# -*- coding: utf-8 -*-
"""商品数据转换工具 GUI 主框架。

八个功能的面板与运行逻辑都在这里；各功能的纯逻辑在 features/ 下，便于独立修改。
"""

import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import BooleanVar, IntVar, StringVar, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .constants import (
    DEFAULT_TITLE_COL, DEFAULT_PRICE_COL, DEFAULT_PARTS, SRC_ONLY_KEEP,
)
from .utils import strip_quotes
from .theme import (
    BG, SURFACE, INPUT, TEXT, MUTED, LINE, SIDE, PRIMARY,
    PRIMARY_PRESSED, ON_ACCENT, SELECTION, SELECTED_FG, FOCUS, ERROR,
    configure_theme,
)
from .features import price_check, wp_to_styles, sku_check, sku_update
from .features import split_by_title as split_by_title_mod
from .features import split_by_title_each as split_by_title_each_mod
from .features import slim_src_links as slim_src_links_mod
from .features import json_sizes

_UTILS_PATH = str(Path(__file__).resolve().parents[1])
if _UTILS_PATH not in sys.path:
    sys.path.insert(0, _UTILS_PATH)
from workbench_ui import GlassBackground, GlassPanel, GlassNav, apply_glass_controls

TOOL_DETAILS = (
    ("WP 价格检查", "核对 WP 商品价格，定位需要关注的价格记录。", "核对商品价格"),
    ("WP 还原 styles", "从 WP 数据还原商品 styles，整理后继续使用。", "还原商品规格"),
    ("SKU 查重", "检查商品 SKU，快速发现重复的商品标识。", "检查重复标识"),
    ("SKU 更新", "按现有规则更新商品 SKU，保持商品标识一致。", "整理商品标识"),
    ("CSV 按 title 拆分", "按标题分组并参考价格，把商品均衡拆成指定份数。", "均衡拆分 CSV"),
    ("CSV 按 title 切分", "按每个商品标题分别输出文件，便于逐款整理。", "逐款输出文件"),
    ("图片链接精简", "保留规格引用图片，精简其余图片链接。", "整理商品图片"),
    ("JSON 尺码调整", "先检查商品尺码，再按预设或自定义序列统一调整。", "统一商品尺码"),
)


