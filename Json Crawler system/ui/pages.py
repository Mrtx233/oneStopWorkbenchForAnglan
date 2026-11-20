"""工作台各页面。四个阶段各自独立使用，无总览流水线页。"""
import tkinter as tk
from tkinter import scrolledtext, ttk

from .theme import LINE, SIDE, SIDE_FG, SIDE_HOVER, TEXT, WHITE

# 侧栏导航表：页面序号 -> (主标题, 副提示)。序号 1–4 与阶段号一致，四个阶段各自独立运行。
NAV = {
    1: ('链接', '采集分类商品'),
    2: ('商品', '汇总 Shopify JSON'),
    3: ('分析', '导出十字段表'),
    4: ('定价', '匹配价格并出表'),
}


class CrawlerPages:
    def _build(self):
        # 由 build.CrawlerBuild.__init__ 调用：搭左侧导航 + 右侧页面区 + 底部进度条/状态栏。
        # 左侧导航栏固定宽 220；pack_propagate(False) 让子控件不会把栏挤窄。
        side = tk.Frame(self.root, bg=SIDE, width=220)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        # 品牌区：ANGLAN 小字 + 「采集工作台」大字 + 一条主绿短粗线作视觉点缀。
        brand = tk.Frame(side, bg=SIDE)
        brand.pack(fill='x', padx=26, pady=(28, 22))
        tk.Label(
            brand, text='ANGLAN', bg=SIDE, fg='#b7ae9f',
            font=(self.ui_family, 10), anchor='w',
        ).pack(anchor='w')
        tk.Label(
            brand, text='采集工作台', bg=SIDE, fg=WHITE,
            font=(self.ui_family, 18, 'bold'), anchor='w',
        ).pack(anchor='w', pady=(4, 0))
        tk.Frame(brand, bg='#1f6b4a', height=3, width=36).pack(anchor='w', pady=(12, 0))

        # 导航项三件套缓存：item 主标题、row 整行背景、sub 副提示，切换/悬停时一起改色。
        self.nav = {}
        self.nav_rows = {}
        self.nav_hints = {}
        for i, (name, hint) in NAV.items():
            row = tk.Frame(side, bg=SIDE, cursor='hand2')
            row.pack(fill='x', padx=(12, 0), pady=2)
            item = tk.Label(
                row, text=name, anchor='w', bg=SIDE, fg=SIDE_FG,
                font=self.nav_font, cursor='hand2',
            )
            item.pack(fill='x', padx=(16, 14), pady=(8, 0))
            sub = tk.Label(
                row, text=hint, anchor='w', bg=SIDE, fg='#a89f93',
                font=(self.ui_family, 10), cursor='hand2',
            )
            sub.pack(fill='x', padx=(16, 14), pady=(1, 8))
            # 整行、主标题、副提示都绑同一组事件：点击切页(show)，进/出改背景(_hover_nav)。
            # 用默认参数 n=i 冻结当前循环值，避免闭包全部指向最后一个 i 的经典坑。
            for widget in (row, item, sub):
                widget.bind('<Button-1>', lambda _e, n=i: self.show(n))
                widget.bind('<Enter>', lambda _e, n=i: self._hover_nav(n, True))
                widget.bind('<Leave>', lambda _e, n=i: self._hover_nav(n, False))
            self.nav[i] = item
            self.nav_rows[i] = row
            self.nav_hints[i] = sub

        # 侧栏底部「查看日志」入口：贴底 pack，点击打开独立日志窗口；下面补一条分隔细线。
        log = tk.Label(
            side, text='查看日志', bg=SIDE, fg='#d9d0c3',
            font=(self.ui_family, 12), pady=14, cursor='hand2',
        )
        log.pack(side='bottom', fill='x')
        log.bind('<Button-1>', lambda _e: self.show_logs())
        log.bind('<Enter>', lambda e: e.widget.configure(bg=SIDE_HOVER))
        log.bind('<Leave>', lambda e: e.widget.configure(bg=SIDE))
        tk.Frame(side, bg='#3a342c', height=1).pack(side='bottom', fill='x')

        # 右侧主体：padding=(左,上,右,下)。顶部先放「当前项目」目录选择行。
        body = ttk.Frame(self.root, padding=(32, 22, 32, 16))
        body.pack(side='left', fill='both', expand=True)
        top = ttk.Frame(body)
        top.pack(fill='x')
        ttk.Label(top, text='当前项目', style='Muted.TLabel').pack(anchor='w', pady=(0, 4))
        path_row = ttk.Frame(top)
        path_row.pack(fill='x')
        # Entry 双向绑定 self.project：手输或 browse_project 选择都会写回同一个变量。
        ttk.Entry(path_row, textvariable=self.project).pack(side='left', fill='x', expand=True)
        ttk.Button(path_row, text='浏览', command=self.browse_project).pack(side='left', padx=(8, 0))
        # 「打开」直接打开当前项目目录；用 lambda 在点击时读最新值，而非建窗时快照。
        ttk.Button(path_row, text='打开', command=lambda: self.open_folder(self.project.get())).pack(side='left', padx=(8, 0))
        # 运行中这里显示本轮参数摘要 + 「已改，下轮生效」，空闲时为空。
        ttk.Label(body, textvariable=self.lock_text, style='Muted.TLabel').pack(anchor='w', pady=(8, 0))
        self.rule(body, pady=(14, 12))

        # deck 是页面容器：4 个 panel grid 到同一格(0,0)，靠 tkraise 叠放切换，无需销毁重建。
        self.deck = ttk.Frame(body)
        self.deck.rowconfigure(0, weight=1)     # 让 panel 纵向填满可用高度
        self.deck.columnconfigure(0, weight=1)  # 横向同理
        self.panels = {}
        for i in range(1, 5):
            panel = ttk.Frame(self.deck)
            panel.grid(row=0, column=0, sticky='nsew')  # sticky 四向贴合，铺满 deck
            self.panels[i] = panel
        # 依次填充四个阶段页面内容（各 _xxx 只往自己 panel 里摆控件）。
        self._links(self.panels[1])
        self._products(self.panels[2])
        self._analysis(self.panels[3])
        self._pricing(self.panels[4])

        # 底栏：进度条(满宽) + 其下一行(状态文本左、停止按钮右)。
        footer = ttk.Frame(body)
        footer.pack(side='bottom', fill='x')
        self.rule(body, pady=(12, 10), side='bottom')
        # deck 放在 footer 之后 pack，fill+expand 会占满两者间剩余空间，实现「上滚内容、底栏固定」。
        self.deck.pack(fill='both', expand=True)
        self.progress = ttk.Progressbar(footer, mode='determinate')  # 由 poll 按百分比喂值
        self.progress.pack(fill='x')
        bar = ttk.Frame(footer)
        bar.pack(fill='x', pady=(8, 0))
        # 停止按钮初始禁用：无任务时不可点；start 时解禁，见 runtime。
        self.stop_button = ttk.Button(bar, text='停止', command=self.stop, state='disabled', style='Danger.TButton')
        self.stop_button.pack(side='right')
        ttk.Label(bar, textvariable=self.status, style='Status.TLabel').pack(side='left', fill='x', expand=True)

    def _hover_nav(self, index, inside):
        # 悬停高亮：当前页保持选中底色不被 hover 覆盖，所以直接跳过。
        if self.current == index:
            return
        bg = SIDE_HOVER if inside else SIDE
        self.nav_rows[index].configure(bg=bg)
        self.nav[index].configure(bg=bg)
        self.nav_hints[index].configure(bg=bg)

    def _text_box(self, panel):
        # 多行文本框（分类列表用）：等宽字体、12 行高、按词折行；
        # highlightbackground/border 用 LINE 常态描边，聚焦时切成主绿 #1f6b4a 提示可编辑。
        return scrolledtext.ScrolledText(
            panel, height=12, font=(self.mono_family, 12), wrap='word',
            relief='flat', bd=0, highlightthickness=1, highlightbackground=LINE, highlightcolor='#1f6b4a',
            bg=WHITE, fg=TEXT, insertbackground=TEXT, padx=10, pady=8,
        )

    def _links(self, panel):
        # 阶段 01 · 链接采集页：分类输入、页数与 XPath，代理由公共常量固定。
        self.heading(
            panel, '链接采集',
            '浏览器固定使用本地代理 127.0.0.1:7897',
            kicker='阶段 01',
        )
        # self.categories 全文收集分类列表，settings() 里取 '1.0'–'end' 送进子进程。
        self.categories = self._text_box(panel)
        self.categories.pack(fill='both', expand=True)
        opts = ttk.Frame(panel)
        opts.pack(fill='x', pady=(14, 0))
        self.field(opts, '页数，空 = 不限', self.pages, 12)
        self.field(opts, 'XPath，可空', self.xpath, 20)
        self.action(panel, '采集链接', lambda: self.start([1]))  # 只跑阶段 1

    def _products(self, panel):
        # 阶段 02 · 商品采集页：列出项目 Json 目录里的域名文件，配置跳图后采集。
        self.heading(
            panel, '商品采集',
            '',
            kicker='阶段 02',
        )
        row = ttk.Frame(panel)
        row.pack(fill='x')
        # skip_images 文本会被 dialogs._parse_skip_images 解析成整数位置列表。
        self.field(row, '跳图，如 2,3 或 -1,-2', self.skip_images, 22)
        # 两个勾选框同一行，不再配描述文字。
        checks = ttk.Frame(panel)
        checks.pack(fill='x', pady=(12, 0))
        ttk.Checkbutton(checks, text='使用标准尺码',
                        variable=self.use_standard_sizes).pack(side='left')
        ttk.Checkbutton(checks, text='保留描述中的 img 标签',
                        variable=self.keep_description_images).pack(side='left', padx=(16, 0))
        ttk.Checkbutton(checks, text='保留描述中的 table 表格',
                        variable=self.keep_description_tables).pack(side='left', padx=(16, 0))
        # 域名文件列表框：内容来自 refresh_files()（扫 Json 下的域名 CSV / 旧版 JSON）；主绿高亮选中项。
        self.product_files = tk.Listbox(
            panel, height=12, font=(self.ui_family, 12),
            relief='flat', bd=0, highlightthickness=1, highlightbackground=LINE, highlightcolor='#1f6b4a',
            bg=WHITE, fg=TEXT, selectbackground='#1f6b4a', selectforeground=WHITE,
            activestyle='none',
        )
        self.product_files.pack(fill='both', expand=True, pady=(14, 8))
        tools = ttk.Frame(panel)
        tools.pack(fill='x')
        ttk.Button(tools, text='刷新列表', command=self.refresh_files).pack(side='left')
        # 采集按钮：只跑阶段 2；登记进 self.buttons 以便运行时禁用。
        button = ttk.Button(tools, text='采集商品', command=lambda: self.start([2]), style='Primary.TButton')
        button.pack(side='left', padx=(8, 0))
        self.buttons.append(button)

    def _analysis(self, panel):
        # 阶段 03 · 数据分析页：维度勾选与 Color 上限、预览/导出按钮、统计文本、预览表格。
        self.heading(
            panel, '数据分析',
            '',
            kicker='阶段 03',
        )
        row = ttk.Frame(panel)
        row.pack(fill='x')
        box = ttk.Frame(row)
        box.pack(side='left', padx=(0, 28))
        # color：勾选决定是否写入 Color 维度；旁边的短输入框是该维度每件颜色上限。
        ttk.Checkbutton(box, text='Color', variable=self.color).pack(side='left')
        ttk.Entry(box, textvariable=self.option_limits['Color'], width=6).pack(side='left', padx=(8, 0))
        # size：只影响是否写入 Size 列，不参与拆件。
        ttk.Checkbutton(row, text='Size', variable=self.size).pack(side='left')
        # color_images_only：绑定「拆色时不要后面四张」，下游传给阶段 03 的 option_split 决定丢相册图。
        ttk.Checkbutton(row, text='拆色时不要后面四张', variable=self.color_images_only).pack(side='left', padx=(28, 0))
        # include_other_options：是否把 Color/Size 之外的维度纳入组合（与上面控件同行显示）。
        ttk.Checkbutton(row, text='其他维度参与组合',
                        variable=self.include_other_options).pack(side='left', padx=(28, 0))
        actions = ttk.Frame(panel)
        actions.pack(fill='x', pady=(14, 8))
        # 预览按钮：action='preview' 走同一路径，controller 会据此只回预览事件、不落盘。
        preview = ttk.Button(actions, text='预览', command=lambda: self.start([3], action='preview'), style='Primary.TButton')
        preview.pack(side='left')
        self.buttons.append(preview)
        # 导出按钮：默认 action='run'，阶段 03 正式导出 _style.csv。
        export = ttk.Button(actions, text='导出 CSV', command=lambda: self.start([3]), style='Primary.TButton')
        export.pack(side='left', padx=8)
        self.buttons.append(export)
        # 统计文本：由 poll 的 stats/preview 事件写入（商品数、组合数、缺失数）。
        ttk.Label(panel, textvariable=self.stats, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))

        # 切分区：导出完成后可把 CSV 下的 _style.csv 直接切分，无需启动另一程序。
        # 放在预览表之前，避免预览表 expand 把切分区顶出可视区。
        self.rule(panel, pady=(8, 8))
        split_head = ttk.Frame(panel)
        split_head.pack(fill='x')
        ttk.Label(split_head, text='十字段表切分', style='Kicker.TLabel').pack(anchor='w')
        ttk.Label(
            split_head, text='对当前项目 CSV/ 下的 *_style.csv 自动切分',
            style='Muted.TLabel',
        ).pack(anchor='w', pady=(2, 0))
        # 模式行：两种切分方式二选一。
        split_mode_row = ttk.Frame(panel)
        split_mode_row.pack(fill='x', pady=(8, 0))
        ttk.Radiobutton(split_mode_row, text='均分 N 份（按 title 排序后轮询打散）',
                        variable=self.split_mode, value='parts').pack(side='left')
        ttk.Radiobutton(split_mode_row, text='按 title 各自成文件',
                        variable=self.split_mode, value='each').pack(side='left', padx=(20, 0))
        # 参数行：份数(Spinbox) + 价格列(Combobox)，固定宽度不撑满整行。
        split_params = ttk.Frame(panel)
        split_params.pack(fill='x', pady=(6, 0))
        ttk.Label(split_params, text='份数', style='Muted.TLabel').pack(side='left')
        ttk.Spinbox(split_params, from_=1, to=99, width=5,
                    textvariable=self.split_parts).pack(side='left', padx=(6, 20))
        ttk.Label(split_params, text='价格列', style='Muted.TLabel').pack(side='left')
        price_combo = ttk.Combobox(split_params, textvariable=self.split_price_col,
                                   values=('price1', 'price2', ''), width=8, state='readonly')
        price_combo.pack(side='left', padx=(6, 0))
        ttk.Label(split_params, text='（空 = 组内保持原序）', style='Muted.TLabel').pack(side='left', padx=(6, 0))
        ttk.Checkbutton(split_params, text='覆盖同名输出',
                        variable=self.split_overwrite).pack(side='left', padx=(20, 0))
        # 操作行：切分按钮。
        split_actions = ttk.Frame(panel)
        split_actions.pack(fill='x', pady=(8, 0))
        split_btn = ttk.Button(
            split_actions, text='切分 CSV',
            command=lambda: self.start([5]), style='Primary.TButton',
        )
        split_btn.pack(side='left')
        self.buttons.append(split_btn)

        # 预览表：expand 填满剩余高度，放在切分区之后。
        frame = ttk.Frame(panel)
        frame.pack(fill='both', expand=True, pady=(12, 0))
        # 预览表列键与 runtime poll 里 preview 事件行的字段名一致（row.get 按键取值）。
        columns = ('title', 'variant_title', 'price', 'compare_at_price', 'image_status')
        self.preview = ttk.Treeview(frame, columns=columns, show='headings', height=8)
        # zip 同时给出 键 / 中文表头 / 初始列宽，minwidth=50 防止列被压没。
        for name, label, width in zip(columns, ['商品', '组合', '售价', '划线价', '图'], [260, 220, 90, 90, 70]):
            self.preview.heading(name, text=label)
            self.preview.column(name, width=width, minwidth=50)
        # 竖向滚动条与 Treeview 互相绑定 yscrollcommand/yview，实现联动。
        scroll = ttk.Scrollbar(frame, command=self.preview.yview)
        self.preview.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.preview.pack(side='left', fill='both', expand=True)

    def _pricing(self, panel):
        # 阶段 04 · 价格与导出页：输入文件/目录、目录与 CSV 选择按钮、价格窗口二选一、产出流程勾选。
        self.heading(
            panel, '价格与导出',
            '',
            kicker='阶段 04',
        )
        box = ttk.Frame(panel)
        box.pack(fill='x')
        # price_input：留空走项目 CSV 默认目录；由下面按钮或手输填充。
        self.field(box, '输入文件或目录', self.price_input, 50)
        row = ttk.Frame(box)
        row.pack(side='left', pady=(18, 0))
        # 三个按钮分别写 price_input：选目录、选单个 csv、清空回默认。
        ttk.Button(row, text='选择目录', command=self.browse_price_dir).pack(side='left')
        ttk.Button(row, text='选择 CSV', command=self.browse_price_file).pack(side='left', padx=8)
        ttk.Button(row, text='清空', command=lambda: self.price_input.set('')).pack(side='left')
        limits = ttk.Frame(panel)
        limits.pack(fill='x', pady=(18, 0))
        # 尺码梯度定价：价差上限 + 候选窗口（参考价 × [下界, 上界]）。
        self.field(limits, '同款总价差上限（%）', self.price_spread_percent, 10)
        self.field(limits, '候选窗口下界', self.window_lower, 10)
        self.field(limits, '候选窗口上界', self.window_upper, 10)
        # 产出流程：勾哪个跑哪个，没勾的流程整段跳过、不落对应文件。横排是为了不把按钮顶出页面。
        self.rule(panel, pady=(12, 6))
        flows = ttk.Frame(panel)
        flows.pack(fill='x')
        ttk.Label(flows, text='产出流程', style='Muted.TLabel').pack(side='left', padx=(0, 12))
        ttk.Checkbutton(flows, text='原价表（原价/）',
                        variable=self.make_raw_prices).pack(side='left')
        ttk.Checkbutton(flows, text='价格匹配（价格匹配/）',
                        variable=self.match_prices).pack(side='left', padx=(12, 0))
        self.action(panel, '处理价格', lambda: self.start([4])).pack_configure(pady=(8, 0))
