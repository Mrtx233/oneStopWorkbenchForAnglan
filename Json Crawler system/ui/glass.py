"""纯 Tk 的柔光背景、磨砂面板与圆角素材，不依赖平台透明窗口接口。"""
import math
import struct
import tkinter as tk
import zlib

from .theme import (
    AMBIENT_BASE, AMBIENT_CLOUDS, BG, DISABLED_BG, DISABLED_FG, FOCUS,
    INPUT_BG, LINE, MUTED, PRIMARY, PRIMARY_FG, RAISED, RIM, SHADOWS,
    SIDE, SIDE_FG, SIDE_HOVER, SIDE_ON, SIDE_ON_FG, SOFT, SURFACE,
)


def rounded_rect(canvas, x1, y1, x2, y2, radius=16, **kwargs):
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    return canvas.create_polygon(
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        smooth=True, splinesteps=24, **kwargs,
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


class AmbientBackground(tk.Canvas):
    """低分辨率生成柔焦光晕，缩放后缓存；仅在窗口尺寸改变时重绘。"""
    def __init__(self, master):
        super().__init__(master, bg=BG, bd=0, highlightthickness=0)
        self.photo = None
        self._render_job = None
        self.surfaces = []
        self.bind('<Configure>', self._schedule_render)

    def _schedule_render(self, _event=None):
        if self._render_job is not None:
            self.after_cancel(self._render_job)
        self._render_job = self.after(90, self._render)

    def _render(self):
        self._render_job = None
        scale = 5
        width = max(1, math.ceil(self.winfo_width() / scale))
        height = max(1, math.ceil(self.winfo_height() / scale))
        pixels = bytearray()
        for y in range(height):
            ny = y / height
            for x in range(width):
                nx = x / width
                color = list(AMBIENT_BASE)
                for cx, cy, spread, tint, opacity in AMBIENT_CLOUDS:
                    alpha = opacity * math.exp(-((nx - cx) ** 2 + (ny - cy) ** 2) / (2 * spread ** 2))
                    color = [v * (1 - alpha) + t * alpha for v, t in zip(color, tint)]
                pixels.extend(int(v) for v in color)
        small = tk.PhotoImage(master=self, data=f'P6\n{width} {height}\n255\n'.encode() + pixels, format='PPM')
        self.photo = small.zoom(scale)
        self.delete('ambient')
        self.create_image(0, 0, image=self.photo, anchor='nw', tags='ambient')
        self.tag_lower('ambient')
        for surface in self.surfaces:
            surface.redraw()


class GlassCard(tk.Canvas):
    """浮层的背景沿用主画布，亮边和柔和投影围出磨砂内容区。"""
    def __init__(self, master, *, padding=22, fill=SURFACE):
        super().__init__(master, bg=BG, bd=0, highlightthickness=0)
        self.ambient = master
        self.fill = fill
        self.padding = padding
        self._crop = None
        self.content = tk.Frame(self, bg=fill, bd=0)
        master.surfaces.append(self)
        self.bind('<Configure>', self.redraw)

    def redraw(self, _event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 20 or height < 20:
            return
        self.delete('surface')
        source = self.ambient.photo
        if source is not None:
            x, y = max(0, self.winfo_x()), max(0, self.winfo_y())
            crop_width = min(width, source.width() - x)
            crop_height = min(height, source.height() - y)
            if crop_width > 0 and crop_height > 0:
                self._crop = tk.PhotoImage(master=self, width=width, height=height)
                self._crop.tk.call(str(self._crop), 'copy', str(source),
                                   '-from', x, y, x + crop_width, y + crop_height, '-to', 0, 0)
                self.create_image(0, 0, image=self._crop, anchor='nw', tags='surface')
        for (inset, offset), shade in zip(((0, 6), (2, 4), (3, 2)), SHADOWS):
            rounded_rect(self, 4 - inset, 5 + offset, width - 5 + inset, height - 7 + offset,
                         radius=21, fill=shade, outline='', tags='surface')
        rounded_rect(self, 4, 3, width - 5, height - 9, radius=20,
                     fill=self.fill, outline=RIM, width=1.2, tags='surface')
        self.tag_lower('surface')
        pad = self.padding
        self.content.place(x=4 + pad, y=3 + pad,
                           width=max(1, width - 9 - pad * 2),
                           height=max(1, height - 12 - pad * 2))


class NavItem(tk.Canvas):
    def __init__(self, master, index, title, hint, family, command):
        super().__init__(master, bg=SIDE, bd=0, highlightthickness=0,
                         height=70, width=170, cursor='hand2', takefocus=True)
        self.index, self.title, self.hint = index, title, hint
        self.family, self.command = family, command
        self.selected = self.hovered = self.focused = False
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda _e: self._hover(True))
        self.bind('<Leave>', lambda _e: self._hover(False))
        self.bind('<FocusIn>', lambda _e: self._focus(True))
        self.bind('<FocusOut>', lambda _e: self._focus(False))
        self.bind('<Button-1>', lambda _e: self._activate())
        self.bind('<Return>', lambda _e: self.command())
        self.bind('<space>', lambda _e: self.command())

    def _activate(self):
        self.focus_set()
        self.command()

    def _hover(self, value):
        self.hovered = value
        self._draw()

    def _focus(self, value):
        self.focused = value
        self._draw()

    def set_selected(self, value):
        self.selected = value
        self._draw()

    def _draw(self, _event=None):
        self.delete('all')
        width = self.winfo_width()
        color = SIDE_ON if self.selected else SIDE_HOVER if self.hovered else SIDE
        rounded_rect(self, 1, 2, width - 2, 67, 12, fill=color,
                     outline=FOCUS if self.focused else RIM if self.selected else color)
        rounded_rect(self, 12, 18, 43, 49, 9, fill=PRIMARY if self.selected else RAISED, outline='')
        self.create_text(28, 34, text=f'{self.index:02}', font=(self.family, 10, 'bold'),
                         fill=PRIMARY_FG if self.selected else MUTED)
        self.create_text(54, 25, text=self.title, anchor='w',
                         font=(self.family, 11, 'bold' if self.selected else 'normal'),
                         fill=SIDE_ON_FG if self.selected else SIDE_FG)
        self.create_text(54, 46, text=self.hint, anchor='w', font=(self.family, 9), fill=MUTED)
