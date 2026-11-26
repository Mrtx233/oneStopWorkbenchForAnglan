# -*- coding: utf-8 -*-

import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse

UTILS_DIR = Path(__file__).resolve().parents[1]
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))
from workbench_ui import (
    BG, FOCUS, HOVER, INPUT, LINE, MUTED, SELECTION, SELECTION_FG, SIDE, SOFT, SURFACE,
    TEXT, WorkbenchNav, apply_workbench_controls,
)
from jsonl_store import load_records as load_jsonl_records, save_records as save_jsonl_records


JSONL_PATH = Path(__file__).parent / "links.jsonl"


# ============================================================
# 使用工作台色板，审核状态另有语义色。
# ============================================================

C = {
    "bg": BG,
    "sidebar": SIDE,
    "sidebar_hover": HOVER,
    "card": SURFACE,
    "input": INPUT,
    "soft": SOFT,
    "line": LINE,
    "text": TEXT,
    "sub": "#cdcfd1",
    "muted": MUTED,
    "primary_soft": SELECTION,
    "selected_text": SELECTION_FG,
    "focus": FOCUS,
    "signal_neutral": "#cdcfd1",
    "signal_progress": "#a0bdcb",
    "signal_good": "#9fc4ac",
    "signal_warn": "#d2b987",
    "signal_alert": "#dca39b",
    "signal_soft": SOFT,
}


# 只用系统字体族；层级靠字号与字重，桌面最小 10pt。
FONT = {"darwin": "PingFang SC", "win32": "Microsoft YaHei UI"}.get(sys.platform, "Noto Sans CJK SC")

FONT_BODY = (FONT, 11)
FONT_SMALL = (FONT, 10)
FONT_CAPTION = (FONT, 10)
FONT_TITLE = (FONT, 24)
FONT_SECTION = (FONT, 12, "bold")
FONT_LABEL = (FONT, 10, "bold")
FONT_HEADING = (FONT, 10, "bold")
FONT_MONO = ({"darwin": "Menlo", "win32": "Consolas"}.get(sys.platform, "DejaVu Sans Mono"), 11)


STATUS_NEW = "未使用"

STATUS_PRESETS = [
    "已送审",
    "审核未通过",
    "通过",
    "404",
    "量少",
    "logo",
    "社媒超限",
    "无可用商品",
    "类型不符",
]


# 记录详情用色区分审核状态，具体含义由文字承载。
STATUS_ROLE = {
    "未使用": "neutral",
    "历史，不在启用": "neutral",
    "无可用商品": "neutral",
    "已审核不可用": "neutral",
    "已送审": "progress",
    "待定": "progress",
    "通过": "good",
    "可使用": "good",
    "量少": "warn",
    "logo": "warn",
    "社媒超限": "warn",
    "类型不符": "warn",
    "404": "alert",
    "审核未通过": "alert",
}

ROLE_STYLE = {
    "neutral": "signal_neutral",
    "progress": "signal_progress",
    "good": "signal_good",
    "warn": "signal_warn",
    "alert": "signal_alert",
}


def status_role(status):
    return STATUS_ROLE.get(status, "neutral")


def status_fg(status):
    return C[ROLE_STYLE[status_role(status)]]


def status_bg(status):
    return C["signal_soft"]


# 保留给外部读取，与固定主题保持一致。
STATUS_THEME = {
    name: (status_fg(name), status_bg(name))
    for name in set(STATUS_ROLE) | set(STATUS_PRESETS)
}


# ============================================================
# Data
# ============================================================

def load_records():
    return load_jsonl_records(JSONL_PATH)


def build_tree(records):
    tree = {}

    for record in records:
        batch = record.get("batch", "(无批次)")
        type_name = record.get("type", "(无分类)")

        tree.setdefault(batch, {})
        tree[batch].setdefault(type_name, [])
        tree[batch][type_name].append(record)

    return tree


def normalize_link(link):
    parsed = urlparse(
        link if "//" in link else f"https://{link}"
    )

    host = (
        parsed.netloc
        or parsed.path.split("/")[0]
    ).lower()

    if host.startswith("www."):
        host = host[4:]

    return host, parsed.path.rstrip("/")


def parse_input_line(line):
    parts = line.split()

    # 兼容旧格式：id link type
    if parts and parts[0].isdigit():
        parts = parts[1:]

    if len(parts) < 2:
        return None

    link = parts[0]

    if (
        not link.startswith(("http://", "https://"))
        and "." not in link
    ):
        return None

    return link, " ".join(parts[1:])


# ============================================================
# App
# ============================================================

