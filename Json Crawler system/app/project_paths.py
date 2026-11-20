"""项目目录默认值。"""
# 环境变量 + 上次运行记录 + 仓库内约定目录，三者共同推断首次启动时的默认项目目录。
import os
from pathlib import Path

from .user_settings import ROOT, load_user_settings

# ROOT 是项目目录（在 user_settings.py 里定义），其父目录即仓库根
REPO = ROOT.parent


def default_project_dir():
    # 回退优先级：环境变量 → 上次使用的项目 → 仓库 ANG_OUTPUT_XLSX → 仓库根。
    # 越靠前的越尊重用户显式意图，越靠后越是「总能得到一个可写目录」的兜底。
    env = os.environ.get('ANGLAN_PROJECT_DIR', '').strip()
    if env:
        return env               # 命令行/多项目切换用的显式指定，优先级最高
    saved = load_user_settings().get('last_project', '').strip()
    if saved and Path(saved).exists():
        return saved             # 上次目录可能已被移动或删除，必须验证存在再用
    output = REPO / 'ANG_OUTPUT_XLSX'
    if output.is_dir():
        return str(output)       # 仓库自带的输出目录约定，作为开箱可用的默认
    return str(REPO)             # 最后兜底仓库根，保证界面里不会出现空路径
