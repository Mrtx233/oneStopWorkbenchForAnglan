# ======================== 采集核心层 ========================
#
# 职责: 分页采集业务逻辑。含分类文本解析、分页 URL 构造、
#       链接提取（HTML 正则 / XPath 两种模式）、采集主循环。
# 依赖: config、logger、browser_utils、file_utils。
# 禁止: 导入 tkinter。
# ========================================================

import json
import re
import threading
import time
from html import unescape
from typing import Callable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import browser_utils
import config
import file_utils
import logger
from url_utils import normalize_request_url

ContextLostError = browser_utils.ContextLostError  # 复用浏览器层的上下文丢失异常类型，供 except 捕获

ProgressCallback = Callable[[int, int, str], None]  # (当前序号, 总数, 分类标题) → 更新进度条
CountCallback = Callable[[int], None]                # (累计链接数) → 更新“已采集 N 条”


def parse_categories(text: str) -> List[config.CategoryItem]:
    # 把用户在文本框粘贴的多行内容解析为分类项，容忍纯 URL / JSON 风格 / "标题: url" 等写法
    raw = (text or "").strip()
    if not raw:
        return []

    categories: List[config.CategoryItem] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):  # 跳过空行与以 # 开头的注释行
            continue

        url_match = re.search(r"(https?://[^\s,\"\')\]]+)", line)  # 取行内第一个 http(s) URL（遇空格/逗号/引号/括号截止）
        if not url_match:
            continue
        raw_url = url_match.group(1)
        url = normalize_request_url(raw_url)  # 同时归一横杠和 Unicode URL 编码

        title = ""
        url_start = url_match.start(1)
        key_match = re.search(r"[\"']([^\"']+)[\"']\s*:\s*\[", line[:url_start])  # 兼容 {"标题": ["url"]}：从 URL 左侧取引号里的键作标题
        if key_match:
            title = key_match.group(1).strip()
        if not title:  # 退回普通写法：取 URL 之前的片段作标题，剥离首尾引号/括号/逗号
            title_part = line[:url_start].strip(" \t,(\"'")
            title = re.sub(r"[\",\)\]]+$", "", title_part).strip()

        if not title:  # 仍无标题则用 URL 路径最后一段兜底，保证分组键非空
            title = urlparse(url).path.split("/")[-1]

        categories.append(config.CategoryItem(title=title, url=url))
    return categories


def build_page_url(base_url: str, page_num: int) -> str:
    # 按页码构造列表页 URL：Shopify 用 ?page=N 分页
    base_url = normalize_request_url(base_url)
    if page_num <= 1:
        return base_url  # 首页不带 page 参数（保持原始分类 URL）

    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))  # 保留原有 query（如 sort_by、filter）
    query["page"] = str(page_num)                                 # 覆盖/追加 page 参数
    return urlunparse(parsed._replace(query=urlencode(query)))


def extract_product_links(html_text: str, base_url: str) -> List[str]:
    # HTML 正则模式：从整页 HTML 抽取商品 handle，多重来源交叉命中后按 handle 去重
    base_parsed = urlparse(normalize_request_url(base_url))
    base = f"{base_parsed.scheme}://{base_parsed.netloc}"  # 协议+域名，用于把 handle 还原为绝对链接
    seen_handles = set()
    unique_handles: List[str] = []

    def add_handle(handle):  # 归一化 + 去重 + 保序加入
        handle = normalize_request_url(handle).strip("/")
        if handle and handle not in seen_handles:
            seen_handles.add(handle)
            unique_handles.append(handle)

    # 来源1：href 里的 /products/<handle>，兼容相对与绝对链接，遇到 ? # / 即截断 handle
    href_pattern = r'href=["\'](?:https?://[^/"\']+)?(/products/[^"\'?#/]+)'
    for href in re.findall(href_pattern, html_text, re.IGNORECASE):
        add_handle(unescape(href).rstrip("/").split("/")[-1])  # 反转义 HTML 实体后取末段 handle

    # 来源2：Shopify 页面常见 var meta = {...}; 里的 products[].handle（结构化数据，最可靠）
    meta_match = re.search(
        r"var\s+meta\s*=\s*(\{.+?\});\s*(?:\n|</script>)",
        html_text,
        re.DOTALL,  # .+? 跨行匹配到第一个结束大括号
    )
    if meta_match:
        try:
            meta_data = json.loads(meta_match.group(1))
            for product in meta_data.get("products", []):
                add_handle(product.get("handle", ""))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass  # meta 非标准 JSON 时静默跳过，交给其他来源/正则兜底

    # 来源3：正文任意 "handle":"x" 片段；但要求页面确有 /products/x 链接才采纳，降低误报
    for handle in re.findall(r'"handle"\s*:\s*"([^"]+)"', html_text):
        path_pattern = rf"/products/{re.escape(handle)}(?=[/?#\"'<>\s]|$)"  # 前瞻限定 handle 边界，避免前缀误匹配
        if re.search(path_pattern, html_text, re.IGNORECASE):
            add_handle(handle)

    return [f"{base}/products/{handle}" for handle in unique_handles]  # 统一还原为绝对商品链接


