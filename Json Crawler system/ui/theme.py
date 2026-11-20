"""曜石黑金磨砂工作台的共享色板。"""
import tkinter.font as tkfont

BG = '#14161a'
SURFACE = '#24262b'
INPUT_BG = '#1a1c20'
TEXT = '#eeeae2'
MUTED = '#aaa59a'
PLACEHOLDER = '#9c968c'
LINE = '#595248'
SOFT = '#292b30'
RAISED = '#2e3035'
HOVER = '#393b40'
PRESSED = '#202226'
SIDE = '#1d1f24'
SIDE_HOVER = '#2b2c30'
SIDE_FG = '#c4beb2'
SIDE_ON = '#373126'
SIDE_ON_FG = '#efcf90'
PRIMARY = '#d1b06f'
PRIMARY_HOVER = '#e2c58a'
PRIMARY_PRESSED = '#b99959'
PRIMARY_FG = '#191711'
FOCUS = '#edca80'
SELECTION_BG = '#433a29'
SELECTION_FG = '#efcf90'
DISABLED_BG = '#34322d'
DISABLED_FG = '#8c8474'
DANGER = '#e1a292'
DANGER_BG = '#3b2b29'
DANGER_HOVER = '#4a332e'
DANGER_PRESSED = '#583b34'
SCROLL = '#57534b'
SCROLL_HOVER = '#7b705b'
RIM = '#464139'
SHADOWS = ('#101114', '#151619', '#1a1b1e')
LOG_BG = '#17191d'
LOG_FG = '#dcd6ca'
ACCENT = PRIMARY

# 少量暖金和石墨柔光，让浮动面板与窗口背景形成层次。
AMBIENT_BASE = (20, 22, 26)
AMBIENT_CLOUDS = (
    (.05, .10, .28, (90, 73, 43), .28),
    (.78, .12, .36, (56, 59, 65), .32),
    (.88, .92, .33, (87, 66, 37), .24),
    (.28, .85, .30, (47, 49, 55), .25),
)

UI_CANDIDATES = (
    'Microsoft YaHei UI', 'PingFang SC', 'Hiragino Sans GB',
    'Noto Sans CJK SC', 'Heiti SC',
)
MONO_CANDIDATES = ('Cascadia Code', 'Consolas', 'SF Mono', 'Menlo', 'DejaVu Sans Mono')


def choose_font(root, candidates):
    have = set(tkfont.families(root))
    for name in candidates:
        if name in have:
            return name
    return tkfont.nametofont('TkDefaultFont').actual()['family']
