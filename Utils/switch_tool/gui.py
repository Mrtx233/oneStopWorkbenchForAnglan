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
from .features import price_check, wp_to_styles, sku_check, sku_update
from .features import split_by_title as split_by_title_mod
from .features import split_by_title_each as split_by_title_each_mod
from .features import slim_src_links as slim_src_links_mod
from .features import json_sizes


class SwitchToolGui:
    def __init__(self, root):
        self.root = root
        self.root.title("商品数据转换工具")

        window_width = 1180
        window_height = 780
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.minsize(1050, 680)

        self.run_buttons = []
        self.tab_buttons = {}
        self.frames = {}
        self.running = False
        self._size_checked = None
        self._size_files = []
        self._build_ui()

    def _build_ui(self):
        style = ttk.Style()
        if sys.platform.startswith("win"):
            style.theme_use("vista")

        default_font = ("Microsoft YaHei UI", 10)
        style.configure(".", font=default_font)
        style.configure("TButton", padding=6)
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 11, "bold"), foreground="#0078D4")

        # ── 底部状态栏 ──
        bottom = tk.Frame(self.root, bg="#E8F4F8")
        bottom.pack(side="bottom", fill="x")

        self.status = StringVar(value="✨ 就绪")
        tk.Label(bottom, textvariable=self.status, font=("Microsoft YaHei UI", 10),
                 bg="#E8F4F8", fg="#333333").pack(side="left", padx=20, pady=8)
        ttk.Button(bottom, text="🗑️ 清空日志", command=self.clear_log).pack(side="right", padx=20, pady=6)

        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)

        header_frame = tk.Frame(outer, bg="#0078D4")
        header_frame.pack(fill="x")
        tk.Label(header_frame, text="✨ 商品数据转换工具",
                 font=("Microsoft YaHei UI", 16, "bold"), bg="#0078D4", fg="#FFFFFF").pack(side="left", padx=20, pady=15)

        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=20, pady=20)

        # ── 左：功能面板 ──
        left_panel = ttk.Frame(paned)
        paned.add(left_panel, weight=14)

        self.tab_frame = tk.Frame(left_panel)
        self.tab_frame.pack(fill="x", pady=(0, 20))
        for i in range(4):
            self.tab_frame.columnconfigure(i, weight=1)

        self.cards_frame = ttk.Frame(left_panel)
        self.cards_frame.pack(fill="both", expand=True)

        # ── 右：日志 ──
        right_panel = ttk.Frame(paned)
        paned.add(right_panel, weight=9)

        log_frame = ttk.LabelFrame(right_panel, text="  📝 运行日志  ", padding=15)
        log_frame.pack(fill="both", expand=True, padx=(10, 0))

        self.log_box = ScrolledText(
            log_frame, wrap="word",
            font=("Consolas", 11),
            bg="#FFFFFF", fg="#333333",
            insertbackground="#000000",
            selectbackground="#ADD6FF",
            highlightcolor="#0078D4", highlightthickness=1,
            padx=12, pady=12, relief="flat",
        )
        self.log_box.pack(fill="both", expand=True)

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

        ttk.Label(content, text=prompt, font=("Microsoft YaHei UI", 12, "bold"),
                  foreground="#0056b3").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 15))

        var = StringVar()
        ttk.Entry(content, textvariable=var, font=("Microsoft YaHei UI", 11)).grid(
            row=1, column=0, sticky="ew", ipady=5)

        if allow_dir:
            browse_cmd = lambda: self._browse_dir(var)
        else:
            browse_cmd = lambda: self.browse_file(var, filetypes)
        ttk.Button(content, text="📂 浏览", command=browse_cmd).grid(row=1, column=1, padx=(15, 8))

        run_button = ttk.Button(content, text="▶ 运行",
                                command=lambda: self.run_operation(internal_name, func, var.get()))
        run_button.grid(row=1, column=2)
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
            row=1, column=1, sticky="ew", ipady=5, pady=6)
        ttk.Button(content, text="📂 浏览",
                   command=lambda: self._browse_dir(self.split_path_var)).grid(
            row=1, column=2, padx=(15, 0), pady=6)

        param_row = ttk.Frame(content)
        param_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(param_row, text="分组列:", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Entry(param_row, textvariable=self.split_title_var, width=12).pack(side="left", padx=(4, 15))

        ttk.Label(param_row, text="价格列:", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Entry(param_row, textvariable=self.split_price_var, width=12).pack(side="left", padx=(4, 15))

        ttk.Label(param_row, text="拆分份数:", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Spinbox(param_row, from_=1, to=99, width=5, textvariable=self.split_parts_var).pack(side="left", padx=4)

        ttk.Checkbutton(content, text="覆盖同名文件（不勾选则加「_新」另存）",
                        variable=self.split_overwrite_var).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        run_button = ttk.Button(content, text="🚀 开始拆分", command=self._run_split)
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
            row=1, column=1, sticky="ew", ipady=5, pady=6)
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

        run_button = ttk.Button(content, text="🚀 开始切分", command=self._run_split_each)
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
            foreground="#555555",
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 15))

        ttk.Label(content, text="目标:", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        ttk.Entry(content, textvariable=self.slim_path_var, font=("Microsoft YaHei UI", 11)).grid(
            row=1, column=1, sticky="ew", ipady=5, pady=6)
        ttk.Button(content, text="📂 浏览",
                   command=lambda: self._browse_dir(self.slim_path_var)).grid(
            row=1, column=2, padx=(15, 0), pady=6)

        param_row = ttk.Frame(content)
        param_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        ttk.Label(param_row, text="未引用图片保留张数:", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Spinbox(param_row, from_=0, to=99, width=5, textvariable=self.slim_keep_var).pack(
            side="left", padx=(6, 0))

        ttk.Checkbutton(content, text="覆盖原文件（自动备份为 .bak；不勾选则另存为「_图片精简」）",
                        variable=self.slim_overwrite_var).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        run_button = ttk.Button(content, text="🚀 开始精简", command=self._run_src_slim)
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

        ttk.Label(
            content, text=("统一商品 JSON 的 Size 尺码，已有的替换，缺失的可选补充。\n"
                           "先读取检查，再覆盖原文件；目录只处理当前层的 JSON。"),
            foreground="#555555", justify="left", wraplength=520,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 15))
        ttk.Label(content, text="目标:").grid(row=1, column=0, padx=(0, 10), sticky="e")
        ttk.Entry(content, textvariable=self.size_path_var).grid(row=1, column=1, sticky="ew", ipady=5)
        browse = ttk.Frame(content)
        browse.grid(row=1, column=2, padx=(10, 0))
        ttk.Button(browse, text="选择文件", command=lambda: self.browse_file(
            self.size_path_var, [("JSON 文件", "*.json")],
        )).pack(side="left")
        ttk.Button(browse, text="选择目录", command=self._browse_size_dir).pack(side="left", padx=(4, 0))

        ttk.Label(content, text="预设数量:").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=10)
        presets = ttk.Frame(content)
        presets.grid(row=2, column=1, columnspan=2, sticky="w", pady=10)
        ttk.Spinbox(presets, from_=2, to=9, width=5, textvariable=self.size_count_var).pack(side="left")
        ttk.Label(presets, text="自定义列表留空时使用预设").pack(side="left", padx=(10, 0))
        ttk.Label(content, text="自定义尺码:").grid(row=3, column=0, sticky="e", padx=(0, 10))
        ttk.Entry(content, textvariable=self.size_custom_var).grid(row=3, column=1, columnspan=2, sticky="ew")
        ttk.Label(content, text="支持中英文逗号、分号分隔，例如：S, M, L",
                  foreground="#555555").grid(row=4, column=1, columnspan=2, sticky="w", pady=(4, 0))
        self.size_preview = ttk.Label(content, foreground="#0078D4", wraplength=520, justify="left")
        self.size_preview.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))

        options = ttk.Frame(content)
        options.grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Checkbutton(options, text="补充没有 Size 的商品", variable=self.size_add_missing_var).pack(side="left")
        ttk.Checkbutton(options, text="写入前备份", variable=self.size_backup_var).pack(side="left", padx=(16, 0))
        adaptive_row = ttk.Frame(content)
        adaptive_row.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            adaptive_row, text="自适应（按各商品自身 Size 个数套标准序列，忽略预设数量/自定义）",
            variable=self.size_adaptive_var,
        ).pack(side="left")
        actions = ttk.Frame(content)
        actions.grid(row=8, column=0, columnspan=3, sticky="w", pady=(15, 0))
        self.size_check_button = ttk.Button(actions, text="读取检查", command=lambda: self._run_size_fix(check_only=True))
        self.size_check_button.pack(side="left")
        self.size_apply_button = ttk.Button(actions, text="执行修改", command=self._run_size_fix, state="disabled")
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
                foreground="#0078D4",
            )
        elif sizes:
            self.size_preview.configure(
                text=(f"将写入 {len(sizes)} 个尺码：{' / '.join(sizes)}" if sizes
                      else "请填写有效数量（预设支持 2–9 码），或填写自定义列表"),
                foreground="#0078D4" if sizes else "#B91C1C",
            )
        else:
            self.size_preview.configure(
                text="请填写有效数量（预设支持 2–9 码），或填写自定义列表",
                foreground="#B91C1C",
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

    def _create_nav_button(self, idx, internal_name, display_text):
        """将导航按钮自动分为每行四个的网格"""
        r, c = divmod(idx, 4)
        btn = tk.Button(
            self.tab_frame, text=display_text, font=("Microsoft YaHei UI", 11, "bold"),
            relief="flat", cursor="hand2", bd=0, padx=5, pady=12,
            command=lambda n=internal_name: self.select_tab(n),
        )
        btn.grid(row=r, column=c, sticky="ew", padx=3, pady=3)
        self.tab_buttons[internal_name] = btn

    def _log_separator(self, name):
        self._append_log(f"[{time.strftime('%H:%M:%S')}][{name}]======================")

    def select_tab(self, name):
        """切换选中功能面板，更新按钮高亮状态"""
        for n, btn in self.tab_buttons.items():
            if n == name:
                btn.config(bg="#0078D4", fg="#FFFFFF", activebackground="#005A9E", activeforeground="#FFFFFF")
                self.frames[n].pack(fill="both", expand=True)
            else:
                btn.config(bg="#E1E4E8", fg="#333333", activebackground="#D0D4D9", activeforeground="#333333")
                self.frames[n].pack_forget()
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
