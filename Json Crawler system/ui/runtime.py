"""工作台任务启停与日志。"""
from datetime import datetime
from pathlib import Path
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.constants import NAMES, STATUS
from .theme import FOCUS, LINE, LOG_BG, LOG_FG, MUTED, SELECTION_BG, SELECTION_FG, SURFACE, TEXT


class CrawlerRuntime:
    def start(self, stages, action='run'):
        # 启动一轮任务：校验参数 -> 提交 controller 子进程 -> 冻结 UI（禁按钮、置 busy）。
        # action='preview' 时阶段 03 只回预览事件、不落 Excel。
        if self.busy:
            return                        # 一次只允许一个任务，运行中直接忽略再次点击
        try:
            if not stages:
                raise ValueError('请至少勾选一个阶段')
            settings = self.settings()    # dialogs.settings() 做全量校验并拍快照，非法即抛错
            if 1 in stages and not settings['categories']:
                raise ValueError('请先在链接采集页填写分类列表')
            if 6 in stages:
                if not settings['image_csv'] or not Path(settings['image_csv']).is_file():
                    raise ValueError('请选择阶段 04 导出的 WP CSV 文件')
                if not settings['image_wp_site'].startswith('https://'):
                    raise ValueError('请填写以 https:// 开头的目标 WordPress 地址')
                if not settings['image_workers'].isdecimal() or not 1 <= int(settings['image_workers']) <= 50:
                    raise ValueError('图片并发数必须是 1 到 50 之间的整数')
                settings['image_workers'] = int(settings['image_workers'])
            settings['action'] = action
            self.controller.start(stages, settings)  # 只投递给后台线程/子进程，不在此阻塞
        except Exception as exc:
            messagebox.showerror('无法启动', str(exc))  # 校验失败保持 UI 可用，不改状态
            return
        # 走到这里说明子进程已启动：进入 busy 态并锁定本轮快照。
        self.busy = True
        self.active_settings = settings
        self.lock_text.set(self._lock_summary(settings))  # 底栏显示本轮参数
        self.persist_settings(settings)                   # 落盘上次目录与功能开关
        # 禁用所有主操作按钮防止重复提交；仅解禁停止按钮。
        for button in self.buttons:
            button.state(['disabled'])
        self.stop_button.state(['!disabled'])
        self.progress['value'] = 0        # 进度归零
        self.append_log(f'\n[{datetime.now():%H:%M:%S}] 开始任务：{stages}，项目：{settings["project"]}\n')
        self.status.set('启动中')

    def stop(self):
        # 请求停止：置 controller 的停止事件并触碰停止文件，等子进程保存完自然收尾。
        if self.busy:
            self.controller.stop()
            self.status.set('正在停止，等待保存完成…')
            self.stop_button.state(['disabled'])  # 停一次后禁用，避免重复触发

    def append_log(self, text):
        # 追加一行日志：始终写入 self.logs 滚动缓冲（deque maxlen=6000 自动淘汰旧的）；
        # 若日志窗口已打开且存活，才同步写进文本框。必须在 Tk 主线程调用（poll 里调）。
        self.logs.append(text)
        if self.log_window is not None and self.log_window.winfo_exists():
            # 仅在追加前已位于底部时跟随；用户向上翻阅后保留当前位置。
            follow_tail = self.log_text.yview()[1] >= 1.0
            # 文本框平时是 disabled 防误编辑，写入时临时解、写完再锁回去。
            self.log_text.configure(state='normal')
            self.log_text.insert('end', text)
            # 超过 8000 行删掉开头 2000 行，防窗口内存与滚动卡顿（缓冲已由 deque 兜底）。
            if int(self.log_text.index('end-1c').split('.')[0]) > 8000:
                self.log_text.delete('1.0', '2000.0')
            if follow_tail:
                self.log_text.see('end')
            self.log_text.configure(state='disabled')

    def show_logs(self):
        # 打开 / 复现独立日志窗口：已存在就 deiconify+lift，否则新建并从 self.logs 回放历史。
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.deiconify()
            self.log_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.log_window = window
        window.title('运行日志 · Anglan')
        window.geometry('980x620')
        window.minsize(720, 420)
        window.configure(bg=SURFACE)
        # 关窗不销毁、只隐藏(withdraw)：保留缓冲，下次 show_logs 复用同一窗口。
        window.protocol('WM_DELETE_WINDOW', window.withdraw)
        bar = ttk.Frame(window, padding=(24, 16))
        bar.pack(fill='x')
        ttk.Label(bar, text='运行日志', font=(self.ui_family, 18)).pack(side='left')
        ttk.Label(bar, text='本次会话', foreground=MUTED).pack(side='left', padx=(12, 0))
        ttk.Button(bar, text='保存日志', command=self.save_log).pack(side='right')
        ttk.Button(bar, text='清空', command=self.clear_log).pack(side='right', padx=8)
        frame = tk.Frame(window, bg=LOG_BG, highlightthickness=1, highlightbackground=LINE)
        frame.pack(fill='both', expand=True, padx=24, pady=(0, 24))
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side='right', fill='y', padx=(0, 4), pady=4)
        self.log_text = tk.Text(
            frame, bg=LOG_BG, fg=LOG_FG, insertbackground=TEXT,
            font=(self.mono_family, 11), wrap='word', relief='flat', bd=0, padx=16, pady=16,
            highlightthickness=0, yscrollcommand=scrollbar.set,
            selectbackground=SELECTION_BG, selectforeground=SELECTION_FG,
        )
        self.log_text.pack(side='left', fill='both', expand=True)
        self.log_text.bind('<FocusIn>', lambda _e: frame.configure(highlightbackground=FOCUS))
        self.log_text.bind('<FocusOut>', lambda _e: frame.configure(highlightbackground=LINE))
        scrollbar.configure(command=self.log_text.yview)
        self.log_text.insert('end', ''.join(self.logs))  # 回放本次会话已积累的全部日志
        self.log_text.see('end')           # 首次打开查看最新日志，后续滚动由用户控制。
        self.log_text.configure(state='disabled')

    def clear_log(self):
        # 清空：同时清滚动缓冲与可见文本框，二者不再残留旧内容。
        self.logs.clear()
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def save_log(self):
        # 把缓冲内容另存为 .log（UTF-8），失败弹错误框；用户取消对话框时 path 为空即跳过。
        path = filedialog.asksaveasfilename(defaultextension='.log', filetypes=[('日志', '*.log')])
        if path:
            try:
                Path(path).write_text(''.join(self.logs), encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('日志保存失败', str(exc))

    def poll(self):
        # 事件泵：每 100ms 由 root.after 在主线程触发。
        # controller 的后台线程只往 events 队列 put、绝不碰 Tk 控件；这里集中消费并更新 UI，
        # 从而把「子进程线程 -> UI」的跨线程改写收敛回主线程，规避 tkinter 的线程不安全问题。
        # 单轮上限 250 条：防止极端日志量长时间占住主线程导致界面卡死。
        for _ in range(250):
            try:
                event = self.controller.events.get_nowait()
            except queue.Empty:
                break  # 队列排空即退出，等下一次 after 再来看
            kind = event['kind']           # 事件类型由 controller 解析 @@CRAWLER_EVENT@@ JSON 行得到
            if kind == 'log':
                self.append_log(event['text'])
            elif kind == 'stage':
                # 阶段状态变更：回填底栏状态 + 日志（STATUS 把内部码翻成中文）。
                stage = event['stage']
                self.status.set(f'{stage:02d} {NAMES[stage]} · {STATUS.get(event["status"], event["status"])}')
                self.append_log(f'[{stage:02d}] {NAMES[stage]} · {STATUS.get(event["status"], event["status"])}\n')
            elif kind == 'progress':
                # 进度：停止请求已发就不再让 progress 文本覆盖「正在停止」提示。
                if not self.controller.stop_event.is_set():
                    self.status.set(event.get('text', '运行中'))
                # total>0 才换算成百分比（进度条取值 0–100）；否则保持上值。
                if event.get('total'):
                    self.progress['value'] = 100 * event.get('current', 0) / event['total']
            elif kind == 'artifact':
                # 产物落盘：记一行「文本：路径」，供日志里回溯输出文件位置。
                self.append_log(f'{event["text"]}：{event["path"]}\n')
            elif kind == 'stats':
                # 阶段 03 统计：商品数写 stats，维度明细写日志。
                self.stats.set(f'{event["products"]} 个商品')
                self.append_log(f'维度商品数：{event["options"]}；实际值总数：{event["totals"]}\n')
            elif kind == 'preview':
                # 预览：先清空旧行再按列键插入；行数受下游限制（页面说明「最多 200 条」）。
                self.preview.delete(*self.preview.get_children())
                for row in event['rows']:
                    # 按 Treeview 的列顺序取值，缺字段用空串兜底，避免 KeyError。
                    self.preview.insert('', 'end', values=[row.get(c, '') for c in self.preview['columns']])
                self._sync_preview_hint()
                # stats 追加组合数与本次显示条数。
                self.stats.set(self.stats.get() + f' · {event["total"]} 个组合 · 显示 {len(event["rows"])} 条')
                if event['missing']:
                    self.append_log(f'缺失勾选维度的商品：{event["missing"]} 个\n')
            elif kind == 'result' and event.get('message'):
                # 阶段自带结论文案（有 message 才记）。
                self.append_log(event['message'] + '\n')
            elif kind == 'finished':
                # 任务结束：解除 busy 与快照锁定，恢复按钮、禁用停止按钮。
                self.busy = False
                self.active_settings = None
                self.lock_text.set('')
                for button in self.buttons:
                    button.state(['!disabled'])
                self.stop_button.state(['disabled'])
                status = event['status']
                label = STATUS.get(status, status)
                # 失败/部分失败时提示去日志排查。
                self.status.set('任务' + label + (' · 请查看日志' if status in ('failed', 'partial') else ''))
                if status in ('success', 'partial'):
                    self.progress['value'] = 100  # 成功或部分成功都拉满进度条
                if status == 'failed':
                    self.show_logs()              # 整轮失败：自动弹日志窗便于定位
        # 关窗收尾：若用户此前点过关闭且子进程已停，这里安全销毁；否则继续挂 after 轮询。
        if self.closing and not self.controller.running:
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        # WM_DELETE_WINDOW 处理：分「空闲 / 首次请求停止 / 再次请求强退」三种情形，
        # 核心是别在子进程写盘时直接 destroy 导致产物损坏。
        if not self.controller.running:
            self.root.destroy()   # 没有任务在跑，直接退出
            return
        if self.closing:
            # 已在「停止并保存」阶段又点关闭：二次确认后才强杀子进程。
            if messagebox.askyesno('仍要退出', '仍在保存。强制结束可能损坏正在写入的文件，确定退出？'):
                self.status.set('正在强制结束…')
                self.controller.force_stop()
            return
        # 首次点关闭：询问是否停止并等待保存（置 closing=True，由 poll 在子进程退出后销毁窗口）。
        if messagebox.askyesno('停止并退出', '任务正在运行，是否停止并等待保存后退出？'):
            self.closing = True
            self.stop()
            self.status.set('正在停止并保存…再次关闭可强制退出')
