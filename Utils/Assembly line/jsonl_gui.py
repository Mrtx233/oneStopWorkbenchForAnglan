# -*- coding: utf-8 -*-

import json
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from urllib.parse import urlparse

UTILS_DIR = Path(__file__).resolve().parents[1]
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))
from workbench_ui import GlassBackground, GlassPanel, GlassNav, apply_glass_controls


JSONL_PATH = Path(__file__).parent / "links.jsonl"


# ============================================================
# 固定曜石黑金主题；所有控件共用语义色，状态由文字与符号辅助表达。
# ============================================================

C = {
    "bg": "#14161a",
    "sidebar": "#1d1f24",
    "sidebar_hover": "#323033",
    "card": "#24262b",
    "input": "#1a1c20",
    "soft": "#292a2d",
    "line": "#595248",
    "text": "#eeeae2",
    "sub": "#c9c3b7",
    "muted": "#aaa59a",
    "primary": "#d1b06f",
    "primary_hover": "#e2c58a",
    "primary_soft": "#433a29",
    "on_accent": "#191711",
    "selected_text": "#efcf90",
    "row_alt": "#292b30",
    "focus": "#edca80",
    "signal_neutral": "#c9c3b7",
    "signal_progress": "#86c6d3",
    "signal_good": "#83c6a4",
    "signal_warn": "#e2bd77",
    "signal_alert": "#ee9a92",
    "signal_soft": "#2d2e32",
}


# 只用系统字体族；层级靠字号与字重，桌面最小 10pt。
FONT = "Microsoft YaHei UI"

FONT_BODY = (FONT, 11)
FONT_SMALL = (FONT, 10)
FONT_CAPTION = (FONT, 10)
FONT_TITLE = (FONT, 20, "bold")
FONT_SECTION = (FONT, 12, "bold")
FONT_LABEL = (FONT, 10, "bold")
FONT_HEADING = (FONT, 10, "bold")
FONT_ICON = (FONT, 13)
FONT_BRAND = (FONT, 13, "bold")
FONT_MONO = ("Consolas", 11)


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


# 颜色只表达「大类」，具体含义由文字承载：一个颜色一个意思。
# 形状符号让状态不只靠颜色传达。
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
    "neutral": ("○", "signal_neutral", "signal_soft"),
    "progress": ("◐", "signal_progress", "signal_soft"),
    "good": ("●", "signal_good", "signal_soft"),
    "warn": ("△", "signal_warn", "signal_soft"),
    "alert": ("!", "signal_alert", "signal_soft"),
}


def status_role(status):
    return STATUS_ROLE.get(status, "neutral")


def status_glyph(status):
    return ROLE_STYLE[status_role(status)][0]


def status_fg(status):
    return C[ROLE_STYLE[status_role(status)][1]]


def status_bg(status):
    return C[ROLE_STYLE[status_role(status)][2]]


# 保留给外部读取，与固定主题保持一致。
STATUS_THEME = {
    name: (status_fg(name), status_bg(name))
    for name in set(STATUS_ROLE) | set(STATUS_PRESETS)
}


# ============================================================
# Data
# ============================================================

