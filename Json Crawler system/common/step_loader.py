"""按文件路径加载数字前缀步骤模块（文件名可 10_xxx.py）。"""
# 阶段脚本用 00/10/…/99 前缀保证排序，而 Python 不允许 import 以数字命名的模块，
# 所以这些文件只能由本模块按完整路径加载。
import importlib.util
import sys
from pathlib import Path


def load_step(path):
    path = Path(path)
    # 合成模块名带上父目录（阶段）名：各阶段存在同名文件（如 80_logger.py），
    # 只用文件名会让 01 与 02 的 logger 在 sys.modules 里互相顶掉。
    name = f'_step_{path.parent.name}_{path.stem}'
    if name in sys.modules:
        return sys.modules[name]     # 命中缓存：同一阶段内多处加载得到同一个模块实例，
                                     # 否则重复执行模块体，改过的配置值会看不到
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        # 文件不存在或扩展名不是 Python：明确报错，别让调用方拿到 None 之后一头雾水
        raise ImportError(f'无法加载步骤：{path}')
    module = importlib.util.module_from_spec(spec)
    # 必须先登记进 sys.modules 再执行：步骤模块内部若再引用自身/兄弟模块，
    # 否则会在 exec 过程中重复创建半成品模块。
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def alias_step(alias, path):
    """加载前缀文件，并登记成旧模块名（如 config），供步骤内部 import。"""
    module = load_step(path)
    # 步骤代码沿用 05 时代的裸名写法（import config / import logger），
    # 这里把前缀文件挂到旧名上它们才找得到；每个子进程只加载一个阶段，
    # 所以不同阶段的 config 不会串味（见 worker.py 的 STAGES 说明）。
    sys.modules[alias] = module
    return module
