"""工作台界面搭建。"""
from collections import deque
import tkinter as tk
from tkinter import ttk

from app.project_paths import default_project_dir
from app.user_settings import load_user_settings
from controller import Controller
from .glass import CONTROL_SLICE, indicator_image, rounded_image
from .theme import (
    BG, DANGER, DANGER_BG, DANGER_HOVER, DANGER_PRESSED,
    DISABLED_BG, DISABLED_FG, FOCUS, HOVER, INPUT_BG, LINE, MONO_CANDIDATES,
    MUTED, PRESSED, PRIMARY, PRIMARY_FG, PRIMARY_HOVER, PRIMARY_PRESSED, RAISED,
    SCROLL, SCROLL_HOVER, SELECTION_BG, SELECTION_FG, SOFT, SURFACE,
    TEXT, UI_CANDIDATES, choose_font,
)


class CrawlerBuild:
    def __init__(self, root):
        # root 是 main.py 建好的 Tk 根窗口；这里保存引用并配置窗口标题、初始与最小尺寸。
        self.root = root
        root.title('Anglan · 采集工作台')
        root.geometry('1200x800')
        root.minsize(1080, 760)            # 允许用户缩小的下限，防止控件被挤压重叠
        # controller 是与 UI 无关的调度器：真正跑阶段的是它的子进程，UI 只通过它发指令、读事件。
        self.controller = Controller()
        self.current = 1                   # 当前显示的页面序号（1–4 对应四个阶段）
        self.closing = False               # 用户已请求关窗、正在等待子进程保存完的标志
        self.busy = False                  # 是否有任务在跑：跑时禁用按钮、忽略再次 start
        self.active_settings = None        # 本轮已提交给子进程的参数快照，用于「已改，下轮生效」提示
        # logs 是滚动缓冲：maxlen=6000 防长时间采集日志无限增长撑爆内存；日志窗口按需从这里回放。
        self.logs = deque(maxlen=6000)
        self.log_window = None             # 日志子窗口（Toplevel），未打开时为 None / 已关闭
        self.log_text = None               # 日志子窗口内的文本控件
        saved_settings = load_user_settings()
        # 浏览器路径只从本机配置读取，没有界面绑定；留空则自动探测 Chrome/Edge。
        self.browser_path = str(saved_settings.get('browser_path') or '')
        # 以下 StringVar/BooleanVar 供控件绑定或动态显示，settings() 读取输入快照。
        self.project = tk.StringVar(value=default_project_dir())   # 项目根目录，初值取本机上次目录等
        self.pages = tk.StringVar(value='')                        # 每分类最大页数，留空 = 不限
        self.xpath = tk.StringVar()                                # 自定义 XPath，可空
        self.skip_images = tk.StringVar(value='')                  # 跳图位置串，如 2,3 或 -1,-2
        self.use_standard_sizes = tk.BooleanVar(
            value=saved_settings.get('use_standard_sizes', False) is True,
        )  # 阶段 02：默认关闭，保留网站尺码值
        self.keep_description_images = tk.BooleanVar(
            value=saved_settings.get('keep_description_images', False) is True,
        )  # 阶段 02：描述是否保留 img，链接和视频仍清理
        self.keep_description_tables = tk.BooleanVar(
            value=saved_settings.get('keep_description_tables', False) is True,
        )  # 阶段 02：描述是否保留 table 表格，默认删除
        self.price_input = tk.StringVar()                          # 阶段 04 的输入文件或目录，留空走默认
        self.price_spread_percent = tk.StringVar(value='30')      # 同款最高/最低价的总价差百分比
        self.window_lower = tk.StringVar(value='0.75')             # 阶段 04 候选窗口下界（参考价 × 下界）
        self.window_upper = tk.StringVar(value='1.25')             # 阶段 04 候选窗口上界（参考价 × 上界）
        self.make_raw_prices = tk.BooleanVar(value=False)         # 阶段 04：是否生成原价表，默认不勾选
        self.match_prices = tk.BooleanVar(value=True)             # 阶段 04：是否做价格匹配
        self.color = tk.BooleanVar(value=True)                     # 是否写入 Color 维度
        self.size = tk.BooleanVar(value=True)                      # 是否写入 Size 维度
        self.include_other_options = tk.BooleanVar(
            value=saved_settings.get('include_other_options', False) is True,
        )  # 阶段 03：在 Color/Size 勾选之外加入其他维度
        self.color_images_only = tk.BooleanVar(value=False)        # 有颜色维度时只保留本块颜色图
        saved_gallery_limit = str(saved_settings.get('gallery_image_limit', 4)).strip()
        if not saved_gallery_limit.isdecimal():
            saved_gallery_limit = '4'
        self.gallery_image_limit = tk.StringVar(value=saved_gallery_limit)  # 无 Color 维度时的相册补图数
        self.option_limits = {'Color': tk.StringVar(value='')}     # Color 每件上限，留空 = 不限
        # 阶段三切分后置动作：两种模式（均分 N 份 / 按 title 各自成文件）+ 份数 + 价格列。
        self.split_mode = tk.StringVar(value='parts')              # 切分模式：parts=均分 / each=按title分类
        self.split_parts = tk.StringVar(value='2')                # 均分拆分的份数（Spinbox 绑定）
        self.split_price_col = tk.StringVar(value='price1')        # 均分拆分的价格列（price1/price2，空=保持原序）
        self.split_overwrite = tk.BooleanVar(value=True)           # 是否覆盖同名输出
        self.image_csv = tk.StringVar()
        self.image_wp_site = tk.StringVar()
        self.image_workers = tk.StringVar(value='8')
        self.status = tk.StringVar(value='就绪')                   # 底栏状态行文本
        self.lock_text = tk.StringVar(value='')                    # 底栏「本轮参数」摘要，运行中才填
        self.stats = tk.StringVar(value='')                        # 分析页统计文本（商品数 / 组合数）
        self.buttons = []                  # 收集所有主操作按钮，运行时统一禁用、结束时统一恢复
        self._styles()                     # 先建 ttk 样式，后面的控件才能引用样式名
        self._build()                      # 搭导航、页面、底栏（定义在 pages.CrawlerPages）
        # 给所有用户可调的变量挂写监听：任一输入变化即触发 on_setting_changed，
        # 用于清空预览并在运行中提示「已改，下轮生效」。
        for var in (self.project, self.pages, self.xpath, self.skip_images, self.use_standard_sizes,
                    self.keep_description_images, self.keep_description_tables,
                    self.price_input, self.price_spread_percent,
                    self.window_lower, self.window_upper,
                    self.make_raw_prices, self.match_prices,
                    self.color, self.size, self.include_other_options,
                    self.color_images_only, self.gallery_image_limit, *self.option_limits.values(),
                    self.split_mode, self.split_parts, self.split_price_col, self.split_overwrite,
                    self.image_csv, self.image_wp_site, self.image_workers):
            var.trace_add('write', lambda *_: self.on_setting_changed())
        self.refresh_paths()               # 初次同步一次路径相关显示状态
        self.show(1)                       # 默认停在阶段 01 链接采集页
        # 拦截系统关闭按钮：不直接销毁，先让 close() 判断子进程是否在保存。
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        # 启动事件轮询：100ms 一次，poll 在 Tk 主线程执行，是唯一改写控件的地方（线程安全关键）。
        self.root.after(100, self.poll)

    def _styles(self):
        self.ui_family = choose_font(self.root, UI_CANDIDATES)
        self.mono_family = choose_font(self.root, MONO_CANDIDATES)
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=(self.ui_family, 10), background=SURFACE, foreground=TEXT)
        style.configure('TFrame', background=SURFACE)
        style.configure('TLabel', background=SURFACE, foreground=TEXT)
        style.configure('H.TLabel', font=(self.ui_family, 24), foreground=TEXT)
        style.configure('Muted.TLabel', font=(self.ui_family, 10), foreground=MUTED)
        style.configure('Section.TLabel', font=(self.ui_family, 11, 'bold'), foreground=TEXT)
        style.configure('Status.TLabel', font=(self.ui_family, 10), foreground=TEXT)
        self._theme_images = []
        for name, kind, prefix in (('TCheckbutton', 'check', 'Checkbutton'),
                                   ('TRadiobutton', 'radio', 'Radiobutton')):
            images = [indicator_image(self.root, kind=kind, **state) for state in (
                {}, {'selected': True}, {'disabled': True},
                {'selected': True, 'disabled': True}, {'focused': True},
                {'selected': True, 'focused': True},
            )]
            self._theme_images.extend(images)
            element = 'Workbench.' + prefix + '.indicator'
            style.element_create(element, 'image', images[0],
                                 ('disabled', 'selected', images[3]), ('disabled', images[2]),
                                 ('focus', 'selected', images[5]), ('focus', images[4]),
                                 ('active', 'selected', images[5]), ('active', images[4]),
                                 ('selected', images[1]), sticky='')
            style.layout(name, [(prefix + '.padding', {'sticky': 'nsew', 'children': [
                (element, {'side': 'left', 'sticky': ''}),
                (prefix + '.label', {'side': 'left', 'sticky': 'nsw'}),
            ]})])
            style.configure(name, background=SURFACE, foreground=TEXT, padding=(0, 4))
            style.map(name, background=[('active', SURFACE)],
                      foreground=[('disabled', MUTED), ('active', TEXT)])

        # 图像元素让 ttk 按钮保留键盘操作和 .state()，同时具有圆角与焦点描边。
        palettes = {
            'TButton': (RAISED, LINE, HOVER, PRESSED, SOFT, LINE, TEXT, DISABLED_FG),
            'Primary.TButton': (PRIMARY, PRIMARY, PRIMARY_HOVER, PRIMARY_PRESSED,
                                DISABLED_BG, LINE, PRIMARY_FG, DISABLED_FG),
            'Danger.TButton': (DANGER_BG, DANGER_BG, DANGER_HOVER, DANGER_PRESSED,
                               SOFT, LINE, DANGER, DISABLED_FG),
        }
        for name, (fill, edge, hover, pressed, disabled, disabled_edge, fg, disabled_fg) in palettes.items():
            images = [rounded_image(self.root, color, outline) for color, outline in (
                (fill, edge), (hover, edge), (pressed, edge),
                (disabled, disabled_edge), (fill, FOCUS),
            )]
            self._theme_images.extend(images)
            element = 'Workbench.' + name.replace('.', '_')
            style.element_create(element, 'image', images[0],
                                 ('disabled', images[3]), ('pressed', images[2]),
                                 ('focus', images[4]), ('active', images[1]),
                                 border=CONTROL_SLICE, padding=0, sticky='nsew')
            style.layout(name, [(element, {'sticky': 'nsew', 'children': [
                ('Button.padding', {'sticky': 'nsew', 'children': [
                    ('Button.label', {'sticky': 'nsew'})]})]})])
            style.configure(name, padding=(16, 8), foreground=fg, background=SURFACE,
                            font=(self.ui_family, 10), anchor='center')
            style.map(name, foreground=[('disabled', disabled_fg)],
                      background=[('disabled', SURFACE), ('active', SURFACE), ('pressed', SURFACE)])
        fields = [rounded_image(self.root, fill, edge) for fill, edge in (
            (INPUT_BG, LINE), (INPUT_BG, FOCUS), (SOFT, LINE),
        )]
        self._theme_images.extend(fields)
        style.element_create('Workbench.field', 'image', fields[0],
                             ('disabled', fields[2]), ('focus', fields[1]),
                             border=CONTROL_SLICE, padding=0, sticky='nsew')
        style.layout('TEntry', [('Workbench.field', {'sticky': 'nsew', 'children': [
            ('Entry.padding', {'sticky': 'nsew', 'children': [
                ('Entry.textarea', {'sticky': 'nsew'})]})]})])
        for name in ('TEntry', 'TCombobox', 'TSpinbox'):
            style.configure(name, fieldbackground=INPUT_BG, background=INPUT_BG,
                            foreground=TEXT, insertcolor=TEXT, arrowcolor=MUTED,
                            bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                            padding=(8, 4), arrowsize=12)
            style.map(name, fieldbackground=[('disabled', SOFT), ('readonly', INPUT_BG)],
                      foreground=[('disabled', MUTED)], bordercolor=[('focus', FOCUS)],
                      lightcolor=[('focus', FOCUS)], darkcolor=[('focus', FOCUS)],
                      background=[('active', SOFT), ('readonly', INPUT_BG)],
                      selectbackground=[('!disabled', SELECTION_BG)],
                      selectforeground=[('!disabled', SELECTION_FG)])
        # 文字内边距与九宫格切片分别设置，修改圆角不会再意外改变控件高度。
        style.configure('TEntry', padding=(12, 8), background=SURFACE)
        style.map('TEntry', background=[('disabled', SURFACE), ('readonly', SURFACE),
                                       ('focus', SURFACE), ('active', SURFACE)])
        self.root.option_add('*TCombobox*Listbox.background', INPUT_BG)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', SELECTION_BG)
        self.root.option_add('*TCombobox*Listbox.selectForeground', SELECTION_FG)
        self.root.option_add('*TCombobox*Listbox.font', (self.ui_family, 10))

        style.configure('Treeview', background=INPUT_BG, foreground=TEXT, fieldbackground=INPUT_BG,
                        rowheight=32, font=(self.ui_family, 10), borderwidth=0,
                        bordercolor=INPUT_BG, lightcolor=INPUT_BG, darkcolor=INPUT_BG)
        style.configure('Treeview.Heading', background=SOFT, foreground=MUTED, relief='flat',
                        font=(self.ui_family, 10), padding=(12, 8), borderwidth=0)
        style.map('Treeview', background=[('selected', SELECTION_BG)],
                  foreground=[('selected', SELECTION_FG)])
        style.map('Treeview.Heading', background=[('active', HOVER)])
        style.configure('TProgressbar', background=PRIMARY, troughcolor=INPUT_BG,
                        bordercolor=SURFACE, lightcolor=PRIMARY, darkcolor=PRIMARY,
                        borderwidth=0, thickness=4)
        style.configure('TScrollbar', background=SCROLL, troughcolor=SURFACE,
                        bordercolor=SURFACE, lightcolor=SCROLL, darkcolor=SCROLL,
                        arrowcolor=MUTED, borderwidth=0, width=8, arrowsize=12)
        style.map('TScrollbar', background=[('active', SCROLL_HOVER)])
        for direction, sticky in (('Vertical', 'ns'), ('Horizontal', 'ew')):
            style.layout(direction + '.TScrollbar', [
                (direction + '.Scrollbar.trough', {'sticky': sticky, 'children': [
                    (direction + '.Scrollbar.thumb', {'expand': '1', 'sticky': 'nsew'})]})])
        self.root.configure(background=BG)

    def heading(self, panel, title, text=None):
        head = ttk.Frame(panel)
        head.pack(fill='x', pady=(0, 24))
        ttk.Label(head, text=title, style='H.TLabel').pack(anchor='w')
        if text:
            description = ttk.Label(head, text=text, style='Muted.TLabel', justify='left')
            description.pack(anchor='w', pady=(4, 0), fill='x')
            head.bind('<Configure>', lambda e: description.configure(wraplength=max(100, e.width - 8)))

    def rule(self, panel, pady=(12, 12), side='top'):
        tk.Frame(panel, bg=LINE, height=1).pack(side=side, fill='x', pady=pady)

    def action(self, panel, text, callback):
        button = ttk.Button(panel, text=text, command=callback, style='Primary.TButton')
        button.pack(anchor='w', pady=(16, 0))
        self.buttons.append(button)
        return button

    def field(self, parent, label, variable, width=14):
        row = ttk.Frame(parent)
        row.pack(side='left', fill='x', expand=True, padx=(0, 12))
        ttk.Label(row, text=label, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Entry(row, textvariable=variable, width=width).pack(fill='x')
        return row
