# ======================== 采集运行器 ========================
# 登记为旧模块名 scraper_runner：遍历域名链接 CSV（兼容旧版 JSON）、断点续传、抓包解析、失败重试一次、批量原子落盘。
import json
import os
import re
import time
from typing import Callable, List, Optional

import browser_utils
import config
import file_utils
import logger
import network_utils
from product_analysis import (
    needs_description_refresh, needs_option_refresh,
    parse_product_object, standardize_size_values,
)
from common.product_model import Product, ProductDataError, is_size_name

DELAY = config.DELAY                            # 商品间隔，见 config
TRANSIENT_RETRY_DELAY = config.TRANSIENT_RETRY_DELAY  # 瞬时失败重试等待秒数，见 config
FLUSH_EVERY = 10                                # 成功多少个商品后强制刷盘
FLUSH_INTERVAL = 15.0                           # 最长多少秒未刷盘就强制刷盘
create_browser = browser_utils.create_browser
fetch_json = network_utils.fetch_json
group_targets_by_json_url = network_utils.group_targets_by_json_url
read_targets = file_utils.read_targets
save_json = file_utils.save_json
FileStatusCallback = Callable[[int, str, str], None]   # 回调：文件序号、文案、状态
ProgressCallback = Callable[[float, float, str], None]  # 回调：当前数、总数、文案


