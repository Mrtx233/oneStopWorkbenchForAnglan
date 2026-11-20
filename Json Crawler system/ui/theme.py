"""工作台配色与字体。暖纸底、墨色导航、绿色主操作。"""
import tkinter.font as tkfont

# 全局主题色常量：build/pages/dialogs/runtime 各处引用，保证配色统一、改色只改这里。
BG = '#f3efe7'                # 暖纸底色，主面板背景
TEXT = '#1c1915'              # 墨色正文
MUTED = '#6f675e'             # 次要说明文字（灰）
LINE = '#ddd4c6'              # 分隔线 / 输入框描边
WHITE = '#fffcf8'             # 输入框、卡片等亮面
SIDE = '#1f1c18'              # 左侧导航栏底色（深墨）
SIDE_HOVER = '#312c26'        # 导航项悬停底色
SIDE_FG = '#e7e1d6'           # 导航项默认文字色
SIDE_ON = '#f3efe7'           # 当前选中导航项底色（与正文区同色，形成高亮块）
SIDE_ON_FG = '#1c1915'        # 当前选中导航项文字色
PRIMARY = '#1f6b4a'           # 主操作绿（开始 / 采集 / 导出按钮、进度条、选中态）
PRIMARY_HOVER = '#174f37'     # 主操作绿悬停 / 描边
DANGER = '#8d3030'            # 危险操作红（停止按钮）
DANGER_HOVER = '#6e2424'      # 危险红悬停 / 描边
LOG_BG = '#1b1916'            # 日志窗口深色背景
LOG_FG = '#e8e2d6'            # 日志窗口文字色
ACCENT = '#1f6b4a'            # 强调色（kicker 小标题），与主绿一致

# 候选字体族：按顺序在系统中探测，匹配到第一个即用；跨 macOS / Windows / Linux 兜底。
UI_CANDIDATES = (
    'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei UI',
    'Noto Sans CJK SC', 'Heiti SC', 'Songti SC',
)
# 等宽字体：日志框、分类输入框用，保证对齐与可读。
MONO_CANDIDATES = ('Menlo', 'SF Mono', 'Consolas', 'Monaco', 'DejaVu Sans Mono')


def choose_font(root, candidates):
    # 从候选列表挑一个本机已安装的字体族；全部缺失时回退 Tk 默认字体，避免启动崩。
    have = set(tkfont.families(root))
    for name in candidates:
        if name in have:
            return name
    return tkfont.nametofont('TkDefaultFont').actual()['family']
