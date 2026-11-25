"""临时文件写入后 os.replace。"""
# 阶段产物（链接 JSON、九字段汇总 JSON 等）体积不小且会被反复覆写，
# 直接写目标文件一旦中途崩溃/被强杀就会留下半截 JSON，下次读取即报错。
import os
import tempfile
import time
from pathlib import Path

# Windows 下 os.replace 目标文件被占用（杀毒实时扫描、同步工具、资源管理器索引等）时会抛
# PermissionError [WinError 5]，且属偶发、稍后重试通常即可成功。这里给替换步骤加带退避的重试，
# 避免一次偶发锁冲突就让整个阶段崩溃、丢掉后续所有已采集结果。
_REPLACE_RETRIES = 5          # os.replace 最多尝试次数（含首次）
_REPLACE_RETRY_DELAY = 0.2    # 每次重试前的等待秒数，随次数线性递增


def _replace_with_retry(temporary, target):
    # 反复尝试把临时文件重命名为目标；重试间隔逐步放大，全部失败才抛最后一次的异常。
    last_exc = None
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(temporary, target)
            return
        except PermissionError as exc:
            # 只有「拒绝访问/被占用」这类可自愈错误才值得重试；其余异常直接上抛不拖延。
            last_exc = exc
            if attempt < _REPLACE_RETRIES - 1:
                time.sleep(_REPLACE_RETRY_DELAY * (attempt + 1))
    raise last_exc


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
        _replace_with_retry(temporary, target)   # 同目录重命名，一次到位：读到的永远是完整的旧版或新版
    finally:
        # writer 抛异常时清掉半成品；替换成功后临时文件已不存在，这里自然跳过
        if os.path.exists(temporary):
            os.remove(temporary)
    return target
