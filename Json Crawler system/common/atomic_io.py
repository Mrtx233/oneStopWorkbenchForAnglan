"""临时文件写入后 os.replace。"""
# 阶段产物（链接 JSON、九字段汇总 JSON 等）体积不小且会被反复覆写，
# 直接写目标文件一旦中途崩溃/被强杀就会留下半截 JSON，下次读取即报错。
import os
import tempfile
from pathlib import Path


def replace_file(target, writer, suffix):
    # 用法：把写内容的动作交给 writer（它收到临时文件路径），成功后整份替换到 target。
    # suffix 由调用方指定真实扩展名（.json / .xlsx），让 openpyxl、pandas 按扩展名选对写入器。
    target = Path(target)
    # 目标父目录（Json/Data Analysis、CSV）可能还不存在，写之前先补出来
    target.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件必须落在目标同一目录：跨分区时 os.replace 可能不是原子操作甚至直接失败。
    # 前缀取 ".{文件名}_"，是隐藏式命名，避免被阶段脚本当成数据文件扫到。
    fd, temporary = tempfile.mkstemp(prefix=f'.{target.stem}_', suffix=suffix, dir=target.parent)
    # mkstemp 返回的句柄这里用不上（writer 需要的是路径字符串），当场关掉避免句柄泄漏
    os.close(fd)
    try:
        writer(temporary)
        os.replace(temporary, target)   # 同目录重命名，一次到位：读到的永远是完整的旧版或新版
    finally:
        # writer 抛异常时清掉半成品；替换成功后临时文件已不存在，这里自然跳过
        if os.path.exists(temporary):
            os.remove(temporary)
    return target
