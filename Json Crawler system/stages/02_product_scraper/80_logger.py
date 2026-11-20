# ======================== 日志层 ========================
# 登记为旧模块名 logger：阶段二在独立子进程内运行，日志经 stdout 由 worker 统一回传，
# 无需 GUI sink 或 tkinter 重定向，仅保留异常回溯打印能力。


def log_exc(prefix=""):
    # 打印当前异常回溯（可选前缀），便于在日志里定位堆栈。
    import traceback
    text = traceback.format_exc()
    if prefix:
        text = f"{prefix}{text}"
    print(text.rstrip("\n"))