class SwitchToolGui:
    def __init__(self, root):
        self.root = root
        self.root.title("商品数据转换工具")

        window_width = 1280
        window_height = 860
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.minsize(1100, 760)

        self.run_buttons = []
        self.tab_buttons = {}
        self.frames = {}
        self.running = False
        self._size_checked = None
        self._size_files = []
        self._build_ui()

    def _build_ui(self):
        self.style = configure_theme(self.root)
        apply_glass_controls(self.root)
        self.background = GlassBackground(self.root)
        self.background.pack(fill="both", expand=True)
        self.background.columnconfigure(0, weight=0, minsize=224)
        self.background.columnconfigure(1, weight=1, minsize=450)
        self.background.columnconfigure(2, weight=0, minsize=284)
        self.background.rowconfigure(0, weight=1)

        # 纵向功能栏独立悬浮，工具、工作区和记录各有清晰层次。
        self.sidebar = GlassPanel(self.background, padding=14, fill=SIDE, width=224)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(18, 10), pady=18)
        side = self.sidebar.body
        tk.Label(side, text="ANGLAN  /  UTILITIES", bg=SIDE, fg=PRIMARY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 8))
        tk.Label(side, text="商品数据\n转换工作台", bg=SIDE, fg=TEXT, justify="left",
                 font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        tk.Label(side, text="8 个工具 · 一个工作流", bg=SIDE, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(8, 18))
        self.tab_frame = tk.Frame(side, bg=SIDE)
        self.tab_frame.pack(fill="x")
        tk.Label(side, text="DATA / ORGANIZE / TRANSFORM", bg=SIDE, fg=MUTED,
                 font=("Segoe UI", 7)).pack(side="bottom", anchor="w", pady=(12, 5))

        self.work_panel = GlassPanel(self.background, padding=20, fill=SURFACE)
        self.work_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=(18, 10))
        workspace = self.work_panel.body
        self.tool_number = StringVar(value="TOOL 01 / 08")
        self.tool_title = StringVar()
        self.tool_description = StringVar()
        tk.Label(workspace, textvariable=self.tool_number, bg=SURFACE, fg=PRIMARY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(2, 8))
        tk.Label(workspace, textvariable=self.tool_title, bg=SURFACE, fg=TEXT,
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        self.tool_description_label = tk.Label(
            workspace, textvariable=self.tool_description, bg=SURFACE, fg=MUTED,
            font=("Microsoft YaHei UI", 10), justify="left", wraplength=440,
        )
        self.tool_description_label.pack(anchor="w", fill="x", pady=(8, 18))
        tk.Frame(workspace, bg=LINE, height=1).pack(fill="x", pady=(0, 20))

        form_host = ttk.Frame(workspace)
        form_host.pack(fill="both", expand=True)
        self.form_canvas = tk.Canvas(form_host, bg=SURFACE, highlightthickness=0, bd=0)
        form_scroll = ttk.Scrollbar(form_host, orient="vertical", command=self.form_canvas.yview)
        form_scroll.pack(side="right", fill="y")
        self.form_canvas.pack(side="left", fill="both", expand=True)
        self.form_canvas.configure(yscrollcommand=form_scroll.set)
        self.cards_frame = ttk.Frame(self.form_canvas)
        self._form_window = self.form_canvas.create_window(0, 0, anchor="nw", window=self.cards_frame)
        self.cards_frame.bind("<Configure>", lambda _e: self.form_canvas.configure(
            scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind("<Configure>", self._resize_workspace)

        self.log_panel = GlassPanel(self.background, padding=16, fill=SURFACE, width=284)
        self.log_panel.grid(row=0, column=2, sticky="nsew", padx=(0, 18), pady=(18, 10))
        log_frame = self.log_panel.body
        log_heading = tk.Frame(log_frame, bg=SURFACE)
        log_heading.pack(fill="x", pady=(4, 6))
        tk.Label(log_heading, text="运行记录", bg=SURFACE, fg=TEXT,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        tk.Label(log_heading, text="LIVE", bg=SURFACE, fg=PRIMARY,
                 font=("Segoe UI", 8, "bold")).pack(side="right")
        tk.Label(log_frame, text="当前操作的进度与输出", bg=SURFACE, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 16))

        self.log_box = ScrolledText(
            log_frame, wrap="word", width=20, height=1,
            font=("Consolas", 10),
            bg=INPUT, fg=TEXT,
            insertbackground=TEXT,
            selectbackground=SELECTION, selectforeground=SELECTED_FG,
            highlightbackground=LINE, highlightcolor=FOCUS, highlightthickness=1,
            padx=10, pady=10, relief="flat",
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.frame.configure(background=INPUT)
        self.log_box.vbar.destroy()
        self.log_box.vbar = ttk.Scrollbar(self.log_box.frame, orient="vertical", command=self.log_box.yview)
        self.log_box.vbar.pack(side="right", fill="y", before=self.log_box._w)
        self.log_box.configure(yscrollcommand=self.log_box.vbar.set)
        ttk.Button(log_frame, text="清空记录", command=self.clear_log).pack(fill="x", pady=(12, 0))

        self.status_panel = GlassPanel(self.background, padding=14, fill=SURFACE, height=70)
        self.status_panel.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=(0, 18))
        self.status = StringVar(value="✨ 就绪")
        tk.Label(self.status_panel.body, textvariable=self.status, bg=SURFACE, fg=PRIMARY,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Label(self.status_panel.body, text="选择工具  →  配置输入  →  查看结果", bg=SURFACE,
                 fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="right")

        # ── 通用工具面板 ──
        operations = [
            ("wp价格检查", "WP 价格检查", "选择 WP CSV文件",
             price_check.price_check, [("CSV 文件", "*.csv")], False),
            ("WP 还原 styles", "WP 还原 styles", "选择 wp-*.csv 文件",
             wp_to_styles.wp_to_styles, [("CSV 文件", "*.csv")], False),
            ("SKU 查重", "SKU 查重", "选择 wp-*.csv 文件",
             sku_check.sku_check, [("CSV 文件", "*.csv")], False),
            ("SKU 更新", "SKU 更新", "选择 wp-*.csv 文件",
             sku_update.sku_update, [("CSV 文件", "*.csv")], False),
        ]
        for idx, (internal_name, btn_name, prompt, func, filetypes, allow_dir) in enumerate(operations):
            self._build_tool_panel(idx, internal_name, btn_name, prompt, func, filetypes, allow_dir)

        # ── 第 5 个：CSV 按 title 拆分 ──
        self._build_split_panel(4)

        # ── 第 6 个：CSV 按 title 切分 ──
        self._build_split_each_panel(5)

        # ── 第 7 个：图片链接精简 ──
        self._build_src_slim_panel(6)

        # ── 第 8 个：JSON 尺码调整 ──
        self._build_size_panel(7)

        self.select_tab(operations[0][0])

    # ---------- 通用工具面板 ----------

    def _build_tool_panel(self, idx, internal_name, btn_name, prompt, func, filetypes, allow_dir=False):
        f = ttk.Frame(self.cards_frame)
        self.frames[internal_name] = f

        content = ttk.Frame(f)
        content.pack(fill="x", expand=False)

        ttk.Label(content, text="01  /  输入文件", font=("Microsoft YaHei UI", 10, "bold"),
                  foreground=PRIMARY).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(content, text=prompt, foreground=MUTED).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        var = StringVar()
        ttk.Entry(content, textvariable=var, font=("Microsoft YaHei UI", 11)).grid(
            row=2, column=0, columnspan=2, sticky="ew")

        if allow_dir:
            browse_cmd = lambda: self._browse_dir(var)
        else:
            browse_cmd = lambda: self.browse_file(var, filetypes)
        ttk.Button(content, text="浏览文件", command=browse_cmd).grid(row=2, column=2, padx=(10, 0))

        ttk.Label(content, text="02  /  执行与输出", font=("Microsoft YaHei UI", 10, "bold"),
                  foreground=PRIMARY).grid(row=3, column=0, columnspan=3, sticky="w", pady=(32, 12))
        ttk.Label(content, text="确认输入文件后开始运行。处理进度与结果路径\n将显示在右侧运行记录中。",
                  foreground=MUTED, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(0, 16))

        run_button = ttk.Button(content, text="▶ 运行", style="Primary.TButton",
                                command=lambda: self.run_operation(internal_name, func, var.get()))
        run_button.grid(row=5, column=0, columnspan=3, sticky="ew")
        self.run_buttons.append(run_button)

        content.columnconfigure(0, weight=1)
        self._create_nav_button(idx, internal_name, btn_name)

    # ---------- CSV 按 title 拆分面板 ----------

    def _build_split_panel(self, idx):
        internal_name = "CSV 按 title 拆分"
        f = ttk.Frame(self.cards_frame)
        self.frames[internal_name] = f

        self.split_path_var = StringVar()
        self.split_title_var = StringVar(value=DEFAULT_TITLE_COL)
        self.split_price_var = StringVar(value=DEFAULT_PRICE_COL)
        self.split_parts_var = IntVar(value=DEFAULT_PARTS)
        self.split_overwrite_var = BooleanVar(value=True)

        content = ttk.Frame(f)
        content.pack(fill="x", expand=False)
        content.columnconfigure(1, weight=1)

        ttk.Label(content, text="目标:", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        ttk.Entry(content, textvariable=self.split_path_var, font=("Microsoft YaHei UI", 11)).grid(
            row=1, column=1, sticky="ew", pady=6)
        ttk.Button(content, text="📂 浏览",
                   command=lambda: self._browse_dir(self.split_path_var)).grid(
            row=1, column=2, padx=(15, 0), pady=6)

        param_row = ttk.Frame(content)
        param_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        for column in range(3):
            param_row.columnconfigure(column, weight=1, uniform="split_parameters")
        ttk.Label(param_row, text="分组列:").grid(row=0, column=0, sticky="w")
        ttk.Entry(param_row, textvariable=self.split_title_var, width=9).grid(
            row=1, column=0, sticky="ew", padx=(0, 10), pady=(4, 0))
        ttk.Label(param_row, text="价格列:").grid(row=0, column=1, sticky="w")
        ttk.Entry(param_row, textvariable=self.split_price_var, width=9).grid(
            row=1, column=1, sticky="ew", padx=(0, 10), pady=(4, 0))
        ttk.Label(param_row, text="拆分份数:").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(param_row, from_=1, to=99, width=5, textvariable=self.split_parts_var).grid(
            row=1, column=2, sticky="ew", pady=(4, 0))

        ttk.Checkbutton(content, text="覆盖同名文件（不勾选则加「_新」另存）",
                        variable=self.split_overwrite_var).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        run_button = ttk.Button(content, text="🚀 开始拆分", style="Primary.TButton", command=self._run_split)
        run_button.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(15, 0))
        self.run_buttons.append(run_button)

        self._create_nav_button(idx, internal_name, "CSV 按 title 拆分")

    def _run_split(self):
        input_path = strip_quotes(self.split_path_var.get())
        if not input_path:
            messagebox.showwarning("缺少文件", "请先选择 CSV 文件或文件夹。")
            return
        if not Path(input_path).exists():
            messagebox.showerror("路径不存在", input_path)
            return

        try:
            parts = int(self.split_parts_var.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning("提示", "拆分份数必须是数字。")
            return
        if parts < 1:
            messagebox.showwarning("提示", "拆分份数至少为 1。")
            return

        title_col = self.split_title_var.get().strip()
        if not title_col:
            messagebox.showwarning("提示", "请填写分组列名。")
            return
        price_col = self.split_price_var.get().strip()
        overwrite = self.split_overwrite_var.get()

        self.set_running(True)
        self._log_separator("CSV 按 title 拆分")
        self.log(f"输入: {input_path}")
        self.log(f"分组列: {title_col}    价格列: {price_col or '（空，保持原序）'}    份数: {parts}")

        def worker():
            try:
                files = split_by_title_mod.collect_csv_files_split(input_path)
                if not files:
                    raise ValueError(f"未找到 csv 文件: {input_path}")
                self.log(f"待处理 {len(files)} 个文件")
                self.log("-" * 60)

                total_rows = total_files = failed = 0
                for path in files:
                    try:
                        stat = split_by_title_mod.split_by_title(path, parts, title_col, price_col,
                                                                 overwrite=overwrite, log=self.log)
                    except Exception as exc:
                        failed += 1
                        self.log(f"[失败] {path.name}：{exc}")
                        continue
                    if stat:
                        total_files += 1
                        total_rows += stat["total"]

                self.log("-" * 60)
                summary = f"处理完成：{total_files} 个文件，共 {total_rows} 行，各拆成 {parts} 份"
                if failed:
                    summary += f"，失败 {failed} 个"
                self.log(summary)
            except Exception as exc:
                self.log(f"失败: {exc}")
                self.root.after(0, lambda: messagebox.showerror("运行失败", str(exc)))
            finally:
                self.root.after(0, lambda: self.set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- CSV 按 title 切分面板 ----------

    def _build_split_each_panel(self, idx):
        internal_name = "CSV 按 title 切分"
        f = ttk.Frame(self.cards_frame)
        self.frames[internal_name] = f

        self.split_each_path_var = StringVar()
        self.split_each_title_var = StringVar(value=DEFAULT_TITLE_COL)
        self.split_each_overwrite_var = BooleanVar(value=True)

        content = ttk.Frame(f)
        content.pack(fill="x", expand=False)
        content.columnconfigure(1, weight=1)

        ttk.Label(content, text="目标:", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        ttk.Entry(content, textvariable=self.split_each_path_var, font=("Microsoft YaHei UI", 11)).grid(
            row=1, column=1, sticky="ew", pady=6)
        ttk.Button(content, text="📂 浏览",
                   command=lambda: self._browse_dir(self.split_each_path_var)).grid(
            row=1, column=2, padx=(15, 0), pady=6)

        param_row = ttk.Frame(content)
        param_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(param_row, text="分组列:", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Entry(param_row, textvariable=self.split_each_title_var, width=12).pack(side="left", padx=(4, 15))

        ttk.Checkbutton(content, text="覆盖同名文件（不勾选则加「_新」另存）",
                        variable=self.split_each_overwrite_var).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        run_button = ttk.Button(content, text="🚀 开始切分", style="Primary.TButton", command=self._run_split_each)
        run_button.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(15, 0))
        self.run_buttons.append(run_button)

        self._create_nav_button(idx, internal_name, "CSV 按 title 切分")

    def _run_split_each(self):
        input_path = strip_quotes(self.split_each_path_var.get())
        if not input_path:
            messagebox.showwarning("缺少文件", "请先选择 CSV 文件或文件夹。")
            return
        if not Path(input_path).exists():
            messagebox.showerror("路径不存在", input_path)
            return

        title_col = self.split_each_title_var.get().strip()
        if not title_col:
            messagebox.showwarning("提示", "请填写分组列名。")
            return
        overwrite = self.split_each_overwrite_var.get()

        self.set_running(True)
        self._log_separator("CSV 按 title 切分")
        self.log(f"输入: {input_path}")
        self.log(f"分组列: {title_col}    覆盖: {'是' if overwrite else '否'}")

        def worker():
            try:
                files = split_by_title_mod.collect_csv_files_split(input_path)
                if not files:
                    raise ValueError(f"未找到 csv 文件: {input_path}")
                self.log(f"待处理 {len(files)} 个文件")
                self.log("-" * 60)

                total_rows = total_files = total_titles = failed = 0
                for path in files:
                    try:
                        stat = split_by_title_each_mod.split_by_title_each(path, title_col,
                                                                           overwrite=overwrite, log=self.log)
                    except Exception as exc:
                        failed += 1
                        self.log(f"[失败] {path.name}：{exc}")
                        continue
                    if stat:
                        total_files += 1
                        total_rows += stat["total"]
                        total_titles += stat["groups"]

                self.log("-" * 60)
                summary = f"处理完成：{total_files} 个文件，共 {total_rows} 行 / {total_titles} 个 title"
                if failed:
                    summary += f"，失败 {failed} 个"
                self.log(summary)
            except Exception as exc:
                self.log(f"失败: {exc}")
                self.root.after(0, lambda: messagebox.showerror("运行失败", str(exc)))
            finally:
                self.root.after(0, lambda: self.set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 图片链接精简面板 ----------

    def _build_src_slim_panel(self, idx):
        internal_name = "图片链接精简"
        f = ttk.Frame(self.cards_frame)
        self.frames[internal_name] = f

        self.slim_path_var = StringVar()
        self.slim_keep_var = IntVar(value=SRC_ONLY_KEEP)
        self.slim_overwrite_var = BooleanVar(value=True)

        content = ttk.Frame(f)
        content.pack(fill="x", expand=False)
        content.columnconfigure(1, weight=1)

        ttk.Label(
            content,
            text=("按 styles1 精简 src_links 列：\n"
                  "  · 已被 styles1 引用的图片 → 全部保留\n"
                  "  · styles1 未引用的图片 → 只保留开头若干张，其余删除\n"
                  "精简结果写回源文件的 src_links 列。"),
            font=("Microsoft YaHei UI", 10),
            foreground=MUTED, wraplength=480,
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 15))

        ttk.Label(content, text="目标:", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        ttk.Entry(content, textvariable=self.slim_path_var, font=("Microsoft YaHei UI", 11)).grid(
            row=1, column=1, sticky="ew", pady=6)
        ttk.Button(content, text="📂 浏览",
                   command=lambda: self._browse_dir(self.slim_path_var)).grid(
            row=1, column=2, padx=(15, 0), pady=6)

        param_row = ttk.Frame(content)
        param_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        ttk.Label(param_row, text="未引用图片保留张数:", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Spinbox(param_row, from_=0, to=99, width=5, textvariable=self.slim_keep_var).pack(
            side="left", padx=(6, 0))

        ttk.Checkbutton(content, text="覆盖原文件（自动备份为 .bak；\n不勾选则另存为「_图片精简」）",
                        variable=self.slim_overwrite_var).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        run_button = ttk.Button(content, text="🚀 开始精简", style="Primary.TButton", command=self._run_src_slim)
        run_button.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(15, 0))
        self.run_buttons.append(run_button)

        self._create_nav_button(idx, internal_name, "图片链接精简")

    def _run_src_slim(self):
        input_path = strip_quotes(self.slim_path_var.get())
        if not input_path:
            messagebox.showwarning("缺少文件", "请先选择 Excel 文件或文件夹。")
            return
        if not Path(input_path).exists():
            messagebox.showerror("路径不存在", input_path)
            return

        try:
            keep = int(self.slim_keep_var.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning("提示", "保留张数必须是数字。")
            return
        if keep < 0:
            messagebox.showwarning("提示", "保留张数不能为负数。")
            return

        overwrite = self.slim_overwrite_var.get()

        self.set_running(True)
        self._log_separator("图片链接精简")
        self.log(f"输入: {input_path}")
        self.log(f"未引用图片保留张数: {keep}    覆盖原文件: {'是（备份 .bak）' if overwrite else '否'}")

        def worker():
            try:
                slim_src_links_mod.slim_src_links_target(input_path, keep=keep, overwrite=overwrite, log=self.log)
            except Exception as exc:
                self.log(f"失败: {exc}")
                self.root.after(0, lambda: messagebox.showerror("运行失败", str(exc)))
            finally:
                self.root.after(0, lambda: self.set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- JSON 尺码面板 ----------

    def _build_size_panel(self, idx):
        name = "JSON 尺码调整"
        content = ttk.Frame(self.cards_frame)
        self.frames[name] = content
        content.columnconfigure(1, weight=1)
        self.size_path_var = StringVar()
        self.size_count_var = StringVar(value="8")
        self.size_custom_var = StringVar()
        self.size_add_missing_var = BooleanVar(value=True)
        self.size_backup_var = BooleanVar(value=True)
        self.size_adaptive_var = BooleanVar(value=False)

        ttk.Label(content, text="01  /  输入商品 JSON", foreground=PRIMARY,
                  font=("Microsoft YaHei UI", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Entry(content, textvariable=self.size_path_var).grid(
            row=1, column=0, columnspan=3, sticky="ew")
        browse = ttk.Frame(content)
        browse.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(browse, text="选择文件", command=lambda: self.browse_file(
            self.size_path_var, [("JSON 文件", "*.json")],
        )).pack(side="left")
        ttk.Button(browse, text="选择目录", command=self._browse_size_dir).pack(side="left", padx=(4, 0))

        ttk.Label(content, text="02  /  尺码规则", foreground=PRIMARY,
                  font=("Microsoft YaHei UI", 10, "bold")).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(24, 10))
        presets = ttk.Frame(content)
        presets.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(presets, text="预设数量").pack(side="left", padx=(0, 10))
        ttk.Spinbox(presets, from_=2, to=9, width=5, textvariable=self.size_count_var).pack(side="left")
        ttk.Label(presets, text="自定义为空时使用").pack(side="left", padx=(10, 0))
        ttk.Label(content, text="自定义尺码（可选）").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Entry(content, textvariable=self.size_custom_var).grid(
            row=6, column=0, columnspan=3, sticky="ew")
        ttk.Label(content, text="用逗号或分号分隔，例如：S, M, L",
                  foreground=MUTED).grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.size_preview = ttk.Label(content, foreground=PRIMARY, wraplength=380, justify="left")
        self.size_preview.grid(row=8, column=0, columnspan=3, sticky="w", pady=(12, 0))

        options = ttk.Frame(content)
        options.grid(row=9, column=0, columnspan=3, sticky="w", pady=(14, 0))
        ttk.Checkbutton(options, text="补充没有 Size 的商品", variable=self.size_add_missing_var).pack(side="left")
        ttk.Checkbutton(options, text="写入前备份", variable=self.size_backup_var).pack(side="left", padx=(16, 0))
        adaptive_row = ttk.Frame(content)
        adaptive_row.grid(row=10, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            adaptive_row, text="自适应（按各商品自身 Size 个数套标准序列，\n忽略预设数量/自定义）",
            variable=self.size_adaptive_var,
        ).pack(side="left")
        actions = ttk.Frame(content)
        actions.grid(row=11, column=0, columnspan=3, sticky="w", pady=(20, 12))
        self.size_check_button = ttk.Button(actions, text="读取检查", command=lambda: self._run_size_fix(check_only=True))
        self.size_check_button.pack(side="left")
        self.size_apply_button = ttk.Button(actions, text="执行修改", style="Primary.TButton", command=self._run_size_fix, state="disabled")
        self.size_apply_button.pack(side="left", padx=(8, 0))
        self.run_buttons.extend([self.size_check_button, self.size_apply_button])
        for variable in (self.size_path_var, self.size_count_var, self.size_custom_var, self.size_add_missing_var, self.size_adaptive_var):
            variable.trace_add("write", self._update_size_preview)
        self._update_size_preview()
        self._create_nav_button(idx, name, name)

    def _browse_size_dir(self):
        selected = filedialog.askdirectory(title="选择商品 JSON 目录")
        if selected:
            self.size_path_var.set(strip_quotes(selected))

    def _size_values(self):
        custom = json_sizes.parse_size_list(self.size_custom_var.get())
        if custom:
            return custom
        try:
            count = int(self.size_count_var.get())
        except (tk.TclError, ValueError):
            return []
        return list(json_sizes.SIZE_PRESETS.get(count, []))

    def _size_signature(self):
        adaptive = bool(self.size_adaptive_var.get())
        return (strip_quotes(self.size_path_var.get()),
                tuple(self._size_values()) if not adaptive else (),
                bool(self.size_add_missing_var.get()), adaptive)

    def _update_size_preview(self, *_):
        self._size_checked = None
        self._size_files = []
        adaptive = bool(self.size_adaptive_var.get())
        sizes = self._size_values()
        if adaptive:
            self.size_preview.configure(
                text="自适应模式：按各商品自身 Size 个数套标准序列（2–9 码，超过 9 码保留原值）",
                foreground=PRIMARY,
            )
        elif sizes:
            self.size_preview.configure(
                text=(f"将写入 {len(sizes)} 个尺码：{' / '.join(sizes)}" if sizes
                      else "请填写有效数量（预设支持 2–9 码），或填写自定义列表"),
                foreground=PRIMARY if sizes else ERROR,
            )
        else:
            self.size_preview.configure(
                text="请填写有效数量（预设支持 2–9 码），或填写自定义列表",
                foreground=ERROR,
            )
        self._update_size_apply_state()

    def _update_size_apply_state(self):
        ready = (not self.running and self._size_checked is not None
                 and self._size_checked == self._size_signature() and bool(self._size_files))
        self.size_apply_button.configure(state="normal" if ready else "disabled")

    def _run_size_fix(self, check_only=False):
        if self.running:
            return
        signature = self._size_signature()
        source, sizes, add_missing, adaptive = signature
        if not source or (not sizes and not adaptive):
            messagebox.showwarning("提示", "请选择商品 JSON 文件或目录，并指定有效尺码（或勾选自适应）。")
            return
        if not check_only and self._size_checked != signature:
            messagebox.showwarning("提示", "设置已改变，请先重新「读取检查」。")
            return
        try:
            files = json_sizes.iter_targets(source) if check_only else list(self._size_files)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法读取", str(exc))
            return
        if not files:
            messagebox.showwarning("提示", "没有可处理的 JSON 文件。")
            return
        backup = bool(self.size_backup_var.get())
        self._size_checked = None
        self._size_files = []
        self.set_running(True)
        self._log_separator("JSON 尺码调整 · " + ("读取检查" if check_only else "执行修改"))
        self.log(f"输入：{source}")

        def finish(stats, error):
            if check_only and stats and stats["readable"] and self._size_signature() == signature:
                self._size_checked = signature
                self._size_files = stats["readable"]
                self.log("检查完成，可以点击「执行修改」；读取失败的文件不会写入。")
            self.set_running(False)
            if error is not None:
                messagebox.showerror("运行失败", error)
            elif check_only:
                if not stats["readable"]:
                    messagebox.showwarning("检查失败", "没有读取成功的商品文件，请查看日志。")
            else:
                summary = (f"写入 {stats['written']} 个文件，跳过 {stats['skipped']} 个，"
                           f"失败 {stats['failed']} 个")
                if stats["failed"]:
                    messagebox.showwarning("部分失败", summary + "，详见日志。")
                else:
                    messagebox.showinfo("完成", summary)

        def worker():
            stats = None
            error = None
            try:
                stats = json_sizes.process_json_sizes(files, sizes, add_missing=add_missing, backup=backup,
                                                      check_only=check_only, adaptive=adaptive, log=self.log)
            except Exception as exc:
                error = str(exc)
                self.log(f"失败：{error}")
            finally:
                self.root.after(0, finish, stats, error)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 公共 UI ----------

    def _resize_workspace(self, event):
        self.form_canvas.itemconfigure(self._form_window, width=max(1, event.width))
        self.tool_description_label.configure(wraplength=max(240, event.width))
        def wrap_labels(parent):
            for widget in parent.winfo_children():
                if (widget.winfo_class() in ("TLabel", "Label")
                        and widget.winfo_pixels(widget.cget("wraplength") or 0)):
                    widget.configure(wraplength=max(240, event.width - 10))
                wrap_labels(widget)
        wrap_labels(self.cards_frame)

    def _create_nav_button(self, idx, internal_name, display_text):
        """保留原有索引与名称，以紧凑纵向导航展示八个工具。"""
        btn = GlassNav(
            self.tab_frame, idx + 1, display_text, TOOL_DETAILS[idx][2],
            command=lambda n=internal_name: self.select_tab(n), width=180, height=54,
        )
        btn.pack(fill="x", pady=(0, 4))
        self.tab_buttons[internal_name] = btn

    def _log_separator(self, name):
        self._append_log(f"[{time.strftime('%H:%M:%S')}][{name}]======================")

    def select_tab(self, name):
        """切换选中功能面板，更新按钮高亮状态"""
        for n, btn in self.tab_buttons.items():
            btn.set_selected(n == name)
            if n == name:
                self.frames[n].pack(fill="both", expand=True)
            else:
                self.frames[n].pack_forget()
        index = list(self.tab_buttons).index(name)
        self.tool_number.set(f"TOOL {index + 1:02d} / 08")
        self.tool_title.set(TOOL_DETAILS[index][0])
        self.tool_description.set(TOOL_DETAILS[index][1])
        self.form_canvas.yview_moveto(0)
        self._log_separator(name)

    def browse_file(self, var, filetypes):
        selected = filedialog.askopenfilename(
            title="选择输入文件",
            filetypes=filetypes + [("所有文件", "*.*")],
        )
        if selected:
            var.set(strip_quotes(selected))

    def _browse_dir(self, var):
        """目录选择：既可以选文件夹，也可以选单个文件。"""
        choice = messagebox.askyesnocancel(
            "选择目标",
            "是 → 选择文件夹（递归处理其中的 CSV / XLSX）\n否 → 选择单个文件",
        )
        if choice is None:
            return
        if choice:
            selected = filedialog.askdirectory(title="选择文件夹")
        else:
            selected = filedialog.askopenfilename(
                title="选择文件",
                filetypes=[("所有支持", "*.csv *.xlsx"), ("CSV 文件", "*.csv"),
                           ("Excel 文件", "*.xlsx"), ("所有文件", "*.*")],
            )
        if selected:
            var.set(strip_quotes(selected))

    def log(self, text=""):
        self.root.after(0, self._append_log, str(text))

    def _append_log(self, text):
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")

    def clear_log(self):
        self.log_box.delete("1.0", "end")

    def set_running(self, running):
        self.running = running
        state = "disabled" if running else "normal"
        for button in self.run_buttons:
            button.configure(state=state)
        if hasattr(self, "size_apply_button"):
            self._update_size_apply_state()
        self.status.set("⏳ 运行中..." if running else "✨ 就绪")

    def run_operation(self, name, func, input_file):
        input_file = strip_quotes(input_file)
        if not input_file:
            messagebox.showwarning("缺少文件", "请先选择输入文件或文件夹。")
            return
        if not Path(input_file).exists():
            messagebox.showerror("路径不存在", input_file)
            return

        self.set_running(True)
        self._log_separator(name)
        self.log(f"输入: {input_file}")

        def worker():
            try:
                output = func(input_file, self.log)
                self.log(f"完成: {name}")
                if output:
                    self.log(f"输出: {output}")
            except Exception as exc:
                self.log(f"失败: {exc}")
                self.root.after(0, lambda: messagebox.showerror("运行失败", str(exc)))
            finally:
                self.root.after(0, lambda: self.set_running(False))

        threading.Thread(target=worker, daemon=True).start()


def main():
    from tkinter import Tk
    root = Tk()
    SwitchToolGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