def extract_links_by_xpath(
    tab,
    xpath: str,
    stop_event: Optional[threading.Event] = None,
) -> List[str]:
    # XPath 模式：在浏览器里用给定 XPath 求值得到链接文本，再规整为绝对 /products/ URL 并去重
    result = browser_utils.evaluate_xpath(tab, xpath, stop_event=stop_event)

    if isinstance(result, dict) and result.get("__xpath_error__"):  # 求值报错=用户 XPath 语法非法，抛出让上层记错
        raise ValueError(f"XPath 无效: {result['__xpath_error__']}")
    if not isinstance(result, list):
        return []

    base_parsed = urlparse(normalize_request_url(tab.url))
    base = f"{base_parsed.scheme}://{base_parsed.netloc}"
    seen = set()
    links: List[str] = []

    for raw in result:
        raw = normalize_request_url(raw)
        if not raw:
            continue
        if raw.startswith("/"):          # 相对路径 → 补域名
            full = f"{base}{raw}"
        elif raw.startswith("http"):     # 已是绝对 URL → 直接用
            full = raw
        else:
            continue                     # 其他形态（纯文本等）忽略

        parsed = urlparse(full)
        match = re.match(r"^/products/([^/?#]+)", parsed.path, re.IGNORECASE)  # 只认 /products/<handle>，截出 handle
        if not match:
            continue
        normalized = f"{base}/products/{match.group(1)}"  # 去掉 query/锚点，统一成干净商品链接以便去重
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)

    return links


def collect_page_links(
    tab,
    stop_event: Optional[threading.Event] = None,
    xpath: str = "",
) -> List[str]:
    # 采集“当前这一页”的链接：先等页面稳定，再按模式选 XPath 或 HTML 正则
    if stop_event is not None:
        # 用 wait 而非 sleep 实现 PAGE_SETTLE_WAIT 稳定等待：停止时能立刻返回 []
        if stop_event.wait(config.PAGE_SETTLE_WAIT):
            return []
    else:
        time.sleep(config.PAGE_SETTLE_WAIT)

    if xpath:  # 配置了 XPath 就走浏览器内求值模式
        return extract_links_by_xpath(tab, xpath, stop_event=stop_event)

    html_text = browser_utils.get_outer_html(tab, stop_event=stop_event)  # 否则取整页 HTML
    if not html_text:
        return []
    return extract_product_links(html_text, tab.url)


