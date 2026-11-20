"""工具窗口共用的黑金浮层与控件素材，仅依赖 Tk 和标准库。"""

import math
import struct
import tkinter as tk
from tkinter import ttk
import zlib

BG = '#14161a'
SURFACE = '#24262b'
SIDE = '#1d1f24'
INPUT = '#1a1c20'
TEXT = '#eeeae2'
MUTED = '#aaa59a'
LINE = '#595248'
PRIMARY = '#d1b06f'
ON_PRIMARY = '#191711'
SELECTION = '#433a29'
FOCUS = '#edca80'


def _rounded(canvas, box, radius=18, **options):
    x1, y1, x2, y2 = box
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    return canvas.create_polygon(
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        smooth=True, splinesteps=24, **options,
    )


class GlassBackground(tk.Canvas):
    """柔焦暖光衬底；尺寸变化后合并重绘，不占用持续动画循环。"""

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=BG, bd=0, highlightthickness=0, **kwargs)
        self.photo = None
        self.panels = []
        self._render_job = None
        self.bind('<Configure>', self._schedule_render)
        self.bind('<Destroy>', self._cancel_render, add='+')

    def _cancel_render(self, event):
        if event.widget is self and self._render_job is not None:
            self.after_cancel(self._render_job)
            self._render_job = None

    def _schedule_render(self, _event=None):
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(80, self._render)

    def _render(self):
        self._render_job = None
        scale = 6
        width = max(1, math.ceil(self.winfo_width() / scale))
        height = max(1, math.ceil(self.winfo_height() / scale))
        clouds = ((.04, .08, .30, (87, 68, 37), .38),
                  (.90, .15, .36, (54, 57, 65), .34),
                  (.75, .98, .30, (91, 68, 35), .28))
        pixels = bytearray()
        for y in range(height):
            for x in range(width):
                color = [20., 22., 26.]
                for cx, cy, spread, tint, opacity in clouds:
                    alpha = opacity * math.exp(-((x / width - cx) ** 2 + (y / height - cy) ** 2)
                                               / (2 * spread ** 2))
                    color = [v * (1 - alpha) + t * alpha for v, t in zip(color, tint)]
                pixels.extend(int(v) for v in color)
        small = tk.PhotoImage(master=self, data=f'P6\n{width} {height}\n255\n'.encode() + pixels, format='PPM')
        self.photo = small.zoom(scale)
        self.delete('ambient')
        self.create_image(0, 0, image=self.photo, anchor='nw', tags='ambient')
        self.tag_lower('ambient')
        for panel in tuple(self.panels):
            if panel.winfo_exists():
                panel.redraw()


