"""商品数据工具使用的共享石墨灰与暖金主题。"""

from tkinter import ttk

from workbench_ui import (
    SURFACE, SIDE, INPUT, TEXT, MUTED, LINE, PRIMARY,
    SELECTION, SELECTION_FG as SELECTED_FG, FOCUS, DANGER as ERROR,
    SOFT, HOVER,
    apply_workbench_controls,
)


def configure_theme(root):
    """配置共享基础控件，再补上当前工具的表格样式。"""
    style = apply_workbench_controls(root)
    style.configure('Treeview', background=INPUT, foreground=TEXT, fieldbackground=INPUT,
                    rowheight=32, borderwidth=0, font=('TkDefaultFont', 10))
    style.configure('Treeview.Heading', background=SOFT, foreground=MUTED,
                    relief='flat', borderwidth=0, padding=(10, 8))
    style.map('Treeview', background=[('selected', SELECTION)],
              foreground=[('selected', SELECTED_FG)])
    style.map('Treeview.Heading', background=[('active', HOVER)])
    return style
