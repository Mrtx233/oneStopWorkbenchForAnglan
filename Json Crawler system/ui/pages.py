"""四阶段采集工作台的布局和表单。"""
import tkinter as tk
from tkinter import ttk

from app.constants import NAMES, PAGE_NAMES, PROXY_SERVER
from .glass import NavItem
from .theme import (
    FOCUS, INPUT_BG, LINE, MUTED, PLACEHOLDER, PRIMARY,
    SELECTION_BG, SELECTION_FG, SIDE, SURFACE, TEXT,
)


class CrawlerPages:
    def _build(self):
        shell = ttk.Frame(self.root)
        shell.pack(fill='both', expand=True)
        shell.columnconfigure(2, weight=1)
        shell.rowconfigure(0, weight=1)

        side = tk.Frame(shell, bg=SIDE, width=216)
        side.grid(row=0, column=0, sticky='ns')
        side.pack_propagate(False)
        tk.Frame(shell, bg=LINE, width=1).grid(row=0, column=1, sticky='ns')
        tk.Label(side, text='Anglan', bg=SIDE, fg=TEXT, font=(self.ui_family, 18),
                 anchor='w').pack(fill='x', padx=20, pady=(24, 0))
        tk.Label(side, text='采集工作台', bg=SIDE, fg=MUTED, font=(self.ui_family, 10),
                 anchor='w').pack(fill='x', padx=20, pady=(4, 28))
        tk.Label(side, text='工作流程', bg=SIDE, fg=MUTED,
                 font=(self.ui_family, 10), anchor='w').pack(fill='x', padx=20, pady=(0, 8))
        self.nav = {}
        for i in range(1, 6):
            item = NavItem(side, i, PAGE_NAMES[i], self.ui_family, self.mono_family, lambda n=i: self.show(n))
            item.pack(fill='x', padx=12, pady=(0, 4))
            self.nav[i] = item

        main = ttk.Frame(shell)
        main.grid(row=0, column=2, sticky='nsew')
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        top = ttk.Frame(main, padding=(24, 12))
        top.grid(row=0, column=0, sticky='ew')
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text='项目目录', style='Section.TLabel').grid(row=0, column=0, padx=(0, 16))
        ttk.Entry(top, textvariable=self.project).grid(row=0, column=1, sticky='ew')
        ttk.Button(top, text='选择目录', command=self.browse_project).grid(row=0, column=2, padx=8)
        ttk.Button(top, text='打开目录', command=lambda: self.open_folder(self.project.get())).grid(row=0, column=3)
        tk.Frame(main, bg=LINE, height=1).grid(row=1, column=0, sticky='ew')

        deck = ttk.Frame(main, padding=(24, 20))
        deck.grid(row=2, column=0, sticky='nsew')
        deck.rowconfigure(0, weight=1)
        deck.columnconfigure(0, weight=1)
        self.panels = {}
        for i, build_page in enumerate((self._links, self._products, self._analysis,
                                         self._pricing, self._image_download), 1):
            panel = ttk.Frame(deck)
            self.panels[i] = panel
            build_page(panel)

        tk.Frame(main, bg=LINE, height=1).grid(row=3, column=0, sticky='ew')
        footer = ttk.Frame(main, padding=(24, 12))
        footer.grid(row=4, column=0, sticky='ew')
        self.lock_label = ttk.Label(footer, textvariable=self.lock_text, style='Muted.TLabel', justify='left')
        bar = ttk.Frame(footer)
        bar.pack(fill='x')
        bar.columnconfigure(1, weight=1)
        status_dot = tk.Canvas(bar, width=8, height=8, bg=SURFACE, bd=0, highlightthickness=0)
        status_dot.grid(row=0, column=0, padx=(0, 8))
        dot = status_dot.create_oval(1, 1, 7, 7, fill=MUTED, outline='')
        self.status.trace_add('write', lambda *_: status_dot.itemconfigure(dot, fill=PRIMARY if self.busy else MUTED))
        status_label = ttk.Label(bar, textvariable=self.status, style='Status.TLabel', anchor='w', justify='left')
        status_label.grid(row=0, column=1, sticky='ew')
        ttk.Button(bar, text='运行日志', command=self.show_logs).grid(row=0, column=2, padx=(12, 8))
        self.stop_button = ttk.Button(bar, text='停止任务', command=self.stop,
                                      state='disabled', style='Danger.TButton')
        self.stop_button.grid(row=0, column=3)
        self.progress = ttk.Progressbar(footer, mode='determinate')
        self.progress.pack(fill='x', pady=(8, 0))
        footer.bind('<Configure>', lambda event: self.lock_label.configure(wraplength=max(1, event.width - 48)))
        status_label.bind('<Configure>', lambda event: status_label.configure(wraplength=event.width))

        def sync_task_details(*_):
            if self.lock_text.get():
                self.lock_label.pack(fill='x', pady=(0, 8), before=bar)
            else:
                self.lock_label.pack_forget()

        self.lock_text.trace_add('write', sync_task_details)

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
        scroll.pack(side='right', fill='y', padx=(0, 4), pady=4)
        text = tk.Text(frame, height=6, font=(self.mono_family, 11), wrap='word',
                       relief='flat', bd=0, highlightthickness=0, bg=INPUT_BG, fg=TEXT,
                       insertbackground=TEXT, padx=12, pady=12, undo=True,
                       selectbackground=SELECTION_BG, selectforeground=SELECTION_FG,
                       yscrollcommand=scroll.set)
        text.pack(side='left', fill='both', expand=True)
        scroll.configure(command=text.yview)
        text.bind('<FocusIn>', lambda _e: frame.configure(highlightbackground=FOCUS))
        text.bind('<FocusOut>', lambda _e: frame.configure(highlightbackground=LINE))
        return text

    def _links(self, panel):
        self.heading(panel, NAMES[1], '从分类页面提取商品链接，按域名保存到项目的 Json 目录')
        bottom = ttk.Frame(panel)
        bottom.pack(side='bottom', fill='x', pady=(16, 0))
        self.action(bottom, '采集链接', lambda: self.start([1])).pack_configure(side='left', pady=0)
        ttk.Label(bottom, text=f'代理：{PROXY_SERVER}', style='Muted.TLabel').pack(side='right', anchor='s', pady=8)
        opts = ttk.Frame(panel)
        opts.pack(side='bottom', fill='x', pady=(16, 0))
        self.field(opts, '每分类最多页数（留空不限）', self.pages, 18)
        self.field(opts, '自定义 XPath（选填）', self.xpath, 40).pack_configure(padx=0)
        self._section_header(panel, '分类链接', '每行一条，可填写「分类名, URL」')
        self.categories = self._text_box(panel)
        placeholder = tk.Label(self.categories, text='https://example.com/collections/all', font=(self.mono_family, 11),
                               bg=INPUT_BG, fg=PLACEHOLDER, padx=0, pady=0, cursor='xterm')
        placeholder.place(x=12, y=12)

        def sync_placeholder(_event=None):
            if self.categories.get('1.0', 'end-1c') or self.root.focus_get() == self.categories:
                placeholder.place_forget()
            else:
                placeholder.place(x=12, y=12)

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
        self.heading(panel, NAMES[2], '读取域名文件，将商品详情、选项和图片链接保存为 JSON')
        self._section_header(panel, '采集设置')
        settings = ttk.Frame(panel)
        settings.pack(fill='x')
        ttk.Label(settings, text='跳过图片位置', style='Muted.TLabel').pack(side='left', padx=(0, 12))
        ttk.Entry(settings, textvariable=self.skip_images, width=20).pack(side='left')
        ttk.Label(settings, text='如 2,3 或 -1,-2；留空不跳图', style='Muted.TLabel').pack(side='left', padx=12)
        checks = ttk.Frame(panel)
        checks.pack(fill='x', pady=(12, 0))
        ttk.Checkbutton(checks, text='使用标准尺码', variable=self.use_standard_sizes).grid(row=0, column=0, sticky='w', padx=(0, 20))
        ttk.Checkbutton(checks, text='保留描述中的图片', variable=self.keep_description_images).grid(row=0, column=1, sticky='w', padx=(0, 20))
        ttk.Checkbutton(checks, text='保留描述中的表格', variable=self.keep_description_tables).grid(row=0, column=2, sticky='w')
        self.rule(panel, pady=(16, 16))
        bottom = ttk.Frame(panel)
        bottom.pack(side='bottom', fill='x', pady=(16, 0))
        self.action(bottom, '采集商品', lambda: self.start([2])).pack_configure(side='left', pady=0)
        ttk.Label(bottom, text='将处理列表中的全部域名文件', style='Muted.TLabel').pack(side='right', anchor='s', pady=8)
        head = self._section_header(panel, '域名文件')
        self.file_count = tk.StringVar(value='0 个域名文件')
        ttk.Label(head, textvariable=self.file_count, style='Muted.TLabel').pack(side='left', padx=12)
        ttk.Button(head, text='刷新列表', command=self.refresh_files).pack(side='right')
        frame = tk.Frame(panel, bg=INPUT_BG, highlightbackground=LINE, highlightthickness=1)
        frame.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(frame)
        scroll.pack(side='right', fill='y', padx=(0, 4), pady=4)
        self.product_files = tk.Listbox(frame, height=5, font=(self.ui_family, 11),
                                        relief='flat', bd=0, highlightthickness=0,
                                        bg=INPUT_BG, fg=TEXT, selectbackground=SELECTION_BG,
                                        selectforeground=SELECTION_FG, activestyle='underline',
                                        selectborderwidth=4, yscrollcommand=scroll.set)
        self.product_files.pack(fill='both', expand=True, padx=8, pady=8)
        scroll.configure(command=self.product_files.yview)
        self.product_files.bind('<FocusIn>', lambda _e: frame.configure(highlightbackground=FOCUS))
        self.product_files.bind('<FocusOut>', lambda _e: frame.configure(highlightbackground=LINE))
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
        self.heading(panel, NAMES[3], '从商品 JSON 整理颜色和尺码组合，预览、导出或切分 CSV')
        settings = ttk.Frame(panel)
        settings.pack(fill='x')
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(2, weight=1)
        options = ttk.Frame(settings)
        options.grid(row=0, column=0, sticky='nsew', padx=(0, 20))
        tk.Frame(settings, bg=LINE, width=1).grid(row=0, column=1, sticky='ns')
        split = ttk.Frame(settings)
        split.grid(row=0, column=2, sticky='nsew', padx=(20, 0))
        self._section_header(options, '商品组合')
        row = ttk.Frame(options)
        row.pack(fill='x')
        ttk.Checkbutton(row, text='Color', variable=self.color).pack(side='left')
        ttk.Entry(row, textvariable=self.option_limits['Color'], width=4).pack(side='left', padx=8)
        ttk.Label(row, text='每件颜色上限（留空不限）', style='Muted.TLabel').pack(side='left')
        row = ttk.Frame(options)
        row.pack(fill='x', pady=(4, 0))
        ttk.Checkbutton(row, text='Size', variable=self.size).pack(side='left', padx=(0, 16))
        ttk.Checkbutton(row, text='其他维度参与组合', variable=self.include_other_options).pack(side='left')
        row = ttk.Frame(options)
        row.pack(fill='x', pady=(8, 4))
        ttk.Label(row, text='无颜色补图数', style='Muted.TLabel').pack(side='left')
        ttk.Entry(row, textvariable=self.gallery_image_limit, width=5).pack(side='left', padx=8)
        ttk.Label(row, text='张（默认 4，可填 0）', style='Muted.TLabel').pack(side='left')
        ttk.Checkbutton(options, text='有颜色维度时只保留颜色图', variable=self.color_images_only).pack(anchor='w', pady=(0, 12))
        actions = ttk.Frame(options)
        actions.pack(fill='x')
        for text, callback, style in (
            ('预览组合', lambda: self.start([3], action='preview'), 'TButton'),
            ('导出 CSV', lambda: self.start([3]), 'Primary.TButton'),
        ):
            button = ttk.Button(actions, text=text, command=callback, style=style)
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)

        self._section_header(split, '切分十字段表')
        row = ttk.Frame(split)
        row.pack(fill='x')
        ttk.Radiobutton(row, text='均分 N 份', variable=self.split_mode, value='parts').pack(side='left')
        ttk.Radiobutton(row, text='按标题分别保存', variable=self.split_mode, value='each').pack(side='left', padx=(12, 0))
        row = ttk.Frame(split)
        row.pack(fill='x', pady=8)
        ttk.Label(row, text='份数', style='Muted.TLabel').pack(side='left')
        ttk.Spinbox(row, from_=1, to=99, width=3, textvariable=self.split_parts).pack(side='left', padx=(8, 12))
        ttk.Label(row, text='价格列', style='Muted.TLabel').pack(side='left')
        ttk.Combobox(row, textvariable=self.split_price_col, values=('price1', 'price2', ''),
                     width=6, state='readonly').pack(side='left', padx=(8, 0))
        row = ttk.Frame(split)
        row.pack(fill='x')
        ttk.Checkbutton(row, text='覆盖同名输出', variable=self.split_overwrite).pack(side='left')
        button = ttk.Button(row, text='切分 CSV', command=lambda: self.start([5]))
        button.pack(side='right')
        self.buttons.append(button)
        ttk.Label(split, text='读取 *_style.csv；价格列留空保持原序', style='Muted.TLabel').pack(anchor='w', pady=(8, 0))
        self.rule(panel, pady=(16, 12))
        head = self._section_header(panel, '数据预览', '最多显示 200 条')
        ttk.Label(head, textvariable=self.stats, style='Muted.TLabel').pack(side='left', padx=12)
        frame = tk.Frame(panel, bg=INPUT_BG, highlightbackground=LINE, highlightthickness=1)
        frame.pack(fill='both', expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        columns = ('title', 'variant_title', 'price', 'compare_at_price', 'image_status')
        self.preview = ttk.Treeview(frame, columns=columns, show='headings', height=3)
        for name, label, width, align in zip(
            columns, ('商品', '组合', '售价', '划线价', '图片'), (248, 192, 88, 88, 80), ('w', 'w', 'e', 'e', 'center'),
        ):
            self.preview.heading(name, text=label, anchor=align)
            self.preview.column(name, width=width, minwidth=60, anchor=align)
        vertical = ttk.Scrollbar(frame, command=self.preview.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=self.preview.xview)
        self.preview.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.preview.grid(row=0, column=0, sticky='nsew')
        self.preview.bind('<FocusIn>', lambda _e: frame.configure(highlightbackground=FOCUS))
        self.preview.bind('<FocusOut>', lambda _e: frame.configure(highlightbackground=LINE))
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
        self.heading(panel, NAMES[4], '合并十字段表，按选定规则处理价格并导出 WooCommerce CSV')
        self._section_header(panel, '数据来源', '留空使用当前项目 CSV 目录')
        source = ttk.Frame(panel)
        source.pack(fill='x')
        ttk.Button(source, text='清空', command=lambda: self.price_input.set('')).pack(side='right')
        ttk.Button(source, text='选择 CSV', command=self.browse_price_file).pack(side='right', padx=8)
        ttk.Button(source, text='选择目录', command=self.browse_price_dir).pack(side='right')
        ttk.Entry(source, textvariable=self.price_input, width=20).pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.rule(panel, pady=(20, 16))
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
            row.pack(fill='x', pady=(0, 8))
            ttk.Label(row, text=label, style='Muted.TLabel').pack(side='left')
            ttk.Entry(row, textvariable=variable, width=10).pack(side='right', padx=(12, 0))
        ttk.Label(rules, text='候选范围 = 参考价 × [下界，上界]', style='Muted.TLabel').pack(anchor='w', pady=(4, 0))
        self._section_header(flows, '导出选项')
        ttk.Checkbutton(flows, text='生成原价表（原价/）', variable=self.make_raw_prices).pack(anchor='w', pady=(4, 8))
        ttk.Checkbutton(flows, text='按尺码匹配价格（价格匹配/）', variable=self.match_prices).pack(anchor='w')
        ttk.Label(flows, text='两项都不选时，仅合并和导出', style='Muted.TLabel').pack(anchor='w', pady=(12, 0))
        self.action(flows, '处理价格并导出', lambda: self.start([4])).pack_configure(pady=(16, 0))

    def _image_download(self, panel):
        self.heading(panel, PAGE_NAMES[5], '下载 WooCommerce CSV 的 Images，并改写为目标站上传路径')
        self._section_header(panel, 'WP 导出文件', '可扫描当前项目的原价/价格匹配目录')
        row = ttk.Frame(panel)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=self.image_csv).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='选择 CSV', command=self.browse_image_csv).pack(side='left', padx=(8, 0))
        ttk.Button(row, text='扫描最新', command=lambda: self.refresh_wp_csv(force_latest=True)).pack(side='left', padx=(8, 0))
        self.rule(panel, pady=(20, 16))
        self._section_header(panel, '下载设置')
        settings = ttk.Frame(panel)
        settings.pack(fill='x')
        ttk.Label(settings, text='目标 WordPress 地址', style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Entry(settings, textvariable=self.image_wp_site).pack(fill='x')
        row = ttk.Frame(settings)
        row.pack(fill='x', pady=(16, 0))
        ttk.Label(row, text='并发线程', style='Muted.TLabel').pack(side='left')
        ttk.Spinbox(row, from_=1, to=50, textvariable=self.image_workers, width=8).pack(side='left', padx=(12, 0))
        ttk.Label(panel, text='下载成功的链接会替换为 /wp-content/uploads/ 年/月路径；失败项保留原链接并生成清单。',
                  style='Muted.TLabel', wraplength=820, justify='left').pack(anchor='w', pady=(20, 0))
        self.action(panel, '下载图片并生成新 CSV', lambda: self.start([6])).pack_configure(pady=(20, 0))
