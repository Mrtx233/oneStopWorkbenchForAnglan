"""GUI 无关的串行调度器；后台线程不接触 Tk 控件。"""
# 只用标准库：设置走 JSON 序列化，阶段跑 subprocess，回传给 UI 的信息走 queue.Queue。
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

# 事件行前缀与 worker.emit 共用同一份定义，避免两侧字面值各写一遍后走岔。
from app.constants import PREFIX

FORCE_WAIT_SECONDS = 10        # 强制停止时先等 10 秒，给阶段自己把 JSON / xlsx 落盘
KILL_WAIT_SECONDS = 3          # terminate 之后最多再等 3 秒，仍不退才 kill（强杀会丢未落盘产物）


class Controller:
    def __init__(self, python=None):
        # python 默认沿用当前解释器；GUI 常由 pythonw.exe 启动（无控制台），
        # 用它跑子进程会丢 stdout 管道，所以换成同目录下的 python.exe。
        self.python = python or sys.executable
        if Path(self.python).name.lower() == 'pythonw.exe':
            self.python = str(Path(self.python).with_name('python.exe'))
        self.events = queue.Queue()          # 事件出口：后台线程只 put，UI 主线程定时 get 后改控件
        self.stop_event = threading.Event()  # UI 线程 → 调度线程的软停止信号
        self.thread = None                   # 调度线程（_run），存活即代表「有任务在跑」
        self.process = None                  # 当前阶段子进程，读写都要持 lock
        self.stop_path = None                # 当前阶段的停止文件路径（跨进程停止的载体）
        self.lock = threading.Lock()         # 保护 process / stop_path：stop 与 _run 会并发访问

    @property
    def running(self):
        # 以调度线程是否存活判定忙闲：阶段串行执行，线程在跑就说明有子进程或正在收尾
        return self.thread is not None and self.thread.is_alive()

    def start(self, stages, settings):
        if self.running:
            # 不允许并行任务：两个进程写同一份域名 CSV 会互相覆盖
            raise RuntimeError('已有任务正在运行')
        self.stop_event.clear()
        # 深拷贝设置快照：后台线程稍后读取时，UI 里的输入框可能已被用户改动
        snapshot = json.loads(json.dumps(settings))
        # daemon 线程：窗口被关闭时不阻止进程退出
        self.thread = threading.Thread(target=self._run, args=(list(stages), snapshot), daemon=True)
        self.thread.start()

    def stop(self):
        # 软停止：置事件 + 落停止文件，让阶段自己保存产物后正常收尾（不丢数据）
        self.stop_event.set()
        with self.lock:
            if self.stop_path is not None:
                try:
                    self.stop_path.touch()   # worker 的轮询线程见到该文件就 set 它的 stop 事件
                except OSError as exc:
                    # 临时目录可能已被系统回收：不能静默失败，否则用户以为已经停了
                    self.events.put({'kind': 'log', 'text': f'发送停止请求失败：{exc}\n'})

    def force_stop(self):
        # 硬停止分三步：先软停止请求保存 → 等 10 秒 → terminate → 再等 3 秒 → kill
        self.stop()
        process = None
        with self.lock:
            process = self.process   # 取当前子进程快照，可能已经切换到下一阶段或已结束
        if process is None or process.poll() is not None:
            return                   # 没有活着的子进程，无需强杀
        deadline = time.time() + FORCE_WAIT_SECONDS
        while time.time() < deadline:
            if process.poll() is not None:
                return               # 10 秒内自行退出：产物已保存，属于理想情况
            time.sleep(0.2)          # 轮询间隔：够快响应，又不至于占 CPU
        self.events.put({'kind': 'log', 'text': '保存等待超时，正在强制结束子进程…\n'})
        try:
            process.terminate()      # 温和的结束请求，浏览器等子进程还可能自行清理
        except OSError as exc:
            self.events.put({'kind': 'log', 'text': f'结束进程失败：{exc}\n'})
            return
        kill_deadline = time.time() + KILL_WAIT_SECONDS
        while time.time() < kill_deadline:
            if process.poll() is not None:
                return               # terminate 已生效，不必强杀
            time.sleep(0.2)
        try:
            process.kill()           # 最后手段：立即杀死，接受产物可能不完整
        except OSError as exc:
            self.events.put({'kind': 'log', 'text': f'强制结束失败：{exc}\n'})

    def _run(self, stages, settings):
        # 后台调度线程主体：按顺序为每个阶段起一个 worker.py 子进程并转发其事件。
        # 界面每次只提交单个阶段，串行循环仅用于兼容多阶段入参，阶段失败即中止。
        outcome = 'success'
        failed_stages = []
        # 停止文件放在本次任务的临时目录里，退出时整体删除；
        # 若放项目目录，残留的停止文件会让下一次运行刚开始就被停掉。
        temporary = tempfile.TemporaryDirectory(prefix='json-crawler-')
        try:
            for stage in stages:
                if self.stop_event.is_set():
                    # 阶段之间也要检查停止：未启动的阶段不再启动
                    outcome = 'stopped'
                    break
                self.events.put({'kind': 'stage', 'stage': stage, 'status': 'running'})
                environment = os.environ.copy()
                environment['PYTHONIOENCODING'] = 'utf-8'   # 子进程中文日志按 UTF-8 出，避免乱码
                environment['PYTHONUNBUFFERED'] = '1'       # 事件行立刻刷出来，进度条才跟得上
                with self.lock:
                    # 每个阶段一个独立停止文件：上一阶段的停止标记不会误伤本阶段
                    self.stop_path = Path(temporary.name) / f'stop-{stage}'
                # 子进程命令行：python -u worker.py <阶段号> <停止文件路径>；
                # cwd 固定为项目根目录，保证 worker 与阶段脚本的相对路径稳定。
                # stderr 并入 stdout，traceback 也能作为日志行回到 GUI。
                popen_kwargs = dict(
                    args=[self.python, '-u', str(Path(__file__).with_name('worker.py')), str(stage), str(self.stop_path)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace', env=environment,
                    cwd=str(Path(__file__).resolve().parent),
                )
                if os.name == 'nt':
                    # Windows 下不弹控制台黑窗（GUI 程序启动子进程的常规处理）
                    popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                process = subprocess.Popen(**popen_kwargs)
                with self.lock:
                    self.process = process
                    # settings 用单行 JSON 走 stdin：argv 长度受限且路径含中文/空格时更易出错；
                    # ensure_ascii=False 让子进程读到的仍是可读中文。
                    process.stdin.write(json.dumps(settings, ensure_ascii=False) + '\n')
                    process.stdin.close()   # 关闭写端，worker 的 readline 才能立刻拿到完整行
                    if self.stop_event.is_set():
                        # 竞态兜底：子进程刚起来用户就点了停止，这里补一次标记
                        self.stop_path.touch()
                result = None
                # 逐行读取子进程输出，区分「事件行」与「普通日志行」
                for line in process.stdout:
                    if line.startswith(PREFIX):
                        try:
                            event = json.loads(line[len(PREFIX):])   # 前缀之后是单行 JSON 事件
                        except json.JSONDecodeError:
                            # 事件行被截断/污染时降级为日志，绝不让调度线程因此崩溃
                            event = {'kind': 'log', 'text': line}
                        if event['kind'] == 'result':
                            result = event.get('status')   # 暂存阶段自报结果，进程结束后再判定
                        event['stage'] = stage             # 补阶段号，UI 才知道刷新哪一页
                        self.events.put(event)
                    else:
                        # 非事件行（print 输出、traceback）原样包成日志事件
                        self.events.put({'kind': 'log', 'stage': stage, 'text': line})
                code = process.wait()
                process.stdout.close()
                with self.lock:
                    self.process = None
                    self.stop_path = None   # 置空后 stop() 只置事件，不会再 touch 已失效路径
                # 成功要求两个条件同时成立：退出码 0 且子进程自报 success
                # （例如「一条数据都没采到」时阶段可以自报 failed，即便进程没崩）
                status = 'stopped' if self.stop_event.is_set() else (
                    'success' if code == 0 and result == 'success' else
                    'partial' if code == 3 and result == 'partial' else 'failed')
                self.events.put({'kind': 'stage', 'stage': stage, 'status': status})
                if status == 'stopped':
                    outcome = 'stopped'
                    break                   # 用户停止优先于容错，剩余阶段不再跑
                if status != 'success':
                    failed_stages.append(stage)
                    outcome = status
                    break                   # 阶段失败即中止，不继续后续阶段
        except Exception as exc:
            # 起进程或管道通信本身失败（解释器路径无效、阶段目录被移动等）
            outcome = 'failed'
            self.events.put({'kind': 'log', 'text': f'任务启动或通信失败：{exc}\n'})
        finally:
            # 无论成功失败都要收尾：清理状态 + 发出唯一的 finished 终结事件
            with self.lock:
                self.stop_path = None
            temporary.cleanup()
            # outcome 已在循环里按阶段结果定妥：阶段一旦非 success 就 append + break，
            # 所以「failed_stages 非空而 outcome 仍是 success」这种组合不会出现，无需二次归并。
            # failed_stages 一并带上，UI 才能提示「哪些阶段需要重跑」
            self.events.put({'kind': 'finished', 'status': outcome, 'failed_stages': failed_stages})
