# ======================== 日志层 ========================
# 职责: 采集子进程内的统一日志出口。阶段一在独立子进程内运行，日志经 stdout 由 worker 统一回传，
#       无 GUI sink 场景下直接写真实控制台，保证日志不丢。
import sys
import threading
import traceback

_lock = threading.RLock()            # 保护日志输出，避免多线程并发写时串行
_REAL_STDOUT = sys.stdout            # 保存原始 stdout，作为无 sink 时的落点


def log(msg: str = "") -> None:  # 核心出口：无 sink 时写真实控制台
    text = "" if msg is None else str(msg)
    if not text.endswith("\n"):
        text += "\n"               # 统一补换行，保证每行完整
    with _lock:
        try:
            _REAL_STDOUT.write(text)
        except Exception:
            pass


def log_exc(prefix: str = "") -> None:  # 打印当前异常的完整 traceback，用于吞异常处留痕
    text = traceback.format_exc()
    if prefix:
        text = f"{prefix}{text}"
    log(text.rstrip("\n"))
