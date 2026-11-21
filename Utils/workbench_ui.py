"""共享的 Tk 工具色板、导航和控件样式。"""

import math
import struct
import tkinter as tk
from tkinter import font as tkfont, ttk
import zlib

BG = '#191a1c'
SIDE = BG
SURFACE = '#222325'
INPUT = '#1a1b1d'
SOFT = '#292a2d'
RAISED = '#2d2e31'
HOVER = '#36373b'
PRESSED = '#252628'
LINE = '#3a3b3e'
TEXT = '#edeeef'
MUTED = '#acadaf'
PRIMARY = '#d9b77c'
PRIMARY_HOVER = '#e5c895'
PRIMARY_PRESSED = '#c4a46e'
ON_PRIMARY = '#251d12'
FOCUS = '#e5c895'
SELECTION = '#3c382f'
SELECTION_FG = '#f0dfc1'
DISABLED_BG = '#2b2c2f'
DISABLED_FG = '#909296'
DANGER = '#e6aaa2'
DANGER_BG = '#392b2b'
DANGER_HOVER = '#493330'
DANGER_PRESSED = '#512f2d'
SCROLL = '#55565a'
SCROLL_HOVER = '#717277'

UI_FONTS = ('Microsoft YaHei UI', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC', 'Heiti SC')
MONO_FONTS = ('Cascadia Code', 'Consolas', 'SF Mono', 'Menlo', 'DejaVu Sans Mono')


def choose_font(root, candidates=UI_FONTS):
    families = set(tkfont.families(root))
    return next((font for font in candidates if font in families), 'TkDefaultFont')


class WorkbenchNav(tk.Canvas):
    """由阶段编号、标题和键盘焦点组成的导航项。"""

    def __init__(self, master, index, title, hint='', command=None, *, width=180, height=36, **kwargs):
        super().__init__(master, bg=SIDE, bd=0, highlightthickness=0,
                         width=width, height=height, cursor='hand2', takefocus=True, **kwargs)
        self.index, self.title = index, title
        self.command = command or (lambda: None)
        self.ui_font = choose_font(self)
        self.mono_font = choose_font(self, MONO_FONTS)
        self.selected = self.hovered = self.focused = False
        self.bind('<Configure>', self._draw)
        self.bind('<Button-1>', self._activate)
        self.bind('<Return>', self._activate)
        self.bind('<space>', self._activate)
        self.bind('<Enter>', lambda _e: self._set_state('hovered', True))
        self.bind('<Leave>', lambda _e: self._set_state('hovered', False))
        self.bind('<FocusIn>', lambda _e: self._set_state('focused', True))
        self.bind('<FocusOut>', lambda _e: self._set_state('focused', False))

    def _activate(self, _event):
        self.focus_set()
        self.command()
        return 'break'

    def _set_state(self, name, value):
        setattr(self, name, value)
        self._draw()

    def set_selected(self, value):
        self._set_state('selected', value)

    def _draw(self, _event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if min(width, height) <= 2:
            return
        self.delete('all')
        fill = RAISED if self.selected else SOFT if self.hovered else SIDE
        edge = FOCUS if self.focused else HOVER if self.selected else fill
        self.create_rectangle(1, 1, width - 1, height - 1, fill=fill, outline=edge)
        middle = height / 2
        if self.selected:
            self.create_rectangle(2, middle - 10, 4, middle + 10, fill=PRIMARY, outline='')
        label = f'{self.index:02d}' if isinstance(self.index, int) else str(self.index)
        self.create_text(12, middle, text=label, anchor='w', font=(self.mono_font, 10),
                         fill=PRIMARY if self.selected else MUTED)
        self.create_text(40, middle, text=self.title, anchor='w', font=(self.ui_font, 11), fill=TEXT)


def _control_image(root, fill, outline):
    """24px RGBA 素材；6px 圆角完全处于 8px 固定切片内。"""
    size, radius = 24, 6
    rgb = lambda color: tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    fill_rgb, edge_rgb = rgb(fill), rgb(outline)
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            samples = []
            for oy in (.125, .375, .625, .875):
                for ox in (.125, .375, .625, .875):
                    qx, qy = abs(x + ox - 12) - 6, abs(y + oy - 12) - 6
                    d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius
                    if d <= 0:
                        samples.append(edge_rgb if d > -1 else fill_rgb)
            if samples:
                pixels.extend(round(sum(c[i] for c in samples) / len(samples)) for i in range(3))
                pixels.append(round(255 * len(samples) / 16))
            else:
                pixels.extend((0, 0, 0, 0))
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', size, size, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))
    return tk.PhotoImage(master=root, data=png, format='png')


def _check_image(root, *, selected=False, disabled=False, focused=False):
    image = tk.PhotoImage(master=root, width=24, height=16)
    edge = LINE if disabled else FOCUS if focused else PRIMARY if selected else SCROLL
    fill = DISABLED_BG if disabled else PRIMARY if selected else INPUT
    image.put(edge, to=(0, 0, 16, 16))
    image.put(fill, to=(1, 1, 15, 15))
    if selected:
        ink = DISABLED_FG if disabled else ON_PRIMARY
        for x, y in ((4, 8), (5, 9), (6, 10), (7, 9), (8, 8), (9, 7), (10, 6), (11, 5)):
            image.put(ink, to=(x, y, x + 2, y + 2))
    return image


def apply_workbench_controls(root):
    """为当前 Tk 窗口配置主题，保留原生状态和键盘绑定。"""
    style = ttk.Style(root)
    if getattr(root, '_workbench_images', None):
        return style
    style.theme_use('clam')
    font = choose_font(root)
    root.configure(background=BG)
    root._workbench_images = []
    style.configure('.', font=(font, 10), background=SURFACE, foreground=TEXT, focuscolor=FOCUS)
    style.configure('TFrame', background=SURFACE)
    style.configure('TLabel', background=SURFACE, foreground=TEXT)
    style.configure('Title.TLabel', font=(font, 24))
    style.configure('Section.TLabel', font=(font, 11, 'bold'))
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('TSeparator', background=LINE, bordercolor=LINE)

    palettes = {
        'TButton': (RAISED, LINE, HOVER, PRESSED, TEXT),
        'Primary.TButton': (PRIMARY, PRIMARY, PRIMARY_HOVER, PRIMARY_PRESSED, ON_PRIMARY),
        'Danger.TButton': (DANGER_BG, DANGER_BG, DANGER_HOVER, DANGER_PRESSED, DANGER),
    }
    for name, (fill, edge, hover, pressed, fg) in palettes.items():
        images = [_control_image(root, color, rim) for color, rim in (
            (fill, edge), (hover, edge), (pressed, edge), (DISABLED_BG, LINE), (fill, FOCUS))]
        root._workbench_images.extend(images)
        element = 'Workbench.' + name.replace('.', '_')
        style.element_create(element, 'image', images[0], ('disabled', images[3]),
                             ('pressed', images[2]), ('focus', images[4]), ('active', images[1]),
                             border=8, padding=0, sticky='nsew')
        style.layout(name, [(element, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])
        style.configure(name, background=SURFACE, foreground=fg, padding=(16, 8),
                        font=(font, 10), anchor='center')
        style.map(name, background=[('disabled', SURFACE), ('pressed', SURFACE), ('active', SURFACE)],
                  foreground=[('disabled', DISABLED_FG), ('!disabled', fg)])

    fields = [_control_image(root, color, edge) for color, edge in (
        (INPUT, LINE), (INPUT, FOCUS), (SOFT, LINE))]
    root._workbench_images.extend(fields)
    style.element_create('Workbench.field', 'image', fields[0], ('disabled', fields[2]),
                         ('focus', fields[1]), border=8, padding=0, sticky='nsew')
    style.layout('TEntry', [('Workbench.field', {'sticky': 'nsew', 'children': [
        ('Entry.padding', {'sticky': 'nsew', 'children': [('Entry.textarea', {'sticky': 'nsew'})]})]})])
    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(name, padding=(8, 4), background=INPUT, fieldbackground=INPUT,
                        foreground=TEXT, insertcolor=TEXT, selectbackground=SELECTION,
                        selectforeground=SELECTION_FG, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                        arrowcolor=MUTED, arrowsize=12)
        style.map(name, background=[('disabled', SOFT), ('readonly', INPUT), ('active', SOFT)],
                  fieldbackground=[('disabled', SOFT), ('readonly', INPUT)],
                  foreground=[('disabled', DISABLED_FG)], bordercolor=[('focus', FOCUS)],
                  lightcolor=[('focus', FOCUS)], darkcolor=[('focus', FOCUS)])
    style.configure('TEntry', padding=(12, 8), background=SURFACE)
    style.map('TEntry', background=[('disabled', SURFACE), ('readonly', SURFACE),
                                    ('focus', SURFACE), ('active', SURFACE)])
    for option, value in (('background', INPUT), ('foreground', TEXT), ('selectBackground', SELECTION),
                          ('selectForeground', SELECTION_FG), ('font', (font, 10))):
        root.option_add('*TCombobox*Listbox.' + option, value)

    checks = [_check_image(root, **state) for state in (
        {}, {'selected': True}, {'disabled': True}, {'selected': True, 'disabled': True},
        {'focused': True}, {'selected': True, 'focused': True},
    )]
    root._workbench_images.extend(checks)
    indicator = 'Workbench.Checkbutton.indicator'
    style.element_create(indicator, 'image', checks[0],
                         ('disabled', 'selected', checks[3]), ('disabled', checks[2]),
                         ('focus', 'selected', checks[5]), ('focus', checks[4]),
                         ('selected', checks[1]))
    style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nsew', 'children': [
        (indicator, {'side': 'left', 'sticky': ''}),
        ('Checkbutton.label', {'side': 'left', 'sticky': 'w'}),
    ]})])
    style.configure('TCheckbutton', padding=(0, 4), background=SURFACE, foreground=TEXT)
    style.map('TCheckbutton', background=[('active', SURFACE)], foreground=[('disabled', DISABLED_FG)])

    style.configure('TScrollbar', background=SCROLL, troughcolor=INPUT, bordercolor=INPUT,
                    lightcolor=SCROLL, darkcolor=SCROLL, borderwidth=0, gripcount=0, width=8)
    style.map('TScrollbar', background=[('active', SCROLL_HOVER)])
    for direction, sticky in (('Vertical', 'ns'), ('Horizontal', 'ew')):
        style.layout(direction + '.TScrollbar', [
            (direction + '.Scrollbar.trough', {'sticky': sticky, 'children': [
                (direction + '.Scrollbar.thumb', {'expand': '1', 'sticky': 'nsew'})]})])
    style.configure('TProgressbar', background=PRIMARY, troughcolor=INPUT, bordercolor=INPUT,
                    lightcolor=PRIMARY, darkcolor=PRIMARY, borderwidth=0, thickness=4)
    return style