class LinkBrowserApp:

    def __init__(self, root):

        self.root = root

        self.root.title("链接库")

        self.root.geometry("1240x820")
        self.root.minsize(1040, 680)

        self.root.configure(bg=C["bg"])

        self.records = load_records()
        self.tree = build_tree(self.records)

        self.path_stack = []
        self._current_items = []

        self.status_filter = "全部"
        self._detail_record = None

        self.current_page = "library"

        self._setup_styles()
        self._build_app()

        self.show_batches()
        self.switch_page("library")
        if self.records.invalid_lines:
            self.set_status(
                f"发现 {len(self.records.invalid_lines)} 行损坏或格式异常：原文保留，保存时自动备份")

    # ========================================================
    # ttk
    # ========================================================

    def _setup_styles(self):
        style = apply_workbench_controls(self.root)
        style.configure(
            "Modern.Treeview", background=C["input"], foreground=C["text"],
            fieldbackground=C["input"], bordercolor=C["input"], lightcolor=C["input"],
            darkcolor=C["input"], borderwidth=0, relief="flat", rowheight=32, font=FONT_BODY,
        )
        style.configure(
            "Modern.Treeview.Heading", background=C["soft"], foreground=C["sub"],
            bordercolor=C["soft"], lightcolor=C["soft"], darkcolor=C["soft"],
            borderwidth=0, relief="flat", font=FONT_HEADING, padding=(12, 8),
        )
        style.map("Modern.Treeview.Heading", background=[("active", C["sidebar_hover"])])
        style.map("Modern.Treeview", background=[("selected", C["primary_soft"])],
                  foreground=[("selected", C["selected_text"])])
        style.configure("Hint.TEntry", foreground=C["muted"])
        self.root.option_add("*TCombobox*Listbox.font", FONT_BODY)

    # ========================================================
    # Field hints
    # ========================================================

    def _setup_hint(self, entry, hint):
        entry._hint_text = hint
        entry._hint_on = False
        self._show_hint(entry)

        entry.bind(
            "<FocusIn>",
            self._on_hint_focus_in,
            add="+",
        )
        entry.bind(
            "<FocusOut>",
            self._on_hint_focus_out,
            add="+",
        )

    def _show_hint(self, entry):
        if entry._hint_on:
            return
        entry.delete(0, tk.END)
        entry.insert(0, entry._hint_text)
        entry.configure(style="Hint.TEntry")
        entry._hint_on = True

    def _clear_hint(self, entry):
        if not entry._hint_on:
            return
        entry.delete(0, tk.END)
        entry.configure(style="Modern.TEntry")
        entry._hint_on = False

    def _on_hint_focus_in(self, event):
        self._clear_hint(event.widget)

    def _on_hint_focus_out(self, event):
        widget = event.widget
        if not widget.get().strip():
            self._show_hint(widget)

    def _entry_value(self, entry):
        """读取输入值；提示文字不算用户输入。"""
        if getattr(entry, "_hint_on", False):
            return ""
        return entry.get().strip()

    def _set_entry_value(self, entry, value):
        """回填记录内容；空值且未聚焦时恢复提示。"""
        self._clear_hint(entry)
        entry.delete(0, tk.END)

        if value:
            entry.insert(0, value)
        elif self.root.focus_get() is not entry:
            self._show_hint(entry)

    # ========================================================
    # Common
    # ========================================================

    def button(self, parent, text, command, kind="secondary", padx=16, pady=8, font=None):
        style = "Primary.TButton" if kind == "primary" else "TButton"
        if font:
            prefix = "Compact" if font == FONT_SMALL else "Emphasis"
            style = f"{prefix}.{style}"
            ttk.Style(self.root).configure(style, font=font)
        return ttk.Button(parent, text=text, command=command, style=style,
                          padding=(padx, pady), width=0, cursor="hand2", takefocus=True)

    # ========================================================
    # Shell
    # ========================================================

    def _build_app(self):
        shell = tk.Frame(self.root, bg=C["bg"])
        shell.pack(fill=tk.BOTH, expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(2, weight=1)
        self.sidebar = tk.Frame(shell, bg=C["sidebar"], width=168)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.pack_propagate(False)
        tk.Frame(shell, bg=C["line"], width=1).grid(row=0, column=1, sticky="ns")
        self._build_sidebar()

        self.main = tk.Frame(shell, bg=C["card"])
        self.main.grid(row=0, column=2, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(2, weight=1)
        self._build_header()
        tk.Frame(self.main, bg=C["line"], height=1).grid(row=1, column=0, sticky="ew")
        self.page_host = tk.Frame(self.main, bg=C["card"])
        self.page_host.grid(row=2, column=0, sticky="nsew")
        self.library_page = tk.Frame(self.page_host, bg=C["card"])
        self.add_page = tk.Frame(self.page_host, bg=C["card"])
        self._build_library_page()
        self._build_add_page()
        tk.Frame(self.main, bg=C["line"], height=1).grid(row=3, column=0, sticky="ew")
        self._build_statusbar()

    # ========================================================
    # Sidebar
    # ========================================================

    def _build_sidebar(self):
        tk.Label(self.sidebar, text="链接库", bg=C["sidebar"], fg=C["text"],
                 font=(FONT, 18)).pack(anchor="w", padx=20, pady=(24, 24))
        self.nav_buttons = {
            "library": self._create_nav("library", 1, "浏览链接"),
            "add": self._create_nav("add", 2, "新增链接"),
        }
        self.sidebar_count = tk.Label(self.sidebar, bg=C["sidebar"], fg=C["muted"], font=FONT_CAPTION)
        self.sidebar_count.pack(side=tk.BOTTOM, anchor="w", padx=20, pady=16)
        self._update_sidebar_count()

    def _create_nav(self, key, index, title):
        nav = WorkbenchNav(self.sidebar, index=index, title=title,
                           command=lambda: self.switch_page(key), width=144)
        nav.pack(fill=tk.X, padx=12, pady=(0, 4))
        return nav

    def _set_active_nav(self, key):
        for nav_key, nav in self.nav_buttons.items():
            nav.set_selected(nav_key == key)

    # ========================================================
    # Header
    # ========================================================

    def _build_header(self):
        header = tk.Frame(self.main, bg=C["card"])
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=16)
        header.columnconfigure(0, weight=1)
        self.page_title = tk.Label(header, bg=C["card"], fg=C["text"], font=FONT_TITLE, anchor="w")
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_subtitle = tk.Label(header, bg=C["card"], fg=C["muted"], font=FONT_SMALL, anchor="w")
        self.page_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.header_action = self.button(header, "新增链接", lambda: self.switch_page("add"), kind="primary")
        self.header_action.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))

    # ========================================================
    # Statusbar
    # ========================================================

    def _build_statusbar(self):
        bar = tk.Frame(self.main, bg=C["card"])
        bar.grid(row=4, column=0, sticky="ew", padx=24, pady=12)
        self.statusbar = tk.Label(bar, text="就绪", bg=C["card"], fg=C["muted"], font=FONT_CAPTION)
        self.statusbar.pack(side=tk.LEFT)

    # ========================================================
    # Switch page
    # ========================================================

    def switch_page(self, page):
        self.current_page = page
        self._set_active_nav(page)
        if page == "library":
            self.add_page.pack_forget()
            self.page_title.config(text="浏览链接")
            self.page_subtitle.config(text="按批次和分类查看链接，记录审核状态与备注")
            self.header_action.config(text="新增链接", style="Primary.TButton", command=lambda: self.switch_page("add"))
            self.library_page.pack(fill=tk.BOTH, expand=True)
        else:
            self.library_page.pack_forget()
            self.page_title.config(text="新增链接")
            self.page_subtitle.config(text="每行填写链接和分类，保存时自动编号")
            self.header_action.config(text="返回链接库", style="TButton", command=lambda: self.switch_page("library"))
            self.add_page.pack(fill=tk.BOTH, expand=True)

    # ========================================================
    # Library page
    # ========================================================

    def _build_library_page(self):
        self.library_page.columnconfigure(0, weight=1)
        self.library_page.rowconfigure(0, weight=1)
        table_panel = tk.Frame(self.library_page, bg=C["card"])
        table_panel.grid(row=0, column=0, sticky="nsew", padx=(24, 16), pady=16)
        tk.Frame(self.library_page, bg=C["line"], width=1).grid(row=0, column=1, sticky="ns")
        detail_panel = tk.Frame(self.library_page, bg=C["card"], width=216)
        detail_panel.grid(row=0, column=2, sticky="ns", padx=16, pady=16)
        detail_panel.pack_propagate(False)
        self._build_table(table_panel)
        self._build_detail(detail_panel)

    # ========================================================
    # Table
    # ========================================================

    def _build_table(self, parent):

        # Topbar
        top = tk.Frame(
            parent,
            bg=C["card"],
        )

        top.pack(
            fill=tk.X,
            pady=(0, 12),
        )

        self.back_btn = self.button(
            top,
            "返回上一级",
            self.go_back,
            padx=12,
            pady=4,
        )

        self.back_btn.pack(
            side=tk.LEFT
        )

        self.path_label = tk.Label(
            top,
            text="全部批次",

            bg=C["card"],
            fg=C["text"],

            font=FONT_SECTION,
        )

        self.path_label.pack(
            side=tk.LEFT,
            padx=(12, 0),
        )

        self.path_meta = tk.Label(
            top,
            text="",

            bg=C["card"],
            fg=C["muted"],

            font=FONT_CAPTION,
        )

        self.path_meta.pack(
            side=tk.LEFT,
            padx=(8, 0),
        )

        # Search
        tools = tk.Frame(
            parent,
            bg=C["card"],
        )

        tools.pack(
            fill=tk.X,
            pady=(0, 12),
        )

        search_box = tk.Frame(
            tools,
            bg=C["input"],
            highlightthickness=1,
            highlightbackground=C["line"],
        )

        search_box.pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )

        tk.Label(
            search_box,
            text="搜索",

            bg=C["input"],
            fg=C["muted"],

            font=FONT_CAPTION,
        ).pack(
            side=tk.LEFT,
            padx=(12, 8),
        )

        self.search_var = tk.StringVar()

        self.search_entry = tk.Entry(
            search_box,

            textvariable=self.search_var,

            bg=C["input"],
            fg=C["text"],

            insertbackground=C["text"],
            selectbackground=C["primary_soft"],
            selectforeground=C["selected_text"],

            relief=tk.FLAT,
            bd=0,

            font=FONT_BODY,
        )

        self.search_entry.pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
            ipady=8,
        )
        self.search_entry.bind("<FocusIn>", lambda e: search_box.config(highlightbackground=C["focus"]))
        self.search_entry.bind("<FocusOut>", lambda e: search_box.config(highlightbackground=C["line"]))

        self.search_entry.bind(
            "<KeyRelease>",
            lambda e: self.on_search_changed(),
        )

        self.filter_combo = ttk.Combobox(
            tools,

            style="Modern.TCombobox",

            state="readonly",

            width=11,

            values=["全部"],

            font=FONT_SMALL,
        )

        self.filter_combo.set("全部")

        self.filter_combo.pack(
            side=tk.LEFT,
            padx=(8, 0),
        )

        self.filter_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self.on_filter_changed(),
        )

        # Treeview
        tree_frame = tk.Frame(
            parent,
            bg=C["input"],
            highlightthickness=1,
            highlightbackground=C["line"],
        )

        tree_frame.pack(
            fill=tk.BOTH,
            expand=True,
            pady=(0, 12),
        )

        columns = (
            "id",
            "link",
            "status",
            "note",
            "action",
        )

        self.listbox = ttk.Treeview(
            tree_frame,

            columns=columns,

            show="headings",

            selectmode="extended",

            style="Modern.Treeview",
        )
        self.listbox.tag_configure("row_even", background=C["input"])
        self.listbox.tag_configure("row_odd", background=C["card"])

        self.listbox.column(
            "id",
            anchor="center",
        )

        self.listbox.column(
            "link",
            anchor="w",
        )

        self.listbox.column(
            "status",
            anchor="center",
        )

        self.listbox.column(
            "note",
            anchor="w",
        )

        self.listbox.column(
            "action",
            anchor="center",
        )

        scrollbar = ttk.Scrollbar(
            tree_frame,
            orient="vertical",
            command=self.listbox.yview,
        )

        self.listbox.configure(
            yscrollcommand=scrollbar.set
        )

        self.listbox.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
        )

        scrollbar.pack(
            side=tk.RIGHT,
            fill=tk.Y,
        )

        self.listbox.bind(
            "<Button-1>",
            self.on_click,
        )

        self.listbox.bind(
            "<Double-Button-1>",
            self.on_double_click,
        )

        self.listbox.bind(
            "<Return>",
            self.on_double_click,
        )

        self.listbox.bind(
            "<<TreeviewSelect>>",
            self.on_select,
        )

        self.listbox.bind(
            "<Configure>",
            self._resize_columns,
        )
        self.listbox.bind("<FocusIn>", lambda e: tree_frame.config(highlightbackground=C["focus"]))
        self.listbox.bind("<FocusOut>", lambda e: tree_frame.config(highlightbackground=C["line"]))

        # Batch action
        actions = tk.Frame(
            parent,
            bg=C["card"],
        )

        actions.pack(
            side=tk.BOTTOM,
            fill=tk.X,
            before=tree_frame,
        )
        tk.Frame(actions, bg=C["line"], height=1).pack(fill=tk.X, pady=(0, 8))

        top_action = tk.Frame(
            actions,
            bg=C["card"],
        )

        top_action.pack(
            fill=tk.X,
            pady=(0, 4),
        )

        tk.Label(
            top_action,
            text="批量操作",

            bg=C["card"],
            fg=C["sub"],

            font=FONT_LABEL,
        ).pack(
            side=tk.LEFT
        )

        self.selection_count = tk.Label(
            top_action,
            text="未选择",

            bg=C["card"],
            fg=C["muted"],

            font=FONT_CAPTION,
        )

        self.selection_count.pack(
            side=tk.LEFT,
            padx=(8, 0),
        )

        # Status buttons（自动换行：窗口变窄时按钮流式折行，不再被遮挡）
        self.status_row = tk.Frame(
            actions,
            bg=C["card"],
        )

        status_row = self.status_row

        status_row.pack(
            fill=tk.X,
            pady=(0, 4),
        )

        self._status_buttons = []

        for status in STATUS_PRESETS:
            btn = self.button(status_row, status, lambda s=status: self.set_selected_status(s),
                              padx=8, pady=4, font=FONT_SMALL)
            self._status_buttons.append(btn)

        status_row.bind(
            "<Configure>",
            self._flow_status_buttons,
        )

        self._build_note_row(actions)

    def _flow_status_buttons(self, event=None):
        """按 status_row 的实际宽度把状态按钮流式折行。

        不用 grid：grid 的列宽由同列所有行里最宽的控件决定，
        下一行的宽按钮会把上一行的列撑开，窄窗口时右侧会溢出。
        place 用绝对坐标，各行独立测量，互不影响。
        """

        row_width = (
            self.status_row.winfo_width()
            if hasattr(self, "status_row")
            else 0
        )

        if row_width < 40:
            return

        gap = 4
        widgets = self._status_buttons

        widths = [
            widget.winfo_reqwidth()
            for widget in widgets
        ]

        row_height = max(
            (
                widget.winfo_reqheight()
                for widget in widgets
            ),
            default=0,
        ) + gap

        x = 0
        row = 0

        for widget, w in zip(widgets, widths):

            if x and x + gap + w > row_width:
                x = 0
                row += 1

            widget.place(
                x=x,
                y=row * row_height,
            )

            x += w + gap

        # place 不撑开父容器，需显式给定高度
        self.status_row.configure(
            height=(row + 1) * row_height
        )

    # ========================================================
    # Note row（归属 _build_actions）
    # ========================================================

    def _build_note_row(self, actions):
        note_row = tk.Frame(actions, bg=C["card"])
        note_row.pack(fill=tk.X, pady=(4, 0))
        note_row.columnconfigure(0, weight=1, uniform="fields")
        note_row.columnconfigure(2, weight=1, uniform="fields")
        self.custom_status_entry = ttk.Entry(note_row, style="Modern.TEntry", width=10, font=FONT_SMALL)
        self.custom_status_entry.grid(row=0, column=0, sticky="ew")
        self.custom_status_entry.bind("<Return>", lambda e: self.set_custom_status())
        self.button(note_row, "应用状态", self.set_custom_status,
                    padx=8, pady=4, font=FONT_SMALL).grid(row=0, column=1, padx=(8, 12))
        self.approver_entry = ttk.Entry(note_row, style="Modern.TEntry", width=10, font=FONT_SMALL)
        self.approver_entry.grid(row=0, column=2, sticky="ew")
        self.approver_entry.bind("<Return>", lambda e: self.apply_approver())
        self.button(note_row, "保存审批人", self.apply_approver, padx=8, pady=4,
                    font=FONT_SMALL).grid(row=0, column=3, padx=(8, 0))
        self.note_entry = ttk.Entry(note_row, style="Modern.TEntry", font=FONT_SMALL)
        self.note_entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.note_entry.bind("<Return>", lambda e: self.apply_note())
        self.button(note_row, "保存备注", self.apply_note, padx=8, pady=4,
                    font=FONT_SMALL).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        for entry, hint in ((self.custom_status_entry, "自定义状态"),
                            (self.note_entry, "为选中链接添加备注"), (self.approver_entry, "审批人")):
            self._setup_hint(entry, hint)

    # ========================================================
    # Detail
    # ========================================================

    def _build_detail(self, parent):

        tk.Label(
            parent,
            text="记录详情",

            bg=C["card"],
            fg=C["text"],

            font=FONT_SECTION,
        ).pack(
            anchor="w",
            pady=(0, 12),
        )

        tk.Frame(
            parent,
            bg=C["line"],
            height=1,
        ).pack(
            fill=tk.X
        )

        self.detail_host = tk.Frame(
            parent,
            bg=C["card"],
        )

        self.detail_host.pack(
            fill=tk.BOTH,
            expand=True,
            pady=(12, 0),
        )

        self.detail_canvas = tk.Canvas(
            self.detail_host,
            bg=C["card"],
            highlightthickness=0,
            bd=0,
        )

        detail_scrollbar = ttk.Scrollbar(
            self.detail_host,
            orient="vertical",
            command=self.detail_canvas.yview,
        )

        self.detail_canvas.configure(
            yscrollcommand=detail_scrollbar.set,
        )

        self.detail_canvas.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
        )

        detail_scrollbar.pack(
            side=tk.RIGHT,
            fill=tk.Y,
        )

        self.detail_inner = tk.Frame(
            self.detail_canvas,
            bg=C["card"],
        )

        self._detail_window = self.detail_canvas.create_window(
            (0, 0),
            window=self.detail_inner,
            anchor="nw",
        )

        self.detail_inner.bind(
            "<Configure>",
            lambda e: self.detail_canvas.configure(
                scrollregion=self.detail_canvas.bbox("all"),
            ),
        )

        self.detail_canvas.bind(
            "<Configure>",
            lambda e: self.detail_canvas.itemconfigure(
                self._detail_window,
                width=e.width,
            ),
        )

        # 鼠标滚轮
        def _on_detail_mousewheel(event):
            if event.delta:
                self.detail_canvas.yview_scroll(
                    int(-event.delta / 120), "units",
                )

        self.detail_canvas.bind(
            "<Enter>",
            lambda e: self.detail_canvas.bind_all(
                "<MouseWheel>", _on_detail_mousewheel,
            ),
        )

        self.detail_canvas.bind(
            "<Leave>",
            lambda e: self.detail_canvas.unbind_all(
                "<MouseWheel>",
            ),
        )

        self.detail_empty = tk.Frame(
            self.detail_inner,
            bg=C["card"],
        )

        self.detail_empty.pack(
            fill=tk.BOTH,
            expand=True,
        )

        tk.Label(
            self.detail_empty,
            text="选择一条链接查看详情",
            wraplength=140,
            justify="center",

            bg=C["card"],
            fg=C["muted"],

            font=FONT_SMALL,
        ).pack(
            anchor="w",
            pady=(12, 0),
        )

        self.detail_content = tk.Frame(
            self.detail_inner,
            bg=C["card"],
        )

        self.detail_labels = {}

        fields = [
            ("id", "ID"),
            ("batch", "批次"),
            ("type", "分类"),
            ("link", "链接"),
            ("status", "状态"),
            ("note", "备注"),
            ("approver", "审批人"),
            ("created_at", "录入时间"),
            ("updated_at", "修改时间"),
        ]

        for key, title in fields:

            box = tk.Frame(
                self.detail_content,
                bg=C["card"],
            )

            box.pack(
                fill=tk.X,
                pady=(0, 12),
            )

            tk.Label(
                box,
                text=title,

                bg=C["card"],
                fg=C["muted"],

                font=FONT_CAPTION,
            ).pack(
                anchor="w"
            )

            label = tk.Label(
                box,
                text="-",

                bg=C["card"],
                fg=C["sub"],

                font=FONT_SMALL,

                anchor="w",
                justify="left",

                wraplength=188,
            )

            label.pack(
                fill=tk.X,
                pady=(4, 0),
            )

            self.detail_labels[key] = label

        self.button(
            self.detail_content,
            "复制链接",
            self.copy_current_detail_link,
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

    # ========================================================
    # Add page
    # ========================================================

    def _build_add_page(self):
        form = tk.Frame(self.add_page, bg=C["card"])
        form.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)

        # Batch
        batch_row = tk.Frame(
            form,
            bg=C["card"],
        )

        batch_row.pack(
            fill=tk.X,
            pady=(0, 16),
        )

        tk.Label(
            batch_row,
            text="批次",

            anchor="w",

            bg=C["card"],
            fg=C["sub"],

            font=FONT_LABEL,
        ).pack(
            side=tk.LEFT,
            padx=(0, 12),
        )

        self.batch_entry = ttk.Entry(
            batch_row,

            style="Modern.TEntry",

            width=18,

            font=FONT_BODY,
        )

        self.batch_entry.pack(
            side=tk.LEFT
        )

        if self.tree:
            self.batch_entry.insert(
                0,
                sorted(self.tree)[-1],
            )

        # Text
        input_header = tk.Frame(
            form,
            bg=C["card"],
        )

        input_header.pack(
            fill=tk.X,
            pady=(0, 8),
        )

        tk.Label(
            input_header,
            text="链接",

            bg=C["card"],
            fg=C["sub"],

            font=FONT_LABEL,
        ).pack(
            side=tk.LEFT
        )

        self.entry_counter = tk.Label(
            input_header,
            text="0 条",

            bg=C["card"],
            fg=C["muted"],

            font=FONT_CAPTION,
        )

        self.entry_counter.pack(
            side=tk.RIGHT
        )

        editor = tk.Frame(
            form,

            bg=C["input"],

            highlightthickness=1,
            highlightbackground=C["line"],
        )

        editor.pack(
            fill=tk.BOTH,
            expand=True,
        )

        self.entry_text = tk.Text(
            editor,

            font=FONT_MONO,
            height=8,

            bg=C["input"],
            fg=C["text"],

            insertbackground=C["text"],
            selectbackground=C["primary_soft"],
            selectforeground=C["selected_text"],

            relief=tk.FLAT,
            bd=0,

            padx=12,
            pady=12,

            undo=True,
        )

        self.entry_text.pack(
            fill=tk.BOTH,
            expand=True,
        )
        self.entry_text.bind("<FocusIn>", lambda e: editor.config(highlightbackground=C["focus"]))
        self.entry_text.bind("<FocusOut>", lambda e: editor.config(highlightbackground=C["line"]))

        self.entry_text.bind(
            "<KeyRelease>",
            lambda e: self._update_entry_count(),
        )

        # Bottom actions
        bottom = tk.Frame(
            form,
            bg=C["card"],
        )

        bottom.pack(
            side=tk.BOTTOM,
            fill=tk.X,
            pady=(16, 0),
            before=editor,
        )

        tk.Label(
            bottom,
            text="格式：链接 空格 分类",

            bg=C["card"],
            fg=C["muted"],

            font=FONT_CAPTION,
        ).pack(
            side=tk.LEFT
        )

        self.button(
            bottom,
            "清空",
            self.clear_entry,
            padx=16,
        ).pack(
            side=tk.RIGHT
        )

        self.button(
            bottom,
            "保存链接",
            self.submit_entries,
            kind="primary",
            padx=20,
        ).pack(
            side=tk.RIGHT,
            padx=(0, 8),
        )

    # ========================================================
    # Add link
    # ========================================================

    def clear_entry(self):

        self.entry_text.delete(
            "1.0",
            tk.END,
        )

        self._update_entry_count()

    def _update_entry_count(self):

        lines = [
            line
            for line in self.entry_text.get(
                "1.0",
                tk.END,
            ).splitlines()
            if line.strip()
        ]

        self.entry_counter.config(
            text=f"{len(lines)} 条"
        )

    def submit_entries(self):

        batch = self.batch_entry.get().strip()

        if not batch:
            self.set_status("请输入批次")
            return

        lines = [
            line.strip()
            for line in self.entry_text.get(
                "1.0",
                tk.END,
            ).splitlines()
            if line.strip()
        ]

        if not lines:
            self.set_status("请输入链接")
            return

        existing = {
            normalize_link(
                record.get("link", "")
            )
            for record in self.records
        }

        next_num = 1

        for record in self.records:

            try:
                next_num = max(
                    next_num,
                    int(record.get("id", 0)) + 1,
                )
            except (TypeError, ValueError):
                continue

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        added = []
        skipped = []
        invalid = []

        for line in lines:

            parsed = parse_input_line(line)

            if not parsed:
                invalid.append(line)
                continue

            link, link_type = parsed

            key = normalize_link(link)

            if key in existing:
                skipped.append(link)
                continue

            existing.add(key)

            added.append({
                "id": str(next_num).zfill(5),
                "batch": batch,
                "type": link_type,
                "link": link,
                "status": STATUS_NEW,
                "created_at": now,
                "updated_at": now,
                "note": "",
                "approver": "",
            })

            next_num += 1

        if added:

            self.records.extend(added)

            if not self.save_all():
                return

            self.tree = build_tree(
                self.records
            )

            self._update_sidebar_count()

            self.clear_entry()

            self.show_batches()

        parts = []

        if added:
            parts.append(
                f"新增 {len(added)}"
            )

        if skipped:
            parts.append(
                f"重复 {len(skipped)}"
            )

        if invalid:
            parts.append(
                f"无效 {len(invalid)}"
            )

        self.set_status(
            " · ".join(parts)
        )

    # ========================================================
    # Batch actions
    # ========================================================

    def _selected_records(self):

        if len(self.path_stack) < 2:
            return []

        records = []

        for item in self.listbox.selection():

            index = self.listbox.index(
                item
            )

            if (
                0
                <= index
                < len(self._current_items)
            ):
                records.append(
                    self._current_items[index]
                )

        return records

    def set_selected_status(self, status):

        records = self._selected_records()

        if not records:
            self.set_status("请选择链接")
            return

        ids = {
            record.get("id")
            for record in records
        }

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        changed = 0

        for record in self.records:

            if record.get("id") in ids:

                if record.get("status") != status:
                    record["status"] = status
                    changed += 1

                record["updated_at"] = now

        if not self.save_all():
            return

        self.tree = build_tree(
            self.records
        )

        self._refresh_links()

        self.set_status(
            f"已修改 {changed} 条"
        )

    def set_custom_status(self):

        status = self._entry_value(
            self.custom_status_entry
        )

        if not status:
            return

        self.set_selected_status(status)

    def apply_note(self):

        self._apply_field(
            "note",
            self._entry_value(self.note_entry),
            "备注",
        )

    def apply_approver(self):

        self._apply_field(
            "approver",
            self._entry_value(self.approver_entry),
            "审批人",
        )

    def _apply_field(
        self,
        field,
        value,
        title,
    ):

        records = self._selected_records()

        if not records:
            self.set_status("请选择链接")
            return

        ids = {
            record.get("id")
            for record in records
        }

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        for record in self.records:

            if record.get("id") in ids:

                record[field] = value
                record["updated_at"] = now

        if not self.save_all():
            return

        self.tree = build_tree(
            self.records
        )

        self._refresh_links()

        self.set_status(
            f"{title}已保存"
        )

    # ========================================================
    # Navigation
    # ========================================================

    def show_batches(self):

        self.listbox.delete(
            *self.listbox.get_children()
        )

        self.path_stack = []
        self._current_items = []

        self.path_label.config(
            text="全部批次"
        )

        self.path_meta.config(
            text=f"{len(self.tree)} 个"
        )

        self.back_btn.config(
            state=tk.DISABLED
        )

        self.search_var.set("")

        self.status_filter = "全部"

        self.filter_combo.configure(
            values=["全部"]
        )

        self.filter_combo.set("全部")

        self._set_headings(
            "批次",
            "分类",
            "链接",
        )

        self._clear_detail()

        for row_index, batch in enumerate(sorted(
            self.tree,
            reverse=True,
        )):

            total = sum(
                len(items)
                for items in self.tree[
                    batch
                ].values()
            )

            self.listbox.insert(
                "",
                tk.END,

                values=(
                    batch,
                    len(self.tree[batch]),
                    total,
                    "",
                    "",
                ),
                tags=("row_odd" if row_index % 2 else "row_even",),
            )

        self.set_status(
            f"{len(self.records)} 条链接"
        )

    def show_types(self, batch):

        self.listbox.delete(
            *self.listbox.get_children()
        )

        self.path_stack = [
            ("batch", batch)
        ]

        self._current_items = []

        self.path_label.config(
            text=batch
        )

        self.path_meta.config(
            text=""
        )

        self.back_btn.config(
            state=tk.NORMAL
        )

        self.search_var.set("")

        self.filter_combo.configure(
            values=["全部"]
        )

        self.filter_combo.set("全部")

        self._set_headings(
            "分类",
            "链接",
            "未使用",
        )

        self._clear_detail()

        types = self.tree.get(
            batch,
            {},
        )

        ordered = sorted(
            types,
            key=lambda key: (
                -len(types[key]),
                key,
            ),
        )

        for row_index, type_name in enumerate(ordered):

            items = types[
                type_name
            ]

            unused = sum(
                record.get("status") == STATUS_NEW
                for record in items
            )

            self.listbox.insert(
                "",
                tk.END,

                values=(
                    type_name,
                    len(items),
                    unused,
                    "",
                    "",
                ),
                tags=("row_odd" if row_index % 2 else "row_even",),
            )

    def show_links(
        self,
        batch,
        type_name,
    ):

        self.listbox.delete(
            *self.listbox.get_children()
        )

        self.path_stack = [
            ("batch", batch),
            ("type", type_name),
        ]

        self.path_label.config(
            text=type_name
        )

        self.back_btn.config(
            state=tk.NORMAL
        )

        self._set_headings(
            "ID",
            "链接",
            "状态",
            "备注",
            "操作",
        )

        all_items = (
            self.tree
            .get(batch, {})
            .get(type_name, [])
        )

        statuses = sorted({
            record.get("status", "")
            for record in all_items
            if record.get("status")
        })

        options = [
            "全部"
        ] + statuses

        self.filter_combo.configure(
            values=options
        )

        if self.status_filter not in options:

            self.status_filter = "全部"
            self.filter_combo.set("全部")

        query = (
            self.search_var
            .get()
            .strip()
            .lower()
        )

        items = []

        for record in all_items:

            if (
                self.status_filter != "全部"
                and record.get("status")
                != self.status_filter
            ):
                continue

            text = " ".join(
                str(record.get(key, ""))
                for key in (
                    "id",
                    "link",
                    "status",
                    "note",
                    "approver",
                )
            ).lower()

            if (
                query
                and query not in text
            ):
                continue

            items.append(record)

        self._current_items = items

        for row_index, record in enumerate(items):

            status = record.get(
                "status",
                "",
            )

            self.listbox.insert(
                "",
                tk.END,

                values=(
                    record.get("id", ""),
                    record.get("link", ""),
                    status,
                    record.get("note", ""),
                    "复制",
                ),
                tags=("row_odd" if row_index % 2 else "row_even",),

            )

        self.path_meta.config(
            text=f"{len(items)}/{len(all_items)}"
        )

        self.selection_count.config(
            text="未选择"
        )

        self._clear_detail()

        self.root.after_idle(
            self._resize_columns
        )

    def _refresh_links(self):

        if len(self.path_stack) == 2:

            batch = self.path_stack[0][1]
            type_name = self.path_stack[1][1]

            self.show_links(
                batch,
                type_name,
            )

    def go_back(self):

        if len(self.path_stack) == 2:

            self.show_types(
                self.path_stack[0][1]
            )

        elif len(self.path_stack) == 1:

            self.show_batches()

    # ========================================================
    # Search
    # ========================================================

    def on_search_changed(self):

        if len(self.path_stack) == 2:
            self._refresh_links()

    def on_filter_changed(self):

        if len(self.path_stack) != 2:
            return

        self.status_filter = (
            self.filter_combo.get()
        )

        self._refresh_links()

    # ========================================================
    # Tree headings
    # ========================================================

    def _set_headings(
        self,
        c1,
        c2,
        c3,
        c4="",
        c5="",
    ):

        values = (
            c1,
            c2,
            c3,
            c4,
            c5,
        )

        columns = (
            "id",
            "link",
            "status",
            "note",
            "action",
        )

        anchors = ("w", "e", "e", "w", "center") if len(self.path_stack) < 2 else (
            "e", "w", "w", "w", "center",
        )
        for column, value, anchor in zip(columns, values, anchors):
            self.listbox.heading(column, text=value, anchor=anchor)
            self.listbox.column(column, anchor=anchor)

        self.root.after_idle(
            self._resize_columns
        )

    # ========================================================
    # Resize
    # ========================================================

    def _resize_columns(
        self,
        event=None,
    ):

        total = self.listbox.winfo_width()

        if total < 200:
            return

        # Batch / Type
        if len(self.path_stack) < 2:

            self.listbox.column(
                "id",
                width=int(total * 0.45),
                minwidth=120,
                stretch=True,
            )

            self.listbox.column(
                "link",
                width=int(total * 0.28),
                minwidth=80,
                stretch=True,
            )

            self.listbox.column(
                "status",
                width=int(total * 0.20),
                minwidth=80,
                stretch=True,
            )

            self.listbox.column(
                "note",
                width=1,
                minwidth=1,
                stretch=False,
            )

            self.listbox.column(
                "action",
                width=1,
                minwidth=1,
                stretch=False,
            )

            return

        self.listbox.column(
            "id",
            width=64,
            minwidth=54,
            stretch=False,
        )

        self.listbox.column(
            "status",
            width=80,
            minwidth=70,
            stretch=False,
        )

        self.listbox.column(
            "action",
            width=56,
            minwidth=50,
            stretch=False,
        )

        remain = total - 200

        self.listbox.column(
            "link",
            width=int(remain * 0.68),
            minwidth=120,
            stretch=True,
        )

        self.listbox.column(
            "note",
            width=int(remain * 0.32),
            minwidth=60,
            stretch=True,
        )

    # ========================================================
    # Select
    # ========================================================

    def on_select(self, event=None):

        selected = self.listbox.selection()

        if len(self.path_stack) < 2:
            return

        if not selected:

            self.selection_count.config(
                text="未选择"
            )

            return

        self.selection_count.config(
            text=f"{len(selected)} 条"
        )

        index = self.listbox.index(
            selected[0]
        )

        if index >= len(self._current_items):
            return

        record = self._current_items[index]

        self.show_record_detail(
            record
        )

        if len(selected) == 1:

            self._set_entry_value(
                self.note_entry,
                record.get("note", ""),
            )

            self._set_entry_value(
                self.approver_entry,
                record.get("approver", ""),
            )

    # ========================================================
    # Double click
    # ========================================================

    def on_double_click(
        self,
        event=None,
    ):

        selected = self.listbox.selection()

        if not selected:
            return

        index = self.listbox.index(
            selected[0]
        )

        if not self.path_stack:

            batches = sorted(
                self.tree,
                reverse=True,
            )

            if index < len(batches):

                self.show_types(
                    batches[index]
                )

            return

        if len(self.path_stack) == 1:

            batch = self.path_stack[0][1]

            types = self.tree.get(
                batch,
                {},
            )

            ordered = sorted(
                types,
                key=lambda key: (
                    -len(types[key]),
                    key,
                ),
            )

            if index < len(ordered):

                self.show_links(
                    batch,
                    ordered[index],
                )

            return

        if index < len(
            self._current_items
        ):

            self.show_record_detail(
                self._current_items[index]
            )

    # ========================================================
    # Click Copy
    # ========================================================

    def on_click(
        self,
        event,
    ):

        if len(self.path_stack) < 2:
            return

        if (
            self.listbox.identify_region(
                event.x,
                event.y,
            )
            != "cell"
        ):
            return

        if (
            self.listbox.identify_column(
                event.x
            )
            != "#5"
        ):
            return

        item = self.listbox.identify_row(
            event.y
        )

        if not item:
            return

        index = self.listbox.index(
            item
        )

        if index >= len(
            self._current_items
        ):
            return

        link = self._current_items[
            index
        ].get("link", "")

        if not link:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(link)

        self.set_status("已复制")

        self._toast(
            event.x_root,
            event.y_root,
            "已复制",
        )

        return "break"

    # ========================================================
    # Detail
    # ========================================================

    def _clear_detail(self):

        self._detail_record = None

        self.detail_content.pack_forget()

        self.detail_empty.pack(
            fill=tk.BOTH,
            expand=True,
        )

    def show_record_detail(
        self,
        record,
    ):

        self._detail_record = record

        self.detail_empty.pack_forget()

        self.detail_content.pack(
            fill=tk.BOTH,
            expand=True,
        )

        self.detail_canvas.yview_moveto(0)

        for key, label in self.detail_labels.items():

            value = record.get(
                key,
                "",
            )

            label.config(
                text=value or "-",
                bg=C["card"],
                fg=C["sub"],
                padx=0,
                pady=0,
            )

        status = record.get(
            "status",
            "",
        )

        self.detail_labels[
            "status"
        ].config(
            bg=status_bg(status),
            fg=status_fg(status),
            padx=6,
            pady=3,
        )

    def copy_current_detail_link(self):

        if not self._detail_record:
            return

        link = self._detail_record.get(
            "link",
            "",
        )

        if not link:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(link)

        self.set_status("已复制")

    # ========================================================
    # Helpers
    # ========================================================

    def _toast(
        self,
        x,
        y,
        text,
    ):

        toast = tk.Toplevel(
            self.root
        )

        toast.overrideredirect(True)

        toast.attributes(
            "-topmost",
            True,
        )

        tk.Label(
            toast,
            text=text,

            bg=C["soft"],
            fg=C["text"],

            font=FONT_CAPTION,

            padx=12,
            pady=8,
            highlightthickness=1,
            highlightbackground=C["line"],
        ).pack()

        toast.update_idletasks()

        toast.geometry(
            f"+{x - toast.winfo_width() // 2}"
            f"+{y - 40}"
        )

        toast.after(
            800,
            toast.destroy,
        )

    def save_all(self):
        try:
            save_jsonl_records(JSONL_PATH, self.records)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            messagebox.showerror("保存失败", f"{exc}\n修改尚未保存。", parent=self.root)
            return False
        return True

    def _update_sidebar_count(self):

        if hasattr(
            self,
            "sidebar_count",
        ):
            self.sidebar_count.config(
                text=f"{len(self.tree)} 个批次"
            )

    def set_status(
        self,
        text,
    ):

        self.statusbar.config(
            text=text
        )


