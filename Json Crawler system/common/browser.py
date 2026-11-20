# ======================== 浏览器工具层 ========================
# 统一 create_browser：阶段 01/02 共用同一套「随机端口 + 无痕 + 代理 + 重试」逻辑，
# 避免两处复制粘贴导致一处改了另一处忘改。日志走 print，经 stdout 由 worker 回传。
import os
import random
from pathlib import Path

from app.constants import PROXY_SERVER

try:
    from DrissionPage import Chromium, ChromiumOptions
    from DrissionPage.errors import ContextLostError
except ImportError:  # DrissionPage 为可选依赖：缺失时降级，保证上层 except 仍成立
    Chromium = None
    ChromiumOptions = None

    class ContextLostError(Exception):  # 占位异常，使浏览器不可用时上层逻辑不至崩溃
        pass


# 常见的 Chrome / Edge 安装路径候选：按优先级探测，命中存在的第一个即可。
# 新版 Chrome 常驻 LocalAppData 下，Edge 则多在 Program Files；顺序兼顾两者。
_BROWSER_PATH_CANDIDATES = (
    os.environ.get('CHROME_PATH'),                    # 显式环境变量优先
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
)


def find_browser_path(explicit_path=None):
    # 定位浏览器可执行文件：显式传入路径 > 环境变量 > 常见安装路径。
    # 返回首个存在的路径；全部落空返回 None，由上层给出可读报错。
    if explicit_path and Path(explicit_path).is_file():
        return str(explicit_path)
    for candidate in _BROWSER_PATH_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def create_browser(
    proxy=PROXY_SERVER,
    port_range=(9222, 9322),
    disable_images=False,
    incognito=True,
    retries=3,
    browser_path=None,
):
    # 按参数启动 Chromium；端口被占用则换随机端口重试，全失败才抛错。
    # browser_path：浏览器可执行文件路径；未显式给出时自动探测 Chrome/Edge。
    co = ChromiumOptions()
    resolved_path = find_browser_path(browser_path)
    if not resolved_path:
        raise RuntimeError(
            "无法找到浏览器可执行文件路径，请手动配置。"
            "可设置环境变量 CHROME_PATH 或在 user_settings.json 中填写 browser_path。"
        )
    co.set_browser_path(resolved_path)
    if incognito:
        co.incognito(on_off=True)  # 无痕：避免复用旧会话/缓存影响页面结构
    if disable_images:
        co.set_argument("--blink-settings=imagesEnabled=false")  # 禁图提速
    if proxy:
        co.set_argument(f"--proxy-server={proxy}")  # 走本地代理；传 None 即直连
    low, high = port_range
    random_port = random.randint(low, high)  # 随机调试端口，规避多任务/残留进程端口冲突
    co.set_local_port(random_port)
    for attempt in range(retries):
        try:
            chrome = Chromium(co)
            print(f"浏览器启动成功，端口: {random_port}")
            return chrome
        except Exception as e:
            # 启动失败多为端口占用：记录后换一个随机端口再试
            print(f"端口 {random_port} 启动失败 (尝试 {attempt + 1}/{retries}): {e}")
            random_port = random.randint(low, high)
            co.set_local_port(random_port)
    raise RuntimeError("无法启动浏览器，已重试多次")
