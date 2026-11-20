# ======================== 浏览器工具层 ========================
# 登记为旧模块名 browser_utils；抓 JSON 依赖真实浏览器环境，故用 DrissionPage 而非纯 requests。
from common.browser import create_browser as _create_browser
from app.constants import PROXY_SERVER

PORT_RANGE = (9222, 9322)               # 随机调试端口区间，避开被占用的 Chrome 端口
START_RETRIES = 3                       # 端口启动失败时换端口重试的次数上限


def create_browser(browser_path=None):
    # 创建无痕浏览器实例，随机端口 + 固定本地代理，启动失败自动换端口重试。
    return _create_browser(
        proxy=PROXY_SERVER, port_range=PORT_RANGE, retries=START_RETRIES,
        browser_path=browser_path,
    )