class GlassPanel(tk.Canvas):
    """细亮边、低位阴影和留白包围的面板；body 用于正常布局控件。"""

    def __init__(self, master, *, padding=18, fill=SURFACE, radius=18, width=1, height=1, **kwargs):
        super().__init__(master, bg=BG, bd=0, highlightthickness=0,
                         width=width, height=height, **kwargs)
        self.fill, self.padding, self.radius = fill, padding, radius
        self.body = tk.Frame(self, bg=fill, bd=0)
        self.content = self.body
        self._crop = None
        self.ambient = master
        while self.ambient is not None and not isinstance(self.ambient, GlassBackground):
            self.ambient = getattr(self.ambient, 'master', None)
        if self.ambient is not None:
            self.ambient.panels.append(self)
        self.bind('<Configure>', self.redraw)
        self.bind('<Destroy>', self._detach, add='+')

    def _detach(self, event):
        if event.widget is self and self.ambient is not None and self in self.ambient.panels:
            self.ambient.panels.remove(self)

    def redraw(self, _event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 12 or height < 12:
            return
        self.delete('glass')
        source = self.ambient.photo if self.ambient is not None else None
        if source is not None:
            x = max(0, self.winfo_rootx() - self.ambient.winfo_rootx())
            y = max(0, self.winfo_rooty() - self.ambient.winfo_rooty())
            cw, ch = min(width, source.width() - x), min(height, source.height() - y)
            if cw > 0 and ch > 0:
                self._crop = tk.PhotoImage(master=self, width=width, height=height)
                self._crop.tk.call(str(self._crop), 'copy', str(source),
                                   '-from', x, y, x + cw, y + ch, '-to', 0, 0)
                self.create_image(0, 0, image=self._crop, anchor='nw', tags='glass')
        for inset, offset, shade in ((0, 5, '#101114'), (2, 3, '#151619'), (3, 1, '#191a1d')):
            _rounded(self, (4 - inset, 4 + offset, width - 5 + inset, height - 5 + offset),
                     self.radius + 1, fill=shade, outline='', tags='glass')
        _rounded(self, (4, 3, width - 5, height - 8), self.radius,
                 fill=self.fill, outline='#464139', width=1, tags='glass')
        self.create_line(4 + self.radius, 3, width - 5 - self.radius, 3,
                         fill='#625747', width=1, tags='glass')
        self.tag_lower('glass')
        px, py = self.padding if isinstance(self.padding, tuple) else (self.padding, self.padding)
        self.body.place(x=5 + px, y=4 + py, width=max(1, width - 10 - 2 * px),
                        height=max(1, height - 13 - 2 * py))


class GlassNav(tk.Canvas):
    """编号、标题和辅助说明组成的可聚焦导航行。"""

    def __init__(self, master, index, title, hint='', command=None, *, width=180, height=60, **kwargs):
        super().__init__(master, bg=SIDE, bd=0, highlightthickness=0,
                         width=width, height=height, cursor='hand2', takefocus=True, **kwargs)
        self.index, self.title, self.hint = index, title, hint
        self.command = command or (lambda: None)
        self.selected = self.hovered = self.focused = False
        self.bind('<Configure>', self._draw)
        self.bind('<Button-1>', self._activate)
        self.bind('<Return>', self._activate)
        self.bind('<space>', self._activate)
        self.bind('<Enter>', lambda _e: self._state('hovered', True))
        self.bind('<Leave>', lambda _e: self._state('hovered', False))
        self.bind('<FocusIn>', lambda _e: self._state('focused', True))
        self.bind('<FocusOut>', lambda _e: self._state('focused', False))

    def _state(self, name, value):
        setattr(self, name, value)
        self._draw()

    def _activate(self, _event=None):
        self.focus_set()
        self.command()
        return 'break'

    def set_selected(self, value):
        self.selected = bool(value)
        self._draw()

    def _draw(self, _event=None):
        self.delete('all')
        width, height = self.winfo_width(), self.winfo_height()
        color = '#373126' if self.selected else '#2b2c30' if self.hovered else SIDE
        _rounded(self, (1, 1, width - 2, height - 2), 9, fill=color,
                 outline=FOCUS if self.focused else '#59503e' if self.selected else color)
        middle = height / 2
        _rounded(self, (10, middle - 14, 38, middle + 14), 6,
                 fill=PRIMARY if self.selected else '#2e3035', outline='')
        label = f'{self.index:02}' if isinstance(self.index, int) else str(self.index)
        self.create_text(24, middle, text=label, font=('Segoe UI', 9, 'bold'),
                         fill=ON_PRIMARY if self.selected else MUTED)
        self.create_text(49, middle - (8 if self.hint else 0), anchor='w', text=self.title,
                         font=('Microsoft YaHei UI', 10, 'bold' if self.selected else 'normal'),
                         fill='#efcf90' if self.selected else '#c4beb2')
        if self.hint:
            self.create_text(49, middle + 12, anchor='w', text=self.hint,
                             font=('Microsoft YaHei UI', 8), fill=MUTED)


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


def apply_glass_controls(root):
    """保留 ttk 语义/键盘/状态绑定，替换小圆角外壳；可重复调用。"""
    style = ttk.Style(root)
    if getattr(root, '_glass_control_images', None):
        return style
    root._glass_control_images = []
    palettes = {
        'TButton': ('#2e3035', LINE, '#393b40', '#202226', TEXT),
        'Primary.TButton': (PRIMARY, PRIMARY, '#e2c58a', '#b99959', ON_PRIMARY),
    }
    for name, (fill, edge, hover, pressed, fg) in palettes.items():
        images = [_control_image(root, color, rim) for color, rim in (
            (fill, edge), (hover, edge), (pressed, edge), ('#34322d', '#4b463d'), (fill, FOCUS))]
        root._glass_control_images.extend(images)
        element = 'Workbench.' + name.replace('.', '_')
        style.element_create(element, 'image', images[0], ('disabled', images[3]),
                             ('pressed', images[2]), ('focus', images[4]), ('active', images[1]),
                             border=8, padding=0, sticky='nsew')
        style.layout(name, [(element, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])
        style.configure(name, background=SURFACE, foreground=fg, padding=(14, 8),
                        font=('Microsoft YaHei UI', 10), anchor='center')
        style.map(name, background=[('disabled', SURFACE), ('pressed', SURFACE), ('active', SURFACE)],
                  foreground=[('disabled', '#8c8474'), ('!disabled', fg)])
    fields = [_control_image(root, color, edge) for color, edge in
              ((INPUT, LINE), (INPUT, FOCUS), ('#292b30', '#4b463d'))]
    root._glass_control_images.extend(fields)
    style.element_create('Workbench.field', 'image', fields[0], ('disabled', fields[2]),
                         ('focus', fields[1]), border=8, padding=0, sticky='nsew')
    style.layout('TEntry', [('Workbench.field', {'sticky': 'nsew', 'children': [
        ('Entry.padding', {'sticky': 'nsew', 'children': [('Entry.textarea', {'sticky': 'nsew'})]})]})])
    style.configure('TEntry', padding=(10, 8), background=SURFACE, fieldbackground=INPUT,
                    foreground=TEXT, insertcolor=TEXT, selectbackground=SELECTION, selectforeground='#efcf90')
    style.map('TEntry', background=[('disabled', SURFACE), ('readonly', SURFACE), ('focus', SURFACE), ('active', SURFACE)],
              fieldbackground=[('disabled', '#292b30'), ('readonly', INPUT)], foreground=[('disabled', '#8c8474')])
    return style
