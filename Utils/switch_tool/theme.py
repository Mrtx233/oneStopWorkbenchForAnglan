"""商品转换工具的曜石黑金界面样式。"""

import tkinter as tk
from tkinter import ttk

BG = "#14161a"
SURFACE = "#24262b"
INPUT = "#1a1c20"
TEXT = "#eeeae2"
MUTED = "#aaa59a"
LINE = "#595248"
SIDE = "#1d1f24"
PRIMARY = "#d1b06f"
PRIMARY_HOVER = "#e2c58a"
PRIMARY_PRESSED = "#b99959"
ON_ACCENT = "#191711"
SELECTION = "#433a29"
SELECTED_FG = "#efcf90"
FOCUS = "#edca80"
ERROR = "#f29a8e"
DISABLED = "#827e75"


def configure_theme(root):
    """只配置当前 Tk 实例的控件外观，不读取或改写业务数据。"""
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=BG)
    root.option_add("*Font", ("Microsoft YaHei UI", 10))
    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECTION)
    root.option_add("*TCombobox*Listbox.selectForeground", SELECTED_FG)
    style.configure(".", font=("Microsoft YaHei UI", 10), background=SURFACE,
                    foreground=TEXT, fieldbackground=INPUT, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, troughcolor=INPUT,
                    selectbackground=SELECTION, selectforeground=SELECTED_FG,
                    focuscolor=FOCUS)
    style.configure("TFrame", background=SURFACE)
    style.configure("App.TFrame", background=BG)
    style.configure("TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("TSeparator", background=LINE)
    style.configure("TLabelframe", background=SURFACE, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=SURFACE, foreground=PRIMARY,
                    font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("TPanedwindow", background=BG, sashwidth=7, sashrelief="flat")

    style.configure("TButton", background="#303237", foreground=TEXT,
                    bordercolor=LINE, lightcolor="#303237", darkcolor="#303237",
                    padding=(10, 6), relief="flat", borderwidth=1, focusthickness=1,
                    focuscolor=FOCUS, anchor="center")
    style.map("TButton",
              background=[("disabled", SURFACE), ("pressed", SELECTION), ("active", "#3b3934")],
              foreground=[("disabled", DISABLED), ("pressed", SELECTED_FG)],
              bordercolor=[("disabled", "#404043"), ("focus", FOCUS), ("active", PRIMARY)],
              lightcolor=[("disabled", SURFACE), ("pressed", SELECTION), ("active", "#3b3934")],
              darkcolor=[("disabled", SURFACE), ("pressed", SELECTION), ("active", "#3b3934")])
    style.configure("Primary.TButton", background=PRIMARY, foreground=ON_ACCENT,
                    bordercolor=PRIMARY, lightcolor=PRIMARY, darkcolor=PRIMARY,
                    font=("Microsoft YaHei UI", 10, "bold"), focuscolor=ON_ACCENT)
    for option in ("background", "bordercolor", "lightcolor", "darkcolor"):
        style.map("Primary.TButton", **{option: [("disabled", "#3d3930"),
                  ("pressed", PRIMARY_PRESSED), ("active", PRIMARY_HOVER)]})
    style.map("Primary.TButton", foreground=[("disabled", "#a69a7f"), ("!disabled", ON_ACCENT)])

    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=INPUT, background=INPUT, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=LINE, lightcolor=INPUT, darkcolor=INPUT,
                        padding=(7, 5), borderwidth=1, arrowcolor=MUTED, arrowsize=13)
        style.map(name, fieldbackground=[("disabled", SURFACE), ("readonly", INPUT)],
                  background=[("disabled", SURFACE), ("active", SELECTION), ("readonly", INPUT)],
                  foreground=[("disabled", DISABLED), ("readonly", TEXT)],
                  bordercolor=[("disabled", "#404043"), ("focus", FOCUS), ("active", PRIMARY)],
                  lightcolor=[("focus", INPUT)], darkcolor=[("focus", INPUT)],
                  arrowcolor=[("disabled", DISABLED), ("active", PRIMARY_HOVER)])
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(name, background="#4d4941", troughcolor=INPUT, bordercolor=INPUT,
                        lightcolor="#4d4941", darkcolor="#4d4941", arrowcolor=MUTED,
                        gripcount=0, borderwidth=0, arrowsize=12, width=12, relief="flat")
        style.map(name, background=[("disabled", SURFACE), ("pressed", PRIMARY), ("active", PRIMARY_HOVER)],
                  arrowcolor=[("disabled", DISABLED), ("active", ON_ACCENT)])

    # 使用小方形图标覆盖 clam 的浅色原生勾选框，保留原生键盘/变量绑定。
    def indicator(selected=False, disabled=False, active=False):
        image = tk.PhotoImage(master=root, width=22, height=18)
        edge = DISABLED if disabled else PRIMARY if selected or active else LINE
        fill = "#494338" if disabled and selected else PRIMARY if selected else INPUT
        image.put(edge, to=(0, 1, 16, 17))
        image.put(fill, to=(1, 2, 15, 16))
        if selected:
            ink = MUTED if disabled else ON_ACCENT
            for x, y in ((4, 8), (5, 9), (6, 10), (7, 9), (8, 8), (9, 7), (10, 6), (11, 5)):
                image.put(ink, to=(x, y, x + 2, y + 2))
        return image

    images = [indicator(), indicator(True), indicator(disabled=True),
              indicator(True, True), indicator(active=True)]
    root._switch_theme_images = images
    style.element_create("Switch.Check.indicator", "image", images[0],
                         ("disabled", "selected", images[3]), ("disabled", images[2]),
                         ("selected", images[1]), ("active", images[4]))
    style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
        ("Switch.Check.indicator", {"side": "left", "sticky": ""}),
        ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
            ("Checkbutton.label", {"sticky": "nswe"})]})]})])
    style.configure("TCheckbutton", background=SURFACE, foreground=TEXT,
                    padding=(0, 2), focuscolor=FOCUS)
    style.map("TCheckbutton", background=[("active", SURFACE)],
              foreground=[("disabled", DISABLED)])
    return style
