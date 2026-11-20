# ======================== 浏览器工具层 ========================
# 职责: 封装 DrissionPage Chromium 的创建/关闭，以及在页面上安全执行 JS（带重试与停止检查）。
import json
import time

import config
import logger
from common.browser import create_browser as _create_browser
from common.browser import ContextLostError


def create_browser(
    proxy=config.PROXY_SERVER,
    port_range=config.PORT_RANGE,
    disable_images=config.DISABLE_IMAGES,
    incognito=config.USE_INCOGNITO,
    retries=config.BROWSER_START_RETRIES,
    browser_path=None,
):
    # 阶段 01 的浏览器启动：默认值统一从 config 取，实际逻辑委托 common.browser。
    return _create_browser(
        proxy=proxy,
        port_range=port_range,
        disable_images=disable_images,
        incognito=incognito,
        retries=retries,
        browser_path=browser_path,
    )


def run_js_with_retry(tab, script, default=None, retries=config.JS_DEFAULT_RETRIES, stop_event=None):
    # 在页面上执行 JS，失败按类型退避重试；返回 default 表示放弃（供上层安全取值）
    for attempt in range(retries + 1):
        if stop_event is not None and stop_event.is_set():  # 停止检查点：已请求停止则立即返回默认值
            return default
        try:
            result = tab.run_js(script)
            return default if result is None else result  # 空结果统一回落为 default
        except ContextLostError:
            # 页面导航导致执行上下文丢失：短延时后重试，重试用尽返回 default
            if attempt >= retries:
                return default
            delay = config.JS_CONTEXT_LOST_DELAY
        except Exception as e:
            # 其他 JS 错误：最后一次才打日志，避免刷屏；重试用尽返回 default
            if attempt >= retries:
                logger.log(f"  JavaScript 执行失败: {e}")
                return default
            delay = config.JS_OTHER_ERROR_DELAY
        # 用 stop_event.wait 代替 sleep，停止时能立刻唤醒返回，不用等满延时
        if stop_event is not None:
            if stop_event.wait(delay):
                return default
        else:
            time.sleep(delay)


def get_outer_html(tab, stop_event=None) -> str:  # 取整页 outerHTML，供正则抽取商品链接
    return run_js_with_retry(
        tab, "return document.documentElement.outerHTML;", default="", stop_event=stop_event,
    )


def evaluate_xpath(tab, xpath, stop_event=None):
    # XPath 采集模式：把 XPath 注入浏览器用 document.evaluate 求值，返回文本/href 列表
    return run_js_with_retry(
        tab,
        f"""
        return (() => {{
            const xpath = {json.dumps(xpath)};
            const results = [];
            try {{
                const snapshot = document.evaluate(
                    xpath, document, null,
                    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
                );
                for (let i = 0; i < snapshot.snapshotLength; i++) {{
                    const node = snapshot.snapshotItem(i);
                    const val = node.nodeType === 2 ? node.value : (node.href || node.textContent || '');
                    if (val) results.push(val.trim());
                }}
            }} catch(e) {{
                return {{__xpath_error__: String(e)}};
            }}
            return results;
        }})();
        """,
        default=[],
        stop_event=stop_event,
    )
