"""采集工作台的石墨灰和暖金色板。"""
import tkinter.font as tkfont

BG = '#191a1c'
SIDE = BG
SURFACE = '#222325'
INPUT_BG = '#1a1b1d'
SOFT = '#292a2d'
RAISED = '#2d2e31'
HOVER = '#36373b'
PRESSED = '#252628'
LINE = '#3a3b3e'
TEXT = '#edeeef'
MUTED = '#acadaf'
PLACEHOLDER = '#8b8e93'
PRIMARY = '#d9b77c'
PRIMARY_HOVER = '#e5c895'
PRIMARY_PRESSED = '#c4a46e'
PRIMARY_FG = '#251d12'
FOCUS = '#e5c895'
SELECTION_BG = '#3c382f'
SELECTION_FG = '#f0dfc1'
DISABLED_BG = '#2b2c2f'
DISABLED_FG = '#909296'
DANGER = '#e6aaa2'
DANGER_BG = '#392b2b'
DANGER_HOVER = '#493330'
DANGER_PRESSED = '#512f2d'
SCROLL = '#55565a'
SCROLL_HOVER = '#717277'
LOG_BG = INPUT_BG
LOG_FG = TEXT

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
