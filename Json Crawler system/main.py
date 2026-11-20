"""Anglan 采集工作台启动入口（重构目录）。"""
# 入口只负责开窗，界面逻辑在 ui/，调度逻辑在 controller.py，采集在 stages/（子进程里跑）。
import tkinter as tk

from ui.app import CrawlerApp


if __name__ == "__main__":
    # 直接运行本文件才启动 GUI；被 import 时不弹窗，方便单测与复用。
    app_root = tk.Tk()
    # CrawlerApp 自己搭界面并创建 Controller；Controller 的后台线程只写事件队列，
    # 由 CrawlerApp 在主线程消费，GUI 线程从不直接执行采集。
    CrawlerApp(app_root)
    app_root.mainloop()