def load_records():
    records = []

    if not JSONL_PATH.exists():
        return records

    for line in JSONL_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return records


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

    # ========================================================
    # ttk
    # ========================================================

    def _setup_styles(self):

        style = ttk.Style()

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Combobox 弹出的 Listbox 不继承 ttk 样式，需要单独设置。
        for option, value in {
            "background": C["input"],
            "foreground": C["text"],
            "selectBackground": C["primary_soft"],
            "selectForeground": C["selected_text"],
            "highlightBackground": C["line"],
            "highlightColor": C["focus"],
            "borderWidth": 0,
            "relief": "flat",
            "font": FONT_BODY,
        }.items():
            self.root.option_add(f"*TCombobox*Listbox.{option}", value)

        # 表格：安静的行、清晰的表头，选中行用强调色标出当前位置
        style.configure(
            "Modern.Treeview",
            background=C["card"],
            foreground=C["text"],
            fieldbackground=C["card"],
            bordercolor=C["card"],
            lightcolor=C["card"],
            darkcolor=C["card"],
            borderwidth=0,
            relief="flat",
            rowheight=34,
            font=FONT_BODY,
        )

        style.configure(
            "Modern.Treeview.Heading",
            background=C["soft"],
            foreground=C["sub"],
            bordercolor=C["soft"],
            lightcolor=C["soft"],
            darkcolor=C["soft"],
            borderwidth=0,
            relief="flat",
            font=FONT_HEADING,
            padding=(12, 10),
        )

        style.map(
            "Modern.Treeview.Heading",
            background=[
                ("active", C["sidebar_hover"])
            ],
        )

        style.map(
            "Modern.Treeview",
            background=[
                ("selected", C["primary_soft"])
            ],
            foreground=[
                ("selected", C["selected_text"])
            ],
        )

        # 输入类控件：静态细边，聚焦时边框变强调色（键盘可达的可见反馈）
        for name in (
            "Modern.TEntry",
            "Modern.TCombobox",
            "Hint.TEntry",
        ):
            foreground = C["muted"] if name == "Hint.TEntry" else C["text"]
            style.configure(
                name,
                fieldbackground=C["input"],
                background=C["input"],
                foreground=foreground,
                arrowcolor=C["primary"],
                bordercolor=C["line"],
                lightcolor=C["line"],
                darkcolor=C["line"],
                insertcolor=C["text"],
                selectbackground=C["primary_soft"],
                selectforeground=C["selected_text"],
                relief="flat",
                padding=8,
            )

            style.map(
                name,
                bordercolor=[
                    ("disabled", C["line"]),
                    ("focus", C["focus"])
                ],
                lightcolor=[
                    ("disabled", C["line"]),
                    ("focus", C["focus"])
                ],
                darkcolor=[
                    ("disabled", C["line"]),
                    ("focus", C["focus"])
                ],
                fieldbackground=[
                    ("disabled", C["soft"]),
                    ("readonly", C["input"]),
                ],
                background=[
                    ("disabled", C["soft"]),
                    ("active", C["primary_soft"]),
                    ("readonly", C["input"]),
                ],
                foreground=[
                    ("disabled", C["muted"]),
                    ("readonly", foreground),
                ],
                arrowcolor=[
                    ("disabled", C["muted"]),
                    ("active", C["selected_text"]),
                ],
            )

        style.configure(
            "Vertical.TScrollbar",
            background=C["sidebar_hover"],
            troughcolor=C["card"],
            bordercolor=C["card"],
            lightcolor=C["sidebar_hover"],
            darkcolor=C["sidebar_hover"],
            arrowcolor=C["sub"],
            relief="flat",
        )

        style.map(
            "Vertical.TScrollbar",
            background=[
                ("disabled", C["soft"]),
                ("pressed", C["primary"]),
                ("active", C["primary_soft"]),
            ],
            arrowcolor=[("active", C["selected_text"])],
        )
        apply_glass_controls(self.root)
        for name in ("Modern.TEntry", "Hint.TEntry"):
            style.configure(name, background=C["card"], padding=(10, 7))
            style.map(name, background=[("disabled", C["card"]),
                                        ("readonly", C["card"]),
                                        ("focus", C["card"]),
                                        ("active", C["card"])])

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

    def card(self, parent):

        return tk.Frame(
            parent,
            bg=C["card"],
            highlightthickness=1,
            highlightbackground=C["line"],
        )

    # ========================================================
    # Shell
    # ========================================================

    def _build_app(self):
        self.background = GlassBackground(self.root)
        self.background.pack(fill=tk.BOTH, expand=True)
        self.main = self.background
        self.main.columnconfigure(1, weight=1)
        self.main.rowconfigure(1, weight=1)
        self.sidebar_panel = GlassPanel(self.main, padding=10, fill=C["sidebar"], width=190)
        self.sidebar_panel.grid(row=0, column=0, rowspan=3, sticky="nsew",
                                padx=(16, 10), pady=16)
        self.sidebar = self.sidebar_panel.body
        self._build_sidebar()
        self._build_header()
        self.page_host = tk.Frame(self.main, bg=C["bg"])
        self.page_host.grid(row=1, column=1, sticky="nsew", padx=(0, 16))
        self.library_page = tk.Frame(self.page_host, bg=C["bg"])
        self.add_page = tk.Frame(self.page_host, bg=C["bg"])
        self._build_library_page()
        self._build_add_page()
        self._build_statusbar()

    # ========================================================
    # Sidebar
    # ========================================================

    def _build_sidebar(self):
        brand = tk.Frame(self.sidebar, bg=C["sidebar"])
        brand.pack(fill=tk.X, padx=6, pady=(14, 24))
        tk.Label(brand, text="L /", bg=C["sidebar"], fg=C["primary"],
                 font=("Segoe UI", 25, "bold")).pack(anchor="w")
        tk.Label(brand, text="链接库", bg=C["sidebar"], fg=C["text"],
                 font=(FONT, 17, "bold")).pack(anchor="w", pady=(6, 3))
        tk.Label(brand, text="LINK ARCHIVE", bg=C["sidebar"], fg=C["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Frame(self.sidebar, bg=C["line"], height=1).pack(fill=tk.X, padx=6, pady=(0, 16))
        self.nav_buttons = {
            "library": self._create_nav("library", "01", "浏览链接"),
            "add": self._create_nav("add", "02", "新增链接"),
        }
        tk.Frame(self.sidebar, bg=C["sidebar"]).pack(fill=tk.BOTH, expand=True)
        footer = tk.Frame(self.sidebar, bg=C["sidebar"])
        footer.pack(fill=tk.X, padx=6, pady=(18, 12))
        tk.Label(footer, text="本地链接档案", bg=C["sidebar"], fg=C["sub"],
                 font=FONT_LABEL).pack(anchor="w")
        self.sidebar_count = tk.Label(footer, text="", bg=C["sidebar"],
                                      fg=C["primary"], font=FONT_CAPTION)
        self.sidebar_count.pack(anchor="w", pady=(6, 0))
        self._update_sidebar_count()

    def _create_nav(self, key, icon, title):
        hint = "批次 / 分类 / 审核" if key == "library" else "批量导入 / 自动归档"
        nav = GlassNav(self.sidebar, index=icon, title=title, hint=hint,
                       command=lambda: self.switch_page(key), width=160)
        nav.pack(fill=tk.X, pady=4)
        return nav

    def _hover_nav(self, box, entering):
        # 指针与键盘反馈由公共导航组件统一绘制。
        return

    def _set_active_nav(self, key):
        for nav_key, nav in self.nav_buttons.items():
            nav.set_selected(nav_key == key)

    # ========================================================
    # Header
    # ========================================================

    def _build_header(self):
        self.header_panel = GlassPanel(self.main, padding=14, fill=C["card"], height=112)
        self.header_panel.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=(16, 10))
        header = self.header_panel.body
        header.columnconfigure(0, weight=1)
        self.page_title = tk.Label(header, text="链接库", bg=C["card"],
                                    fg=C["text"], font=(FONT, 19, "bold"), anchor="w")
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_subtitle = tk.Label(header, text="按批次与分类浏览，集中整理链接审核进度。",
                                       bg=C["card"], fg=C["muted"], font=FONT_SMALL, anchor="w")
        self.page_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.header_action = self.button(header, "＋ 录入链接", lambda: self.switch_page("add"),
                                          kind="primary", padx=14, pady=7, font=FONT_SMALL)
        self.header_action.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))

    # ========================================================
    # Statusbar
    # ========================================================

    def _build_statusbar(self):
        bar = tk.Frame(self.main, bg=C["bg"])
        bar.grid(row=2, column=1, sticky="ew", padx=(8, 24), pady=(7, 12))
        self.statusbar = tk.Label(bar, text="就绪", bg=C["bg"], fg=C["muted"], font=FONT_CAPTION)
        self.statusbar.pack(side=tk.LEFT)
        tk.Label(bar, text="JSONL  /  本地档案", bg=C["bg"], fg=C["muted"],
                 font=("Segoe UI", 9)).pack(side=tk.RIGHT)

    # ========================================================
    # Switch page
    # ========================================================

    def switch_page(self, page):
        self.current_page = page
        self._set_active_nav(page)
        self.library_page.pack_forget()
        self.add_page.pack_forget()
        if page == "library":
            self.page_title.config(text="链接库")
            self.page_subtitle.config(text="按批次与分类浏览，集中整理链接审核进度。")
            self.header_action.config(text="＋ 录入链接", command=lambda: self.switch_page("add"))
            self.library_page.pack(fill=tk.BOTH, expand=True)
        else:
            self.page_title.config(text="新增链接")
            self.page_subtitle.config(text="粘贴多条链接与分类，将新记录归入同一批次。")
            self.header_action.config(text="← 返回链接库", command=lambda: self.switch_page("library"))
            self.add_page.pack(fill=tk.BOTH, expand=True)

    # ========================================================
    # Library page
    # ========================================================

    def _build_library_page(self):
        self.library_page.columnconfigure(0, weight=1)
        self.library_page.rowconfigure(0, weight=1)
        self.table_panel = GlassPanel(self.library_page, padding=6, fill=C["card"])
        self.table_panel.grid(row=0, column=0, sticky="nsew")
        self.detail_panel = GlassPanel(self.library_page, padding=6, fill=C["card"], width=210)
        self.detail_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._build_table(self.table_panel.body)
        self._build_detail(self.detail_panel.body)

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
            padx=16,
            pady=(14, 10),
        )

        self.back_btn = self.button(
            top,
            "←",
            self.go_back,
            padx=10,
            pady=5,
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
            padx=16,
            pady=(0, 10),
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
            padx=(10, 0),
        )

        self.filter_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self.on_filter_changed(),
        )

        # Treeview
        tree_frame = tk.Frame(
            parent,

            bg=C["card"],
        )

        tree_frame.pack(
            fill=tk.BOTH,
            expand=True,
            padx=16,
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

        # Batch action
        actions = tk.Frame(
            parent,
            bg=C["soft"],
        )

        actions.pack(
            side=tk.BOTTOM,
            fill=tk.X,
            padx=16,
            pady=(0, 14),
            before=tree_frame,
        )

        top_action = tk.Frame(
            actions,
            bg=C["soft"],
        )

        top_action.pack(
            fill=tk.X,
            padx=12,
            pady=(8, 6),
        )

        tk.Label(
            top_action,
            text="批量操作",

            bg=C["soft"],
            fg=C["sub"],

            font=FONT_LABEL,
        ).pack(
            side=tk.LEFT
        )

        self.selection_count = tk.Label(
            top_action,
            text="未选择",

            bg=C["soft"],
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
            bg=C["soft"],
        )

        status_row = self.status_row

        status_row.pack(
            fill=tk.X,
            padx=12,
            pady=(0, 6),
        )

        self._status_buttons = []

        for status in STATUS_PRESETS:
            role = status_role(status)
            style_name = f"Status{role}.TButton"
            style = ttk.Style(self.root)
            style.configure(style_name, foreground=status_fg(status), font=FONT_SMALL,
                            padding=(8, 5), background=C["soft"])
            style.map(style_name, foreground=[("disabled", C["muted"]),
                                              ("active", C["selected_text"]),
                                              ("!disabled", status_fg(status))],
                       background=[("disabled", C["soft"]), ("active", C["soft"]),
                                   ("pressed", C["soft"])])
            btn = ttk.Button(status_row, text=f"{status_glyph(status)} {status}",
                             command=lambda s=status: self.set_selected_status(s),
                             style=style_name, width=0, cursor="hand2", takefocus=True)
            self._status_buttons.append(btn)

        self._status_widgets = self._status_buttons

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

        gap = 5
        widgets = self._status_widgets

        for widget in widgets:
            widget.update_idletasks()

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
        ) + 6

        x = 0
        row = 0

        for widget, w in zip(widgets, widths):

            if x and x + gap + w > row_width:
                x = 0
                row += 1

            widget.place(
                x=x,
                y=row * row_height + 3,
            )

            x += w + gap

        # place 不撑开父容器，需显式给定高度
        self.status_row.configure(
            height=(row + 1) * row_height
        )

        self.status_row.pack_propagate(False)

    # ========================================================
    # Note row（归属 _build_actions）
    # ========================================================

    def _build_note_row(self, actions):
        note_row = tk.Frame(actions, bg=C["soft"])
        note_row.pack(fill=tk.X, padx=10, pady=(2, 9))
        note_row.columnconfigure(0, weight=1, uniform="fields")
        note_row.columnconfigure(2, weight=1, uniform="fields")
        self.custom_status_entry = ttk.Entry(note_row, style="Modern.TEntry", width=10, font=FONT_SMALL)
        self.custom_status_entry.grid(row=0, column=0, sticky="ew")
        self.custom_status_entry.bind("<Return>", lambda e: self.set_custom_status())
        self.button(note_row, "应用状态", self.set_custom_status, kind="primary",
                    padx=8, pady=5, font=FONT_SMALL).grid(row=0, column=1, padx=(6, 12))
        self.approver_entry = ttk.Entry(note_row, style="Modern.TEntry", width=10, font=FONT_SMALL)
        self.approver_entry.grid(row=0, column=2, sticky="ew")
        self.approver_entry.bind("<Return>", lambda e: self.apply_approver())
        self.button(note_row, "保存审批人", self.apply_approver, padx=8, pady=5,
                    font=FONT_SMALL).grid(row=0, column=3, padx=(6, 0))
        self.note_entry = ttk.Entry(note_row, style="Modern.TEntry", font=FONT_SMALL)
        self.note_entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(7, 0))
        self.note_entry.bind("<Return>", lambda e: self.apply_note())
        self.button(note_row, "保存备注", self.apply_note, padx=8, pady=5,
                    font=FONT_SMALL).grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(7, 0))
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
            padx=10,
            pady=(12, 10),
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
            padx=10,
            pady=10,
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
            pady=100
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
                pady=(0, 11),
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

                wraplength=150,
            )

            label.pack(
                fill=tk.X,
                pady=(2, 0),
            )

            self.detail_labels[key] = label

        self.button(
            self.detail_content,
            "复制链接",
            self.copy_current_detail_link,
            kind="primary",
            pady=7,
        ).pack(
            fill=tk.X,
            pady=(5, 0),
        )

    # ========================================================
    # Add page
    # ========================================================

    def _build_add_page(self):

        self.editor_panel = GlassPanel(self.add_page, padding=18, fill=C["card"])
        self.editor_panel.pack(
            fill=tk.BOTH,
            expand=True,
        )

        form = tk.Frame(
            self.editor_panel.body,
            bg=C["card"],
        )

        form.pack(
            fill=tk.BOTH,
            expand=True,
            padx=6,
            pady=4,
        )
        tk.Label(form, text="批量录入", bg=C["card"], fg=C["text"],
                 font=FONT_SECTION).pack(anchor="w")
        tk.Label(form, text="每行一条链接，末尾填写分类；保存时自动分配编号。",
                 bg=C["card"], fg=C["muted"], font=FONT_SMALL).pack(
                     anchor="w", pady=(4, 16))

        # Batch
        batch_row = tk.Frame(
            form,
            bg=C["card"],
        )

        batch_row.pack(
            fill=tk.X,
            pady=(0, 14),
        )

        tk.Label(
            batch_row,
            text="批次",

            width=8,
            anchor="w",

            bg=C["card"],
            fg=C["sub"],

            font=FONT_LABEL,
        ).pack(
            side=tk.LEFT
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
            pady=(0, 6),
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

            bg=C["card"],

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

            insertbackground=C["primary"],
            selectbackground=C["primary_soft"],
            selectforeground=C["selected_text"],

            relief=tk.FLAT,
            bd=0,

            padx=14,
            pady=12,

            undo=True,
        )

        self.entry_text.pack(
            fill=tk.BOTH,
            expand=True,
        )

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
            pady=(14, 0),
            before=editor,
        )

        tk.Label(
            bottom,
            text="格式：链接 分类",

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
            pady=7,
        ).pack(
            side=tk.RIGHT
        )

        self.button(
            bottom,
            "保存",
            self.submit_entries,
            kind="primary",
            padx=22,
            pady=7,
            font=FONT_LABEL,
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

            self.save_all()

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

        self.save_all()

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

        self.save_all()

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

        for batch in sorted(
            self.tree,
            reverse=True,
        ):

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

        for type_name in ordered:

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

        for record in items:

            status = record.get(
                "status",
                "",
            )

            tag = self._status_tag(
                status
            )

            self.listbox.tag_configure(
                tag,
                foreground=status_fg(status),
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

                tags=(tag,),
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

        for column, value in zip(
            columns,
            values,
        ):

            self.listbox.heading(
                column,
                text=value,
            )

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

    def _status_tag(self, status):

        return (
            "status_"
            + "".join(
                char
                if char.isalnum()
                else "_"
                for char in (
                    status
                    or "default"
                )
            )
        )

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

            bg=C["primary"],
            fg=C["on_accent"],

            font=FONT_CAPTION,

            padx=14,
            pady=7,
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

        with JSONL_PATH.open(
            "w",
            encoding="utf-8",
        ) as file:

            for record in self.records:

                file.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

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
