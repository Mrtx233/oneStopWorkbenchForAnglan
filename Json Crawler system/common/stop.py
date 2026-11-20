"""停止检查。"""


def stopped(stop):
    # 阶段脚本里的 stop 是跨线程/跨进程传入的 threading.Event，可能为 None
    # （命令行直接跑阶段时没有停止控件），故先判空再取标志位。
    return stop is not None and stop.is_set()
