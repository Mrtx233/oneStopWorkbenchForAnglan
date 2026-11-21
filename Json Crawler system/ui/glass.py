"""Tk 控件素材与阶段导航。"""
import math
import struct
import tkinter as tk
import zlib

from .theme import (
    DISABLED_BG, DISABLED_FG, FOCUS, HOVER, INPUT_BG, LINE, MUTED,
    PRIMARY, PRIMARY_FG, RAISED, SIDE, SOFT, SURFACE, TEXT,
)


# 圆角必须完全落在九宫格固定区内，否则拉伸区会把弧线带到直边上。
CONTROL_RADIUS = 6
CONTROL_SLICE = CONTROL_RADIUS + 2
CONTROL_IMAGE_SIZE = CONTROL_SLICE * 3


def rounded_image(master, fill, outline):
    """生成等厚描边的 RGBA 圆角素材，透明度超采样保持边缘平滑。"""
    size, radius = CONTROL_IMAGE_SIZE, CONTROL_RADIUS
    fill_rgb, edge_rgb = (
        tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        for color in (fill, outline)
    )
    pixels = bytearray()
    middle = size / 2
    offsets = (0.125, 0.375, 0.625, 0.875)
    for y in range(size):
        pixels.append(0)  # PNG 每行的过滤类型：不作差分。
        for x in range(size):
            samples = []
            for oy in offsets:
                for ox in offsets:
                    qx = abs(x + ox - middle) - (middle - radius)
                    qy = abs(y + oy - middle) - (middle - radius)
                    distance = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius
                    if distance <= 0:
                        samples.append(edge_rgb if distance > -1 else fill_rgb)
            if samples:
                pixels.extend(round(sum(color[c] for color in samples) / len(samples)) for c in range(3))
                pixels.append(round(255 * len(samples) / 16))
            else:
                pixels.extend((0, 0, 0, 0))

    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data
                + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('!2I5B', size, size, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))
    return tk.PhotoImage(master=master, data=png, format='png')


def indicator_image(master, *, kind='check', selected=False, disabled=False, focused=False, size=18, gap=6):
    """复选/单选图标；右侧透明留白维持标签间距，图形边缘用采样柔化。"""
    image = tk.PhotoImage(master=master, width=size + gap, height=size)
    fill = DISABLED_BG if disabled and selected else PRIMARY if selected else SOFT if disabled else INPUT_BG
    edge = LINE if disabled else FOCUS if focused else PRIMARY if selected else LINE
    mark = DISABLED_FG if disabled else PRIMARY_FG
    if kind == 'radio':
        fill = SOFT if disabled else INPUT_BG
        mark = DISABLED_FG if disabled else PRIMARY
    def rgb(color):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    background, fill_rgb, edge_rgb, mark_rgb = map(rgb, (SURFACE, fill, edge, mark))
    middle = size / 2
    def shape_distance(x, y):
        if kind == 'radio':
            return math.hypot(x - middle, y - middle) - (middle - 1)
        qx, qy = abs(x - middle) - (middle - 5), abs(y - middle) - (middle - 5)
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - 4
    def segment_distance(x, y, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0, min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
    for y in range(size):
        for x in range(size):
            samples = []
            for sy in (1 / 6, 1 / 2, 5 / 6):
                for sx in (1 / 6, 1 / 2, 5 / 6):
                    px, py = x + sx, y + sy
                    distance = shape_distance(px, py)
                    color = background if distance > 0 else edge_rgb if distance > -(1.7 if focused else 1) else fill_rgb
                    if selected and distance <= -1:
                        if kind == 'radio':
                            if math.hypot(px - middle, py - middle) < 3.2:
                                color = mark_rgb
                        elif min(segment_distance(px, py, (4.8, 8.8), (7.6, 11.6)),
                                 segment_distance(px, py, (7.6, 11.6), (13.2, 6.0))) < 1.05:
                            color = mark_rgb
                    samples.append(color)
            if all(color == background for color in samples):
                continue
            color = tuple(round(sum(sample[channel] for sample in samples) / len(samples)) for channel in range(3))
            image.put('#%02x%02x%02x' % color, (x, y))
    return image


class NavItem(tk.Canvas):
    def __init__(self, master, index, title, family, mono_family, command):
        super().__init__(master, bg=SIDE, bd=0, highlightthickness=0,
                         width=168, height=36, cursor='hand2', takefocus=True)
        self.index, self.title = index, title
        self.family, self.mono_family, self.command = family, mono_family, command
        self.selected = self.hovered = self.focused = False
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda _e: self._set_hover(True))
        self.bind('<Leave>', lambda _e: self._set_hover(False))
        self.bind('<FocusIn>', lambda _e: self._set_focus(True))
        self.bind('<FocusOut>', lambda _e: self._set_focus(False))
        self.bind('<Button-1>', self._activate)
        self.bind('<Return>', self._activate)
        self.bind('<space>', self._activate)

    def _activate(self, _event):
        self.focus_set()
        self.command()
        return 'break'

    def _set_hover(self, value):
        self.hovered = value
        self._draw()

    def _set_focus(self, value):
        self.focused = value
        self._draw()

    def set_selected(self, value):
        self.selected = value
        self._draw()

    def _draw(self, _event=None):
        self.delete('all')
        width = self.winfo_width()
        if width <= 2:
            return
        bg = RAISED if self.selected else SOFT if self.hovered else SIDE
        outline = FOCUS if self.focused else HOVER if self.selected else bg
        self.create_rectangle(1, 1, width - 1, 35, fill=bg, outline=outline)
        if self.selected:
            self.create_rectangle(2, 8, 4, 28, fill=PRIMARY, outline='')
        self.create_text(12, 18, text=f'{self.index:02}', anchor='w',
                         font=(self.mono_family, 10), fill=PRIMARY if self.selected else MUTED)
        self.create_text(40, 18, text=self.title, anchor='w', font=(self.family, 11), fill=TEXT)
