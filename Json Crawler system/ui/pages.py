"""四阶段采集工作台：浮动导航、磨砂容器与紧凑表单。"""
import tkinter as tk
from tkinter import ttk

from .glass import AmbientBackground, GlassCard, NavItem, rounded_rect
from .theme import (
    INPUT_BG, LINE, MUTED, PLACEHOLDER, PRIMARY, PRIMARY_FG,
    SELECTION_BG, SELECTION_FG, SIDE, TEXT,
)

NAV = {
    1: ('链接采集', '收集分类商品链接'),
    2: ('商品采集', '获取 Shopify JSON'),
    3: ('数据分析', '组合预览与 CSV'),
    4: ('价格导出', '价格匹配与出表'),
}


class CrawlerPages:
    def _build(self):
        self.backdrop = AmbientBackground(self.root)
        self.backdrop.pack(fill='both', expand=True)
        self.sidebar = GlassCard(self.backdrop, padding=14, fill=SIDE)
        self.project_card = GlassCard(self.backdrop, padding=14)
        self.workspace = GlassCard(self.backdrop, padding=20)
        self.footer_card = GlassCard(self.backdrop, padding=12)
        self._surface_windows = {
            name: self.backdrop.create_window(0, 0, window=widget, anchor='nw')
            for name, widget in (('side', self.sidebar), ('project', self.project_card),
                                 ('workspace', self.workspace), ('footer', self.footer_card))
        }
        side = self.sidebar.content
        brand = tk.Frame(side, bg=SIDE)
        brand.pack(fill='x', pady=(10, 30), padx=8)
        mark = tk.Canvas(brand, width=35, height=35, bg=SIDE, bd=0, highlightthickness=0)
        mark.pack(side='left', padx=(0, 10))
        rounded_rect(mark, 1, 1, 34, 34, 10, fill=PRIMARY, outline='')
        mark.create_line(10, 25, 17, 10, 25, 25, fill=PRIMARY_FG, width=2.4, capstyle='round', joinstyle='round')
        mark.create_line(13, 21, 22, 21, fill=PRIMARY_FG, width=2)
        brand_text = tk.Frame(brand, bg=SIDE)
        brand_text.pack(side='left')
        tk.Label(brand_text, text='ANGLAN', bg=SIDE, fg=TEXT,
                 font=(self.ui_family, 13, 'bold'), anchor='w').pack(anchor='w')
        tk.Label(brand_text, text='JSON CRAWLER', bg=SIDE, fg=MUTED,
                 font=(self.ui_family, 8), anchor='w').pack(anchor='w')
        tk.Label(side, text='工作流程', bg=SIDE, fg=MUTED,
                 font=(self.ui_family, 9), anchor='w').pack(fill='x', padx=14, pady=(0, 9))
        self.nav = {}
        for i, (title, hint) in NAV.items():
            item = NavItem(side, i, title, hint, self.ui_family, lambda n=i: self.show(n))
            item.pack(fill='x', pady=3)
            self.nav[i] = item
        bottom = tk.Frame(side, bg=SIDE)
        bottom.pack(side='bottom', fill='x', padx=9, pady=(12, 8))
        ttk.Button(bottom, text='查看运行日志  ↗', command=self.show_logs,
                   style='Sidebar.TButton').pack(fill='x', pady=(0, 17))
        tk.Frame(bottom, bg=LINE, height=1).pack(fill='x', pady=(0, 14))
        tk.Label(bottom, text='让数据有序流动', bg=SIDE, fg=TEXT,
                 font=(self.ui_family, 9), anchor='w').pack(anchor='w')
        tk.Label(bottom, text='链接 · 商品 · 分析 · 定价', bg=SIDE, fg=MUTED,
                 font=(self.ui_family, 8), anchor='w').pack(anchor='w', pady=(4, 0))

        top = self.project_card.content
        title_row = ttk.Frame(top)
        title_row.pack(fill='x', pady=(0, 5))
        ttk.Label(title_row, text='项目空间', style='Section.TLabel').pack(side='left')
        ttk.Label(title_row, text='●  本地工作台', style='Hint.TLabel').pack(side='right')
        path_row = ttk.Frame(top)
        path_row.pack(fill='x')
        ttk.Button(path_row, text='打开', command=lambda: self.open_folder(self.project.get())).pack(side='right')
        ttk.Button(path_row, text='选择目录', command=self.browse_project).pack(side='right', padx=(8, 8))
        ttk.Entry(path_row, textvariable=self.project).pack(side='left', fill='x', expand=True)

        self.deck = ttk.Frame(self.workspace.content)
        self.deck.pack(fill='both', expand=True)
        self.deck.rowconfigure(0, weight=1)
        self.deck.columnconfigure(0, weight=1)
        self.panels = {}
        for i in range(1, 5):
            panel = ttk.Frame(self.deck)
            panel.grid(row=0, column=0, sticky='nsew')
            self.panels[i] = panel
        self._links(self.panels[1])
        self._products(self.panels[2])
        self._analysis(self.panels[3])
        self._pricing(self.panels[4])

        footer = self.footer_card.content
        self.lock_label = ttk.Label(footer, textvariable=self.lock_text, style='Muted.TLabel', justify='left')
        bar = ttk.Frame(footer)
        bar.pack(fill='x')
        self.stop_button = ttk.Button(bar, text='停止任务', command=self.stop,
                                      state='disabled', style='Danger.TButton')
        self.stop_button.pack(side='right', padx=(12, 0))
        self.status_label = ttk.Label(bar, textvariable=self.status, style='Status.TLabel', anchor='w')
        self.status_label.pack(side='left', fill='x', expand=True)
        self.progress = ttk.Progressbar(footer, mode='determinate')
        self.progress.pack(fill='x', pady=(8, 0))
        self.backdrop.bind('<Configure>', self._layout_surfaces, add='+')
        self.lock_text.trace_add('write', lambda *_: self._layout_surfaces())
        self._layout_surfaces()

    def _layout_surfaces(self, _event=None):
        width, height = self.backdrop.winfo_width(), self.backdrop.winfo_height()
        if width < 50 or height < 50:
            return
        margin, gap, side_width, top_height = 16, 12, 216, 112
        x = margin + side_width + gap
        body_width = max(100, width - x - margin)
        footer_height = 140 if self.lock_text.get() else 90
        page_y = margin + top_height + gap
        footer_y = height - margin - footer_height
        bounds = {
            'side': (margin, margin, side_width, height - margin * 2),
            'project': (x, margin, body_width, top_height),
            'workspace': (x, page_y, body_width, max(100, footer_y - gap - page_y)),
            'footer': (x, footer_y, body_width, footer_height),
        }
        for name, (left, top, w, h) in bounds.items():
            item = self._surface_windows[name]
            self.backdrop.coords(item, left, top)
            self.backdrop.itemconfigure(item, width=w, height=h)
        self.lock_label.configure(wraplength=max(100, body_width - 45))
        self.status_label.configure(wraplength=max(100, body_width - 190))
        if self.lock_text.get():
            if not self.lock_label.winfo_manager():
                self.lock_label.pack(side='top', fill='x', pady=(0, 7), before=self.status_label.master)
        else:
            self.lock_label.pack_forget()

    def _section_header(self, panel, title, hint=None):
        row = ttk.Frame(panel)
        row.pack(fill='x', pady=(0, 8))
        ttk.Label(row, text=title, style='Section.TLabel').pack(side='left')
        if hint:
            ttk.Label(row, text=hint, style='Muted.TLabel').pack(side='right')
        return row

    def _text_box(self, panel):
        frame = tk.Frame(panel, bg=INPUT_BG, highlightbackground=LINE, highlightthickness=1)
        frame.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(frame)
        scroll.pack(side='right', fill='y', padx=(0, 3), pady=5)
        text = tk.Text(frame, height=6, font=(self.mono_family, 11), wrap='word',
                       relief='flat', bd=0, highlightthickness=0, bg=INPUT_BG, fg=TEXT,
                       insertbackground=PRIMARY, padx=14, pady=12, undo=True,
                       selectbackground=SELECTION_BG, selectforeground=SELECTION_FG,
                       yscrollcommand=scroll.set)
        text.pack(side='left', fill='both', expand=True)
        scroll.configure(command=text.yview)
        text.bind('<FocusIn>', lambda _e: frame.configure(highlightbackground=PRIMARY))
        text.bind('<FocusOut>', lambda _e: frame.configure(highlightbackground=LINE))
        return text

    def _links(self, panel):
        self.heading(panel, '链接采集', '从分类页面收集商品链接，开启你的数据工作流。', kicker='WORKFLOW  /  01')
        bottom = ttk.Frame(panel)
        bottom.pack(side='bottom', fill='x', pady=(14, 0))
        self.action(bottom, '采集链接  →', lambda: self.start([1])).pack_configure(side='left', pady=0)
        ttk.Label(bottom, text='代理  127.0.0.1:7897', style='Muted.TLabel').pack(side='right')
        opts = ttk.Frame(panel)
        opts.pack(side='bottom', fill='x', pady=(14, 0))
        self.field(opts, '每分类页数 · 留空不限', self.pages, 10)
        self.field(opts, '自定义 XPath · 可留空', self.xpath, 35).pack_configure(padx=0)
        self._section_header(panel, '分类链接', '每行一个分类 URL')
        self.categories = self._text_box(panel)
        placeholder = tk.Label(self.categories, text='在这里粘贴分类链接\n\nhttps://example.com/collections/all',
                               font=(self.ui_family, 10), bg=INPUT_BG, fg=PLACEHOLDER, justify='left', cursor='xterm')
        placeholder.place(x=14, y=14)
        def sync_placeholder(_event=None):
            if self.categories.get('1.0', 'end-1c') or self.root.focus_get() == self.categories:
                placeholder.place_forget()
            else:
                placeholder.place(x=14, y=14)
        placeholder.bind('<Button-1>', lambda _e: self.categories.focus_set())
        self.categories.bind('<FocusIn>', sync_placeholder, add='+')
        self.categories.bind('<FocusOut>', sync_placeholder, add='+')
        self.categories.bind('<KeyRelease>', sync_placeholder, add='+')
        def on_text_changed(_event=None):
            if self.categories.edit_modified():
                sync_placeholder()
                self.categories.edit_modified(False)
        self.categories.bind('<<Modified>>', on_text_changed)

    def _products(self, panel):
        self.heading(panel, '商品采集', '读取域名链接文件，获取商品详情与图片数据。', kicker='WORKFLOW  /  02')
        self._section_header(panel, '采集设置')
        settings = ttk.Frame(panel)
        settings.pack(fill='x')
        ttk.Label(settings, text='跳过图片位置', style='Muted.TLabel').pack(side='left', padx=(0, 12))
        ttk.Entry(settings, textvariable=self.skip_images, width=20).pack(side='left')
        ttk.Label(settings, text='如 2,3 或 -1,-2；留空不跳图', style='Muted.TLabel').pack(side='left', padx=12)
        checks = ttk.Frame(panel)
        checks.pack(fill='x', pady=(10, 0))
        ttk.Checkbutton(checks, text='使用标准尺码', variable=self.use_standard_sizes).grid(row=0, column=0, sticky='w', padx=(0, 20))
        ttk.Checkbutton(checks, text='保留描述图片（img）', variable=self.keep_description_images).grid(row=0, column=1, sticky='w', padx=(0, 20))
        ttk.Checkbutton(checks, text='保留描述表格（table）', variable=self.keep_description_tables).grid(row=0, column=2, sticky='w')
        self.rule(panel)
        bottom = ttk.Frame(panel)
        bottom.pack(side='bottom', fill='x', pady=(14, 0))
        self.action(bottom, '采集商品  →', lambda: self.start([2])).pack_configure(side='left', pady=0)
        ttk.Label(bottom, text='文件来自项目的 Json 目录', style='Muted.TLabel').pack(side='right')
        head = self._section_header(panel, '域名文件')
        self.file_count = tk.StringVar(value='0 个域名文件')
        ttk.Label(head, textvariable=self.file_count, style='Muted.TLabel').pack(side='left', padx=12)
        ttk.Button(head, text='刷新列表', command=self.refresh_files).pack(side='right')
        frame = tk.Frame(panel, bg=INPUT_BG, highlightbackground=LINE, highlightthickness=1)
        frame.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(frame)
        scroll.pack(side='right', fill='y', padx=(0, 3), pady=5)
        self.product_files = tk.Listbox(frame, height=5, font=(self.ui_family, 11),
                                        relief='flat', bd=0, highlightthickness=0,
                                        bg=INPUT_BG, fg=TEXT, selectbackground=SELECTION_BG,
                                        selectforeground=SELECTION_FG, activestyle='none',
                                        selectborderwidth=6, yscrollcommand=scroll.set)
        self.product_files.pack(fill='both', expand=True, padx=10, pady=10)
        scroll.configure(command=self.product_files.yview)
        self.file_empty = tk.Label(frame, text='暂无域名文件\n完成链接采集后，文件会显示在这里',
                                   bg=INPUT_BG, fg=MUTED, justify='center', font=(self.ui_family, 10))
        self._sync_file_hint()

    def _sync_file_hint(self):
        count = self.product_files.size()
        self.file_count.set(f'{count} 个域名文件')
        if count:
            self.file_empty.place_forget()
        else:
            self.file_empty.place(relx=0.5, rely=0.5, anchor='center')

    def _analysis(self, panel):
        self.heading(panel, '数据分析', kicker='WORKFLOW  /  03')
        settings = ttk.Frame(panel)
        settings.pack(fill='x')
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(2, weight=1)
        options = ttk.Frame(settings)
        options.grid(row=0, column=0, sticky='nsew', padx=(0, 18))
        tk.Frame(settings, bg=LINE, width=1).grid(row=0, column=1, sticky='ns')
        split = ttk.Frame(settings)
        split.grid(row=0, column=2, sticky='nsew', padx=(18, 0))
        self._section_header(options, '组合设置')
        row = ttk.Frame(options)
        row.pack(fill='x')
        ttk.Checkbutton(row, text='Color', variable=self.color).pack(side='left')
        ttk.Entry(row, textvariable=self.option_limits['Color'], width=4).pack(side='left', padx=(10, 8))
        ttk.Label(row, text='颜色上限 · 留空不限', style='Muted.TLabel').pack(side='left')
        row = ttk.Frame(options)
        row.pack(fill='x', pady=(5, 0))
        ttk.Checkbutton(row, text='Size', variable=self.size).pack(side='left', padx=(0, 18))
        ttk.Checkbutton(row, text='其他维度参与组合', variable=self.include_other_options).pack(side='left')
        ttk.Checkbutton(options, text='拆色时不要后面四张', variable=self.color_images_only).pack(anchor='w', pady=(3, 8))
        actions = ttk.Frame(options)
        actions.pack(fill='x')
        for text, callback, style in (
            ('预览组合', lambda: self.start([3], action='preview'), 'TButton'),
            ('导出 CSV  →', lambda: self.start([3]), 'Primary.TButton'),
        ):
            button = ttk.Button(actions, text=text, command=callback, style=style)
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)

        self._section_header(split, '十字段表切分')
        row = ttk.Frame(split)
        row.pack(fill='x')
        ttk.Radiobutton(row, text='均分 N 份', variable=self.split_mode, value='parts').pack(side='left')
        ttk.Radiobutton(row, text='按 title 各自成文件', variable=self.split_mode, value='each').pack(side='left', padx=(12, 0))
        row = ttk.Frame(split)
        row.pack(fill='x', pady=(7, 9))
        ttk.Label(row, text='份数', style='Muted.TLabel').pack(side='left')
        ttk.Spinbox(row, from_=1, to=99, width=3, textvariable=self.split_parts).pack(side='left', padx=(6, 12))
        ttk.Label(row, text='价格列', style='Muted.TLabel').pack(side='left')
        ttk.Combobox(row, textvariable=self.split_price_col, values=('price1', 'price2', ''),
                     width=6, state='readonly').pack(side='left', padx=(6, 0))
        row = ttk.Frame(split)
        row.pack(fill='x')
        ttk.Checkbutton(row, text='覆盖同名输出', variable=self.split_overwrite).pack(side='left')
        button = ttk.Button(row, text='切分 CSV', command=lambda: self.start([5]))
        button.pack(side='right')
        self.buttons.append(button)
        ttk.Label(split, text='读取 *_style.csv；价格列留空保持原序', style='Muted.TLabel').pack(anchor='w', pady=(7, 0))
        self.rule(panel, pady=(13, 12))
        head = self._section_header(panel, '数据预览', '最多显示 200 条')
        ttk.Label(head, textvariable=self.stats, style='Muted.TLabel').pack(side='left', padx=14)
        frame = tk.Frame(panel, bg=INPUT_BG, highlightbackground=LINE, highlightthickness=1)
        frame.pack(fill='both', expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        columns = ('title', 'variant_title', 'price', 'compare_at_price', 'image_status')
        self.preview = ttk.Treeview(frame, columns=columns, show='headings', height=3)
        for name, label, width in zip(columns, ['商品', '组合', '售价', '划线价', '图片'], [255, 210, 85, 85, 65]):
            self.preview.heading(name, text=label)
            self.preview.column(name, width=width, minwidth=60, anchor='w' if name in columns[:2] else 'center')
        vertical = ttk.Scrollbar(frame, command=self.preview.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=self.preview.xview)
        self.preview.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.preview.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.preview_empty = tk.Label(frame, text='还没有预览数据\n点击「预览组合」查看分析结果',
                                      font=(self.ui_family, 10), fg=MUTED, bg=INPUT_BG, justify='center')
        self._sync_preview_hint()

    def _sync_preview_hint(self):
        if self.preview.get_children():
            self.preview_empty.place_forget()
        else:
            self.preview_empty.place(relx=0.5, rely=0.56, anchor='center')

    def _pricing(self, panel):
        self.heading(panel, '价格与导出', kicker='WORKFLOW  /  04')
        self._section_header(panel, '数据来源', '留空使用当前项目 CSV 目录')
        source = ttk.Frame(panel)
        source.pack(fill='x')
        ttk.Button(source, text='清空', command=lambda: self.price_input.set('')).pack(side='right')
        ttk.Button(source, text='选择 CSV', command=self.browse_price_file).pack(side='right', padx=8)
        ttk.Button(source, text='选择目录', command=self.browse_price_dir).pack(side='right')
        ttk.Entry(source, textvariable=self.price_input, width=20).pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.rule(panel, pady=(16, 14))
        columns = ttk.Frame(panel)
        columns.pack(fill='x')
        columns.columnconfigure(0, weight=3)
        columns.columnconfigure(2, weight=2)
        rules = ttk.Frame(columns)
        rules.grid(row=0, column=0, sticky='nsew', padx=(0, 24))
        tk.Frame(columns, bg=LINE, width=1).grid(row=0, column=1, sticky='ns')
        flows = ttk.Frame(columns)
        flows.grid(row=0, column=2, sticky='nsew', padx=(24, 0))
        self._section_header(rules, '价格规则')
        for label, variable in (('同款总价差上限（%）', self.price_spread_percent),
                                ('候选窗口下界', self.window_lower),
                                ('候选窗口上界', self.window_upper)):
            row = ttk.Frame(rules)
            row.pack(fill='x', pady=(0, 6))
            ttk.Label(row, text=label, style='Muted.TLabel').pack(side='left')
            ttk.Entry(row, textvariable=variable, width=10).pack(side='right', padx=(12, 0))
        ttk.Label(rules, text='候选范围 = 参考价 × [下界，上界]', style='Muted.TLabel').pack(anchor='w', pady=(4, 0))
        self._section_header(flows, '产出流程')
        ttk.Checkbutton(flows, text='生成原价表（原价/）', variable=self.make_raw_prices).pack(anchor='w', pady=(4, 6))
        ttk.Checkbutton(flows, text='价格匹配（价格匹配/）', variable=self.match_prices).pack(anchor='w')
        ttk.Label(flows, text='未勾选流程时，仅合并与导出', style='Muted.TLabel').pack(anchor='w', pady=(10, 0))
        self.action(flows, '处理价格  →', lambda: self.start([4])).pack_configure(pady=(12, 0))