class ScraperRunner:
    def __init__(self, task_files, task_folder, stop_event,
                 on_file_status: Optional[FileStatusCallback] = None,
                 on_progress: Optional[ProgressCallback] = None,
                 skip_positions=None, use_standard_sizes=True, keep_description_images=False,
                 keep_description_tables=False, browser_path=None):
        # 持有任务文件列表、项目根、停止事件、两个回写 UI 的回调与跳图位置配置。
        self.task_files = task_files
        self.task_folder = task_folder
        self.stop_event = stop_event
        self.on_file_status = on_file_status
        self.on_progress = on_progress
        self.skip_positions = list(skip_positions or [])
        self.use_standard_sizes = bool(use_standard_sizes)
        self.keep_description_images = bool(keep_description_images)
        self.keep_description_tables = bool(keep_description_tables)
        self.browser_path = browser_path or None

    def _emit_file_status(self, index, text, state):
        # 转发单文件状态给 UI；回调异常不能拖垮采集主流程，故吞掉。
        if self.on_file_status is None:
            return
        try:
            self.on_file_status(index, text, state)
        except Exception:
            pass

    def _emit_progress(self, current, total, text=""):
        # 转发进度给 UI，同样忽略回调异常。
        if self.on_progress is None:
            return
        try:
            self.on_progress(current, total, text)
        except Exception:
            pass

    @staticmethod
    def _handle_of_json_url(json_url):
        # 从 JSON URL 推出用于日志展示的商品 handle（文件名主干），并清洗非法字符。
        base = os.path.splitext(os.path.basename(json_url))[0]
        base = base.strip() or "product"
        base = re.sub(r'[\\/:*?"<>|]', "_", base)  # 去掉 Windows 文件名非法字符
        return base

    def run(self) -> List[dict]:
        # 主循环：逐文件读取→去重→断点续传→抓包解析→批量原子落盘，返回全部汇总行。
        active_file_index = None
        if not self.task_folder:
            raise RuntimeError("未指定保存目录，无法采集")
        try:
            all_results: List[dict] = []
            grand_success = 0
            grand_fail = 0
            file_count = len(self.task_files)
            for fi, file_info in enumerate(self.task_files):  # 一个文件对应一个域名店铺
                if self.stop_event.is_set():  # 每个文件开始前检查停止，支持整体中断
                    break
                active_file_index = fi  # 记录当前文件，异常/停止时用于回写状态
                self._emit_file_status(fi, "处理中", "running")
                fpath = file_info["path"]
                fname = os.path.basename(fpath)
                # 汇总产物路径：项目/Json/Data Analysis/<域名>.json（输入 CSV 只换扩展名，内容仍是九字段 JSON）
                analysis_path = os.path.join(
                    self.task_folder, config.JSON_SUBDIR, config.JSON_ANALYSIS_DIR,
                    os.path.splitext(fname)[0] + '.json',
                )
                print(f"\n{'=' * 50}")
                print(f"[{fi + 1}/{file_count}] {fname}")
                targets = read_targets(fpath)  # 读阶段 01 链接，得 (分类, URL, md5) 列表
                json_url_groups, dup_count = group_targets_by_json_url(targets)  # 按 JSON URL 去重
                total = len(json_url_groups)
                print(f"  共 {total} 个唯一商品（跳过 {dup_count} 个重复）")
                if total == 0:
                    print("  无商品，跳过")
                    self._emit_file_status(fi, "已跳过", "skipped")
                    continue
                saved = {}  # JSON URL → 已校验 Product，保存时复用，避免逐次重洗全部历史商品
                committed_rows = {}  # 已确认落盘的字典；补采/写盘失败时仍返回旧成果
                if os.path.exists(analysis_path):
                    # 已存在汇总文件则载入并按商品对象校验，作为续传基线；校验不过宁可不覆盖。
                    with open(analysis_path, encoding="utf-8") as source:
                        existing = json.load(source)
                    if not isinstance(existing, list):
                        raise ValueError(f"汇总 JSON 格式错误，未覆盖：{analysis_path}")
                    try:
                        products = []
                        for row in existing:
                            # strict=True 等价于旧的内联校验：必需键齐全、无未知键、url 与两个模式字段合法
                            products.append(Product.from_dict(
                                row, strict=True, keep_images=self.keep_description_images,
                                keep_tables=self.keep_description_tables,
                            ))
                    except ProductDataError as exc:
                        raise ValueError(f"汇总 JSON 格式错误，未覆盖：{analysis_path}") from exc
                    original_rows = {}
                    duplicate_count = 0
                    cleaned_count = 0
                    for row, product in zip(existing, products):
                        # 用编码后的 JSON URL 作键；只合并内容相同的重复记录，冲突时保护旧文件。
                        key = network_utils.to_shopify_json_url(row["url"])
                        if key in original_rows:
                            # 历史表情原文/编码两条记录，内容相同时合并；冲突仍拒绝覆盖。
                            previous_row = original_rows[key]
                            previous = dict(previous_row, url=network_utils.normalize_request_url(previous_row['url']))
                            current = dict(row, url=network_utils.normalize_request_url(row['url']))
                            if previous != current:
                                raise ValueError(f"汇总 JSON 同一商品记录内容冲突，未覆盖：{analysis_path}")
                            duplicate_count += 1
                            continue
                        original_rows[key] = row
                        # 开启后直接转换已有明细，旧 original 标记和商品标题均不绕过。
                        # 关闭后需要恢复网站原值，仍由下方模式检查触发补采。
                        if self.use_standard_sizes:
                            for dimension in product.options:
                                if is_size_name(dimension.name) and isinstance(dimension.values, list):
                                    dimension.values = standardize_size_values(dimension.values)
                                    product.option_counts[dimension.name] = dimension.count
                                    product.size_mode = 'standard'
                        saved[key] = product
                        committed_rows[key] = row
                        normalized = product.to_dict()
                        if needs_description_refresh(row, self.keep_description_images,
                                                     self.keep_description_tables):
                            # 旧模式需要恢复时，不能仅因构造器按旧策略删除了正文图/表
                            # 就提前覆盖基线；等补采或其他实际写盘成功后再提交。
                            policy_fields = {'body_html', 'description_image_mode', 'description_table_mode'}
                            normalized = {name: value for name, value in normalized.items()
                                          if name not in policy_fields}
                            original = {name: value for name, value in row.items()
                                        if name not in policy_fields}
                        else:
                            original = row
                        if normalized != original:
                            cleaned_count += 1
                    # 冲突检查始终用原内容；全部通过后才写回已规范化的商品对象。
                    cleaned_count += duplicate_count
                    if cleaned_count:  # 有改动才回写，避免无谓落盘
                        save_json(list(saved.values()), analysis_path, keep_description_images=self.keep_description_images,
                                  keep_description_tables=self.keep_description_tables)
                        committed_rows = {key: product.to_dict() for key, product in saved.items()}
                        print(f"  已规范化或合并已有汇总数据 {cleaned_count} 条（标题/分类、商品链接/重复记录、描述、价格或颜色/尺码）")
                # 明细缺失、尺码模式改变或描述图片需要恢复时补采；失败或中断保留旧记录。
                option_repairs = set()
                for url in json_url_groups:
                    if url not in saved:
                        continue
                    row = saved[url].to_dict()
                    if (needs_option_refresh(row, self.use_standard_sizes)
                            or needs_description_refresh(row, self.keep_description_images,
                                                         self.keep_description_tables)):
                        option_repairs.add(url)
                if option_repairs:
                    print(f"  选项明细/尺码模式/描述图片需要更新：{len(option_repairs)} 个商品将重新采集")
                todo = {url: group for url, group in json_url_groups.items()
                        if url not in saved or url in option_repairs}
                print(f"  断点续传: 已保存 {total - len(todo)} 个商品")
                if not todo:
                    # 全部已采集，直接并入结果、标记完成，不再开浏览器
                    all_results.extend(committed_rows[key] for key in json_url_groups if key in committed_rows)
                    self._emit_file_status(fi, "已完成", "success")
                    continue
                # 新采集/补采结果先放在 pending，按批次并入 saved 后原子写回。
                # 这样仍保持「成功写盘后才更新 committed_rows」的安全语义。
                pending = {}
                last_flush_at = time.monotonic()

                class PendingFlushError(RuntimeError):
                    """批量刷盘失败，不能继续推进当前域名。"""

                def flush_pending(force=False):
                    nonlocal saved, committed_rows, pending, last_flush_at
                    if not pending:
                        return False
                    if not force and len(pending) < FLUSH_EVERY \
                            and time.monotonic() - last_flush_at < FLUSH_INTERVAL:
                        return False
                    candidate = dict(saved)
                    candidate.update(pending)
                    ordered = [candidate[key] for key in json_url_groups if key in candidate]
                    ordered.extend(row for key, row in candidate.items() if key not in json_url_groups)
                    try:
                        save_json(ordered, analysis_path,
                                  keep_description_images=self.keep_description_images,
                                  keep_description_tables=self.keep_description_tables)
                    except Exception as exc:
                        raise PendingFlushError(f"批量保存汇总 JSON 失败：{exc}") from exc
                    batch_size = len(pending)
                    saved = candidate
                    # 只转换本批已提交商品，避免每次刷盘后重建全部历史 committed_rows。
                    committed_rows.update({key: product.to_dict() for key, product in pending.items()})
                    pending = {}
                    last_flush_at = time.monotonic()
                    print(f"  已批量保存 {len(committed_rows)} 个商品（本次写入 {batch_size} 条）")
                    return True

                def flush_pending_final():
                    # 文件完成、停止或异常收尾都必须把未满一批的成功结果落盘。
                    return flush_pending(force=True)

                self._emit_progress(0, len(todo), f"[{fi + 1}/{file_count}] 正在采集与解析 · {fname}")
                chrome = None  # 浏览器延迟到真正需要采集时才开，且每文件复用同一个
                success_count = 0
                fail_count = 0
                file_exception = None
                try:
                    for index, (json_url, group) in enumerate(todo.items(), 1):
                        if self.stop_event.is_set():  # 逐个商品检查停止
                            break
                        table_title = group["title"]
                        handle = self._handle_of_json_url(json_url)
                        self._emit_progress(index, len(todo), f"[{fi + 1}/{file_count}] {fname} · {table_title[:24]}")
                        print(f"  [{index}/{len(todo)}] {table_title} -> {os.path.relpath(analysis_path, self.task_folder)}")
                        if chrome is None:  # 首个待采商品时才启动浏览器
                            chrome = create_browser(self.browser_path)
                            tab = chrome.latest_tab
                        status = 0
                        data = None
                        retried = False  # 重试一次标记：实现"失败重试一次"的边界
                        while True:  # 采集循环：成功或已重试过就退出，最多重试一次
                            if self.stop_event.is_set():
                                break
                            status, data = fetch_json(tab, json_url, stop_event=self.stop_event)
                            if self.stop_event.is_set():
                                break
                            if status == 200 and data:  # 抓到有效 JSON 才算成功
                                break
                            failure = ('未监听到响应' if status == 0 else
                                       'HTTP 200，但无有效 JSON' if status == 200 else f'HTTP {status}')
                            if retried:  # 已经重试过一次仍失败 → 放弃该商品
                                print(f"    {failure}，已重试一次，放弃：{json_url}")
                                break
                            retried = True
                            print(f"    {failure}，{TRANSIENT_RETRY_DELAY}秒后重试一次：{json_url}")
                            # 等待用 stop_event.wait，既能冷却又能被停止信号即时打断
                            if self.stop_event.wait(TRANSIENT_RETRY_DELAY):
                                break
                        if self.stop_event.is_set():
                            break
                        if status == 200 and data:
                            try:
                                # 解析成九字段行；title 取 Shopify 商品标题，fennei 取分类标题
                                result = parse_product_object(
                                    data, url=group["original_url"],
                                    title=data["product"].get("title", ""), fennei=group["title"],
                                    skip_positions=self.skip_positions,
                                    use_standard_sizes=self.use_standard_sizes,
                                    keep_description_images=self.keep_description_images,
                                    keep_description_tables=self.keep_description_tables,
                                    md5=group.get("md5", ""),
                                )
                                pending[json_url] = result
                                success_count += 1
                                flush_pending()
                                print(f"    采集与解析成功: {handle}.json")
                            except PendingFlushError:
                                # 刷盘失败不能当作单个商品失败继续推进，否则会丢失本批结果。
                                raise
                            except Exception as exc:
                                # 解析失败只记为该商品失败；尚未落盘的结果仍留在 pending，收尾时提交。
                                print(f"    解析失败: {exc}")
                                fail_count += 1
                        else:
                            fail_count += 1  # 重试后仍非 200/空数据，计为失败
                            print(f"    采集失败（{failure}）：{json_url}")
                        if self.stop_event.wait(DELAY):  # 商品间冷却，同时响应停止
                            break
                except Exception as exc:
                    # 文件级异常：记住它，收尾时据以把该文件标记 failed 并上抛
                    file_exception = exc
                    print(f"  当前文件采集异常: {exc}")
                    logger.log_exc()
                finally:
                    if chrome is not None:  # 无论成功失败都关闭本文件启动的浏览器，释放端口/进程
                        print("  正在关闭浏览器...")
                        try:
                            chrome.quit()
                        except Exception as exc:
                            print(f"  关闭浏览器失败: {exc}")
                try:
                    flush_pending_final()
                except Exception as exc:
                    # 未提交的批次不能进入返回结果；把刷盘错误升级为文件级失败。
                    file_exception = file_exception or exc
                    print(f"  批量收尾保存失败: {exc}")
                all_results.extend(committed_rows[key] for key in json_url_groups if key in committed_rows)  # 含续传已有的 + 本次已落盘
                grand_success += success_count
                grand_fail += fail_count
                if self.stop_event.is_set():  # 采集中途被停止
                    self._emit_file_status(fi, "已停止", "stopped")
                    break
                if file_exception is not None:
                    self._emit_file_status(fi, "发生异常", "failed")
                    raise file_exception  # 文件级异常继续上抛，交由入口记录失败清单
                if fail_count > 0:
                    self._emit_file_status(fi, f"{fail_count} 个失败", "failed")
                else:
                    self._emit_file_status(fi, "已完成", "success")
            if self.stop_event.is_set() and active_file_index is not None:
                # 停止后把尚未处理的文件状态刷成 waiting，让 UI 进度一致
                for pending_index in range(active_file_index + 1, len(self.task_files)):
                    self._emit_file_status(pending_index, "未处理", "waiting")
            final_text = f"总计：{grand_success} 成功，{grand_fail} 失败，{len(all_results)} 条数据"
            if self.stop_event.is_set():
                final_text = "任务已中断 · " + final_text
            self._emit_progress(grand_success + grand_fail, grand_success + grand_fail, final_text)
            print(f"\n{final_text}")
            return all_results
        except Exception as exc:
            # 顶层兜底：记录异常、回写失败状态后重新抛出，让 worker/入口判定阶段失败
            print(f"发生异常: {exc}")
            logger.log_exc()
            if active_file_index is not None:
                self._emit_file_status(active_file_index, "发生异常", "failed")
            self._emit_progress(0, 0, f"任务异常：{exc}")
            raise
