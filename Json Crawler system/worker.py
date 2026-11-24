"""一个子进程只加载一个阶段，避免同名模块冲突。"""
# 本文件由 controller 以 `python -u worker.py <阶段号> <停止文件>` 启动，只做三件事：
# 读 settings、加载该阶段入口、把事件行写回 stdout。
import json
from pathlib import Path
import sys
import threading
import traceback

# 本文件由 controller 以「python -u worker.py …」在项目根目录下启动，脚本所在目录即 sys.path[0]，
# 所以这里能直接 import app 包；事件前缀与 controller 共用同一份定义，不再各写字面值。
from app.constants import PREFIX

# 阶段号 → 阶段目录名；一次运行只加载其中一个目录，
# 因此各阶段自有的 config / logger 等同名模块不会互相污染。
STAGES = {
    1: '01_link_collector',
    2: '02_product_scraper',
    3: '03_data_analysis',
    4: '04_price_export',
    5: '03_1_split',
    6: '04_1_image_downloader',
}


def emit(kind, **values):
    # 跨进程协议：一行「前缀 + 单行 JSON」；controller 逐行解析后回灌 UI（进度、产物、日志、预览）。
    # flush 保证进度即时可见，即使子进程忘了设无缓冲也不会卡在管道里。
    print(PREFIX + json.dumps({'kind': kind, **values}, ensure_ascii=False), flush=True)


def main():
    # settings 从 stdin 读一行（父进程写完后立刻关闭，readline 即得 EOF，不会阻塞）
    settings = json.loads(sys.stdin.readline())
    stage = int(sys.argv[1])
    stop = threading.Event()      # 交给阶段 run() 的停止信号
    finished = threading.Event()  # 主流程结束标记，用于让轮询线程退出
    stop_path = Path(sys.argv[2]) # 父进程 stop() 时 touch 的文件

    def listen():
        # 停止靠「文件是否存在」跨进程传递：每 0.1 秒看一次；
        # wait(0.1) 兼作休眠，任务一结束就退出轮询，不遗留线程。
        while not finished.wait(0.1):
            if stop_path.exists():
                stop.set()
                return

    listener = threading.Thread(target=listen, daemon=True)
    listener.start()
    # sys.path 顺序决定同名文件的归属：先项目根目录（找得到 common / app / url_utils），
    # 再把当前阶段目录放最前，让阶段内 `import config` 等裸名优先命中本阶段版本。
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'stages' / STAGES[stage]))
    try:
        folder = root / 'stages' / STAGES[stage]
        # 数字前缀不是合法模块名，不能 import，必须按路径加载（见 README 的 step_loader 说明）；
        # 入口文件缺失时 load_step 自己抛带路径的 ImportError，不需要在这里先探测存在性。
        from common.step_loader import load_step
        outcome = load_step(folder / '99_pipeline_entry.py').run(settings, stop, emit)
        outcome = 'stopped' if stop.is_set() else (outcome or 'success')
        if outcome not in ('success', 'partial', 'failed', 'stopped'):
            raise ValueError(f'未知阶段结果：{outcome}')
        emit('result', status=outcome)
        # 退出码约定：0=成功，3=部分失败，2=被停止，1=失败；controller 会结合 result 事件一起判定
        return {'success': 0, 'partial': 3, 'failed': 1, 'stopped': 2}[outcome]
    except BaseException as exc:
        # 捕获 BaseException：浏览器/DrissionPage 异常退出时可能抛非 Exception 子类，
        # 也必须转成 failed 事件回传，否则 UI 会一直停在「运行中」。
        traceback.print_exc()
        emit('result', status='stopped' if stop.is_set() else 'failed', message=str(exc))
        return 2 if stop.is_set() else 1
    finally:
        finished.set()    # 通知 listen 线程收工
        listener.join()   # 等它退出，让解释器干净结束（daemon 只是兜底）


if __name__ == '__main__':
    # 把 main() 的返回值作为进程退出码，controller 的 process.wait() 读到的就是它
    raise SystemExit(main())
