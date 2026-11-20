# -*- coding: utf-8 -*-
"""商品数据转换工具入口（薄壳）。

实际实现已拆分到 switch_tool 包（本目录）：
  - gui.py              主 GUI 框架（一个 GUI）
  - features/*.py       八个独立功能文件
  - constants.py        常量
  - utils.py            通用工具

保持本文件名不变，双击 / `python switch_gui.py` 均可启动。
"""

import sys
from pathlib import Path

# 入口位于包内（Utils/switch_tool/），双击运行时工作目录是本目录，
# 需把包父目录（Utils/）加进 sys.path，才能以包形式导入 switch_tool。
_here = Path(__file__).resolve().parent
if str(_here.parent) not in sys.path:
    sys.path.insert(0, str(_here.parent))

from switch_tool.gui import main

if __name__ == "__main__":
    main()