class CollectorRunner:
    def __init__(
        self,
        cfg: config.CollectConfig,
        stop_event: Optional[threading.Event] = None,
        on_progress: Optional[ProgressCallback] = None,
        on_count: Optional[CountCallback] = None,
    ):
        self.cfg = cfg
        # 停止由 worker 传入的 threading.Event 驱动：各分页循环自己轮询 is_set() 后保存退出，
        # 不需要额外的中断入口，也不缓存标签页引用。
        self.stop_event = stop_event or threading.Event()  # 无外部停止事件时自建，保证 .is_set() 可用
        self.on_progress = on_progress
        self.on_count = on_count
        self.last_report = None   # 最近一次落盘报告，入口 run() 后读取
        self.errors = []          # 采集过程中的错误/警告文本，入口据此写失败清单

    def run(self) -> List[dict]:
        # 阶段主流程：建浏览器 → 逐分类分页采集 → finally 关浏览器并落盘（异常也保证保存）
        all_results: List[dict] = []
        seen_all_links = set()  # 跨分类去重集：同一商品链接只保留一次
        chrome = None

        # 采集前预置历史基线：读输出目录已有域名 CSV 的链接，避免本次把旧链接当成新链接跨分类重复入库
        try:
            existing_urls = file_utils.load_existing_urls(self.cfg.output_dir)
            if existing_urls:
                seen_all_links.update(existing_urls)
                logger.log(f"已读取历史基线 {len(existing_urls)} 条链接，跨分类去重将从这些链接开始")
        except Exception as e:
            logger.log(f"读取历史基线失败（不影响采集）: {e}")

        try:
            logger.log(self.cfg.summary())
            logger.log("")

            chrome = browser_utils.create_browser(  # 整个任务复用一个浏览器实例，逐分类换页
                proxy=self.cfg.proxy,
                port_range=self.cfg.port_range,
                disable_images=self.cfg.disable_images,
                browser_path=self.cfg.browser_path,
            )
            tab = chrome.latest_tab

            categories = self.cfg.categories
            for i, category in enumerate(categories, 1):
                if self.stop_event.is_set():  # 每个分类开始前检查停止
                    break
                self._collect_category(
                    index=i,
                    total=len(categories),
                    category=category,
                    tab=tab,
                    all_results=all_results,
                    seen_all_links=seen_all_links,
                )

        except Exception as e:  # 兜底：任何未处理异常记入 errors，不中断 finally 的落盘
            self.errors.append(str(e))
            logger.log(f"发生异常: {e}")
            logger.log_exc()

        finally:
            if chrome is not None:
                try:
                    chrome.quit()  # 关闭浏览器释放端口/进程；失败不影响结果，故吞异常仅记日志
                except Exception as e:
                    logger.log(f"关闭浏览器时出现异常（不影响保存）: {e}")

            # 无论正常结束还是停止/异常，都把已采结果落盘（合并写入域名 CSV）
            self.last_report = file_utils.save_results(
                all_results, self.cfg.output_dir, self.cfg.categories
            )

        return all_results

    def _collect_category(
        self,
        index: int,
        total: int,
        category: config.CategoryItem,
        tab,
        all_results: List[dict],
        seen_all_links: set,
    ) -> None:
        # 单个分类的分页采集循环：逐页翻、抽链接、分类内+跨分类两级去重，直到终止条件
        title = category.title
        base_url = category.url

        category_total = 0        # 本分类累计发现链接数（含被跳过的重复）
        category_new_for_all = 0  # 本分类贡献给全局结果的新增数
        category_skipped = 0      # 本分类因跨分类重复被跳过的数

        try:
            logger.log(f"[{index}/{total}] {title}")
            if self.on_progress is not None:
                self.on_progress(index, total, title)  # 通知 GUI 当前分类序号/总数

            seen_in_category = set()  # 分类内去重集（本页与之前页比对，判定是否还有新内容）
            page_num = 1

            while not self.stop_event.is_set():  # 停止检查点：每轮翻页入口判断
                if self.cfg.max_pages and page_num > self.cfg.max_pages:  # 达到页数上限则停止
                    logger.log(f"  已达到最大页数 {self.cfg.max_pages}")
                    break

                url = build_page_url(base_url, page_num)
                logger.log(f"  第 {page_num} 页: {url}")

                links = self._fetch_page_with_recovery(tab, url)  # 打开该页并抽链接（含上下文丢失恢复）
                if links is None:  # None 表示该页彻底加载失败：记错并结束本分类
                    if not self.stop_event.is_set():
                        self.errors.append(f"分类页面加载失败：{url}")
                    break

                if self.stop_event.is_set():  # 停止检查点：抓取过程中被停止则放弃当前页
                    logger.log("  当前页已放弃")
                    break

                new_links = [
                    link for link in links if link not in seen_in_category
                ]  # 只保留分类内首次出现的链接，用于翻页终止判断

                if not new_links:  # 本页全是老链接 → 无新内容
                    if page_num == 1:
                        # 首页就没有链接多半是没加载出来：重试首屏几次
                        new_links = self._retry_first_page(
                            tab, url, seen_in_category
                        )
                        if self.stop_event.is_set():
                            logger.log("  当前页已放弃")
                            break
                        if not new_links:  # 重试仍空 → 该分类不可采，记错并跳过
                            self.errors.append(f"分类首页没有采集到商品：{url}")
                            logger.log("  跳过该分类")
                            break
                    else:
                        # 翻页终止条件：非首页无新链接，视为已到列表末尾，分类采集完毕
                        logger.log("  无新链接，该分类采集完毕")
                        break

                page_new_for_all = 0
                page_skipped = 0
                for link in new_links:  # 逐链接做跨分类去重并累积结果
                    seen_in_category.add(link)
                    category_total += 1

                    if link in seen_all_links:  # 已在别的分类采过 → 跳过，避免重复入库
                        category_skipped += 1
                        page_skipped += 1
                        continue
                    seen_all_links.add(link)
                    all_results.append({"title": title, "link": link})  # 结果项：分类标题 + 商品链接
                    category_new_for_all += 1
                    page_new_for_all += 1

                logger.log(
                    f"  新增 {len(new_links)} 条（分类累计 {category_total} 条，"
                    f"全局新增 {page_new_for_all} 条，跨分类跳过 {page_skipped} 条）"
                )
                if self.on_count is not None:  # 把累计条数回报 GUI；回调异常不影响采集
                    try:
                        self.on_count(len(all_results))
                    except Exception as e:
                        logger.log(f"  链接计数回调异常（不影响采集）: {e}")
                page_num += 1

            logger.log(
                f"  共采集 {category_total} 条（新增 {category_new_for_all} 条，"
                f"跨分类去重跳过 {category_skipped} 条）"
            )
            logger.log("")

        except Exception as e:  # 单分类出错只记错并继续其他分类，不让整个任务崩
            self.errors.append(f"{title}: {e}")
            logger.log(f"  分类 [{title}] 出错: {e}")
            logger.log_exc()
            if category_total:  # 出错前已翻页拿到的链接保留在 all_results 中，不丢弃
                logger.log(
                    f"  已保留该分类此前完成分页的 {category_total} 条链接"
                )
            logger.log("")

    def _fetch_page_with_recovery(self, tab, url: str) -> Optional[List[str]]:
        # 打开一页并抽链接：ContextLostError 时快速重试一次；再失败返回 None（结束该分类）
        try:
            tab.get(url)
            if self.stop_event.is_set():  # 停止检查点：get 后判断，避免白抽
                logger.log("  当前页已放弃")
                return []
            return collect_page_links(
                tab, stop_event=self.stop_event, xpath=self.cfg.xpath
            )
        except ContextLostError:
            # 翻页途中上下文丢失（常见于页面自身重定向/刷新）：稍等重试一次
            if self.stop_event.is_set():
                logger.log("  当前页已放弃")
                return []
            logger.log("  页面上下文丢失，快速重试一次...")
            if self.stop_event.wait(config.CONTEXT_LOST_RETRY_DELAY):  # 等待期间可被停止打断
                return []
            try:
                tab.get(url)
                if self.stop_event.is_set():
                    logger.log("  当前页已放弃")
                    return []
                return collect_page_links(
                    tab, stop_event=self.stop_event, xpath=self.cfg.xpath
                )
            except ContextLostError:  # 重试仍丢失：判定页面无法恢复，结束该分类
                logger.log("  页面未恢复，结束该分类")
                return None

    def _retry_first_page(self, tab, url: str, seen_in_category: set) -> List[str]:
        # 首页抽不到链接时最多重试 MAX_RETRIES 次，间隔 RETRY_DELAY；任意一次拿到新链接即返回
        for retry in range(1, config.MAX_RETRIES + 1):
            if self.stop_event.is_set():
                break
            logger.log(f"  首页无链接，第 {retry}/{config.MAX_RETRIES} 次重试...")
            if self.stop_event.wait(config.RETRY_DELAY):  # 用 wait 实现延时，停止时立即跳出
                break

            links = self._fetch_page_with_recovery(tab, url)
            if links is None:  # 页面彻底失败，停止重试
                break
            if self.stop_event.is_set():
                break

            new_links = [link for link in links if link not in seen_in_category]
            if new_links:  # 重试见到新链接即成功返回，交回主循环继续处理
                logger.log(f"  重试成功: {len(new_links)} 条")
                return new_links

        return []  # 重试用尽仍无链接
