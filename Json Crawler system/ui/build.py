"""工作台界面搭建。"""
from collections import deque
import tkinter as tk
from tkinter import ttk

from app.project_paths import default_project_dir
from app.user_settings import load_user_settings
from controller import Controller
from .theme import (
    ACCENT, BG, DANGER, DANGER_HOVER, LINE, MONO_CANDIDATES, MUTED,
    PRIMARY, PRIMARY_HOVER, SIDE, SIDE_FG, SIDE_HOVER, TEXT, UI_CANDIDATES, WHITE,
    choose_font,
)


class CrawlerBuild:
    def __init__(self, root):
        # root 是 main.py 建好的 Tk 根窗口；这里保存引用并配置窗口标题、初始与最小尺寸。
        self.root = root
        root.title('Anglan · 采集工作台')
        root.geometry('1180x900')          # 首次打开的推荐尺寸（阶段三含切分区，需更高）
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
        self.color_images_only = tk.BooleanVar(value=False)        # 「拆色时不要后面四张」：只留本件颜色图
        self.option_limits = {'Color': tk.StringVar(value='')}     # Color 每件上限，留空 = 不限
        # 阶段三切分后置动作：两种模式（均分 N 份 / 按 title 各自成文件）+ 份数 + 价格列。
        self.split_mode = tk.StringVar(value='parts')              # 切分模式：parts=均分 / each=按title分类
        self.split_parts = tk.StringVar(value='2')                # 均分拆分的份数（Spinbox 绑定）
        self.split_price_col = tk.StringVar(value='price1')        # 均分拆分的价格列（price1/price2，空=保持原序）
        self.split_overwrite = tk.BooleanVar(value=True)           # 是否覆盖同名输出
        self.status = tk.StringVar(value='就绪')                   # 底栏状态行文本
        self.lock_text = tk.StringVar(value='')                    # 顶栏「本轮参数」摘要，运行中才填
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
                    self.color_images_only, *self.option_limits.values(),
                    self.split_mode, self.split_parts, self.split_price_col, self.split_overwrite):
            var.trace_add('write', lambda *_: self.on_setting_changed())
        self.refresh_paths()               # 初次同步一次路径相关显示状态
        self.show(1)                       # 默认停在阶段 01 链接采集页
        # 拦截系统关闭按钮：不直接销毁，先让 close() 判断子进程是否在保存。
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        # 启动事件轮询：100ms 一次，poll 在 Tk 主线程执行，是唯一改写控件的地方（线程安全关键）。
        self.root.after(100, self.poll)

    def _styles(self):
        # 解析实际可用字体族；导航用 ui_family，日志/输入等宽区用 mono_family。
        self.ui_family = choose_font(self.root, UI_CANDIDATES)
        self.mono_family = choose_font(self.root, MONO_CANDIDATES)
        self.nav_font = (self.ui_family, 13)            # 导航项常态字体
        self.nav_font_on = (self.ui_family, 13, 'bold') # 当前页导航项加粗，配合高亮底色
        style = ttk.Style(self.root)
        style.theme_use('clam')  # clam 允许逐控件自定义底色，是这套扁平配色的前提
        # '.' 是所有 ttk 控件的默认样式：统一字号、暖纸底、墨色字。
        style.configure('.', font=(self.ui_family, 12), background=BG, foreground=TEXT)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=TEXT)
        # 以下三种是标题/说明的派生样式，pages 里按 style= 引用。
        style.configure('H.TLabel', font=(self.ui_family, 22, 'bold'), background=BG, foreground=TEXT)   # 页面大标题
        style.configure('Muted.TLabel', font=(self.ui_family, 11), background=BG, foreground=MUTED)      # 灰色说明
        style.configure('Kicker.TLabel', font=(self.ui_family, 11), background=BG, foreground=ACCENT)    # 标题上方小标
        style.configure('Status.TLabel', font=(self.ui_family, 12), background=BG, foreground=TEXT)      # 底栏状态行
        # 勾选框：未选白色指示，选中填主绿；激活态不改变底色以免闪烁。
        style.configure('TCheckbutton', background=BG, foreground=TEXT, indicatorcolor=WHITE, font=(self.ui_family, 13))
        style.map(
            'TCheckbutton',
            background=[('active', BG)],
            foreground=[('active', TEXT)],
            indicatorcolor=[('selected', PRIMARY)],
        )
        # 输入框：亮面底、细描边、padding=8 让文字不贴边。
        style.configure(
            'TEntry',
            fieldbackground=WHITE, foreground=TEXT, insertcolor=TEXT,
            bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=8,
        )
        # 默认按钮：白底扁平；padding=(14,8) 控制内边距；禁用态转灰底灰字。
        style.configure(
            'TButton', background=WHITE, foreground=TEXT, bordercolor=LINE,
            lightcolor=WHITE, darkcolor=LINE, padding=(14, 8), relief='flat', focuscolor=BG,
        )
        style.map(
            'TButton',
            background=[('active', '#e7e1d4'), ('disabled', '#ece7de')],
            foreground=[('disabled', '#8a8378')],
            bordercolor=[('active', '#c9c0b2')],
        )
        # Primary.TButton：主操作绿按钮（开始 / 采集 / 导出），padding 更大更醒目。
        style.configure(
            'Primary.TButton', background=PRIMARY, foreground=WHITE,
            bordercolor=PRIMARY_HOVER, lightcolor=PRIMARY, darkcolor=PRIMARY_HOVER,
            padding=(18, 9),
        )
        style.map(
            'Primary.TButton',
            background=[('active', PRIMARY_HOVER), ('disabled', '#9db8ab')],  # 禁用变浅绿，仍能识别是主按钮
            foreground=[('active', WHITE), ('disabled', WHITE)],
            bordercolor=[('active', PRIMARY_HOVER), ('disabled', '#9db8ab')],
        )
        # Danger.TButton：停止按钮，红色以示区别。
        style.configure(
            'Danger.TButton', background=DANGER, foreground=WHITE,
            bordercolor=DANGER_HOVER, lightcolor=DANGER, darkcolor=DANGER_HOVER,
            padding=(16, 8),
        )
        style.map(
            'Danger.TButton',
            background=[('active', DANGER_HOVER), ('disabled', '#e3c8c8')],
            foreground=[('active', WHITE), ('disabled', DANGER)],
            bordercolor=[('disabled', '#e3c8c8')],
        )
        # 预览表：白底行高 30；表头用深色导航底呼应侧栏；选中行填主绿。
        style.configure(
            'Treeview', background=WHITE, foreground=TEXT, fieldbackground=WHITE,
            rowheight=30, font=(self.ui_family, 11), bordercolor=LINE,
        )
        style.configure(
            'Treeview.Heading', background=SIDE, foreground=SIDE_FG, relief='flat',
            font=(self.ui_family, 11), padding=6,
        )
        style.map(
            'Treeview',
            background=[('selected', PRIMARY)],
            foreground=[('selected', WHITE)],
        )
        style.map('Treeview.Heading', background=[('active', SIDE_HOVER)], foreground=[('active', SIDE_FG)])
        # 进度条：主绿填充、暖灰槽底、thickness=8 细条；运行时由 poll 按百分比喂值。
        style.configure(
            'TProgressbar', background=PRIMARY, troughcolor='#e4dcd0',
            bordercolor=BG, lightcolor=PRIMARY, darkcolor=PRIMARY, thickness=8,
        )
        # 滚动条配色跟主题，避免系统默认灰在暖纸底上突兀。
        style.configure('TScrollbar', background='#ddd4c6', troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)
        # ttk 管不到根窗口本身，这里单独把根窗底色刷成暖纸色，否则边缘露白。
        self.root.configure(background=BG)

    def heading(self, panel, title, text=None, kicker=None):
        # 页面标题区通用排版：可选小标(kicker) + 大标题 + 可选灰底说明（定宽折行）。
        if kicker:
            ttk.Label(panel, text=kicker, style='Kicker.TLabel').pack(anchor='w')
        ttk.Label(panel, text=title, style='H.TLabel').pack(anchor='w', pady=(2, 0))
        if text:
            ttk.Label(
                panel, text=text, style='Muted.TLabel', wraplength=700, justify='left',
            ).pack(anchor='w', pady=(8, 16))

    def rule(self, panel, pady=(8, 8), side='top'):
        # 1px 高 LINE 色细框当分隔线；side 决定贴顶还是贴底（底栏用 bottom）。
        tk.Frame(panel, bg=LINE, height=1).pack(side=side, fill='x', pady=pady)

    def action(self, panel, text, callback):
        # 生成一个主操作按钮，并登记到 self.buttons：start 时统一禁用、finished 时统一恢复。
        button = ttk.Button(panel, text=text, command=callback, style='Primary.TButton')
        button.pack(anchor='w', pady=(14, 0))
        self.buttons.append(button)
        return button

    def field(self, parent, label, variable, width=14):
        # 带灰色小标签的单行输入框组合：variable 双向绑定到 self.* 变量，改即写。
        # width 只是初值，实际由外层 frame 布局拉伸决定。
        row = ttk.Frame(parent)
        row.pack(side='left', fill='x', expand=True, padx=(0, 16))
        ttk.Label(row, text=label, style='Muted.TLabel').pack(anchor='w', pady=(0, 4))
        ttk.Entry(row, textvariable=variable, width=width).pack(fill='x')
        return row