# ============================================================
# Main
# ============================================================

def main():

    root = tk.Tk()

    LinkBrowserApp(root)

    root.mainloop()


if __name__ == "__main__":
    main()


# {
#   "xxs": { "us": "0", "uk": "4", "aus": "4", "fr": "32", "ity": "36" },
#   "xs": { "us": "2", "uk": "6", "aus": "6", "fr": "34", "ity": "38" },
#   "s": { "us": "4", "uk": "8", "aus": "8", "fr": "36", "ity": "40" },
#   "m": { "us": "6", "uk": "10", "aus": "10", "fr": "38", "ity": "42" },
#   "l": { "us": "8", "uk": "12", "aus": "12", "fr": "40", "ity": "44" },
#   "xl": { "us": "10", "uk": "14", "aus": "14", "fr": "42", "ity": "46" },
#   "xxl": { "us": "12", "uk": "16", "aus": "16", "fr": "44", "ity": "48" },
#   "3xl": { "us": "14", "uk": "18", "aus": "18", "fr": "46", "ity": "50" },
#   "4xl": { "us": "16", "uk": "20", "aus": "20", "fr": "48", "ity": "52" },
#   "1x": { "us": "16W", "uk": "20", "aus": "20", "fr": "48", "ity": "52" },
#   "2x_18w": { "us": "18W", "uk": "22", "aus": "22", "fr": "50", "ity": "54" },
#   "2x_20w": { "us": "20W", "uk": "24", "aus": "24", "fr": "52", "ity": "56" },
#   "3x_22w": { "us": "22W", "uk": "26", "aus": "26", "fr": "54", "ity": "58" },
#   "3x_24w": { "us": "24W", "uk": "28", "aus": "28", "fr": "56", "ity": "60" },
#   "4x_26w": { "us": "26W", "uk": "30", "aus": "30", "fr": "58", "ity": "62" }
# }
