# ======================== 文件持久化层 ========================
#
# 职责: 采集结果落盘。含旧文件安全读取、恢复文件命名、分类索引维护、
#       按域名分组、按分类合并写两列 CSV。
# 依赖: config、logger。
# 禁止: 导入 tkinter、DrissionPage、collector、browser_utils。
# ========================================================

import csv
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

import config
import logger
from url_utils import normalize_request_url
from common.atomic_io import replace_file


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')  # Windows 文件名非法字符+控制符，域名转文件名时替换为下划线


def _safe_domain_filename(domain: str) -> str:  # 把域名清洗成安全文件名；全空则回退 unknown_domain
    safe = _INVALID_FILENAME_CHARS.sub("_", str(domain or ""))
    safe = safe.rstrip(". ")  # 去掉结尾点/空格，避免 Windows 生成非法或隐藏后缀名
    return safe or "unknown_domain"


DOMAIN_HEADER = ("title", "url", "md5")  # 域名链接 CSV 的三列：分类标题、商品链接、url 的 md5
INDEX_HEADER = ("title", "url")   # 链接索引 CSV 的两列：分类标题、分类列表页 URL


def _load_domain_csv(file_path: str) -> Dict[str, List[str]]:
    # 读取域名 CSV 为 {分类: [链接]}；缺列/空链接视为损坏并抛错，交由上层保护原文件
    grouped: Dict[str, List[str]] = {}
    first_row = True
    with open(file_path, "r", encoding=config.CSV_ENCODING, newline="") as f:
        for line_no, row in enumerate(csv.reader(f), 1):
            if not row or not any(str(cell).strip() for cell in row):
                continue
            if first_row:  # 表头只可能在第一条非空行；不是表头就照常当数据
                first_row = False
                if len(row) >= 2 and row[0].strip().lower() == DOMAIN_HEADER[0] \
                        and row[1].strip().lower() == DOMAIN_HEADER[1]:
                    continue
            if len(row) < 2:
                raise ValueError(f"第 {line_no} 行少于两列")
            title = str(row[0]).strip() or "未分类"
            link = normalize_request_url(row[1])  # 历史表情原文与百分号编码链接统一去重
            if not link:
                raise ValueError(f"第 {line_no} 行缺少有效链接")
            links = grouped.setdefault(title, [])
            if link not in links:
                links.append(link)
    return grouped


def _load_legacy_domain_json(file_path: str) -> Dict[str, List[str]]:
    # 兼容旧版 <域名>.json：跳过 domain/generated_at/link_count 元数据，其余键即分类
    grouped: Dict[str, List[str]] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    for key, value in raw.items():
        if key in ("domain", "generated_at", "link_count"):
            continue
        if not isinstance(value, list):
            continue
        links: List[str] = []
        for raw_link in value:
            link = normalize_request_url(raw_link)
            if link and link not in links:
                links.append(link)
        if links:
            grouped[str(key)] = links
    return grouped


def load_existing_domain_data(file_path: str) -> Optional[Dict[str, List[str]]]:
    # 断点续采读取：优先同名 CSV；首次升级时回退读旧版 .json（只读，不回写）
    # 读/解析失败返回 None：上层据此绝不覆盖原文件，另存 recovery 保住旧数据
    if os.path.exists(file_path):
        try:
            return _load_domain_csv(file_path)
        except Exception as e:
            logger.log(f"读取已有文件失败，已保护原文件不覆盖: {e}")
            return None
    legacy_path = os.path.splitext(file_path)[0] + config.LEGACY_DOMAIN_FILE_EXT
    if os.path.exists(legacy_path):
        try:
            logger.log(f"已读取旧版 {os.path.basename(legacy_path)} 的历史链接，本次起写入 CSV")
            return _load_legacy_domain_json(legacy_path)
        except Exception as e:
            logger.log(f"读取旧版链接文件失败，已保护原文件不覆盖: {e}")
            return None
    return {}  # 两者都不存在：首次采集


def load_existing_urls(output_path: str) -> set:
    # 采集前扫描输出目录里已有的域名 CSV，汇总全部已采链接，作为跨分类去重的历史基线。
    # 只读、不写、不重算 md5：历史文件保持原样，新逻辑仅影响后续任务。
    existing_urls = set()
    if not output_path or not os.path.isdir(output_path):
        return existing_urls
    try:
        entries = os.listdir(output_path)
    except OSError as e:
        logger.log(f"扫描输出目录失败（跳过历史基线）: {e}")
        return existing_urls

    for name in entries:
        if not name.lower().endswith(config.DOMAIN_FILE_EXT):
            continue
        file_path = os.path.join(output_path, name)
        try:
            grouped = load_existing_domain_data(file_path)
        except Exception as e:
            logger.log(f"读取历史域名文件失败（跳过）: {file_path}（{e}）")
            continue
        if not grouped:
            continue
        for links in grouped.values():
            for link in links:
                existing_urls.add(link)
    return existing_urls


def build_recovery_file_path(file_path: str) -> str:
    # 生成一个不与现有文件冲突的 recovery 副本路径（原路径 + .recovery-时间戳[.计数]）
    base, ext = os.path.splitext(file_path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    mark = config.RECOVERY_MARK
    candidate = f"{base}.{mark}-{stamp}{ext or config.DOMAIN_FILE_EXT}"
    counter = 2
    while os.path.exists(candidate):  # 同秒多次则追加计数，确保不覆盖已有 recovery
        candidate = f"{base}.{mark}-{stamp}-{counter}{ext or config.DOMAIN_FILE_EXT}"
        counter += 1
    return candidate


def _index_rows(index: Dict[str, Dict[str, List[str]]]):
    # 把 {域名:{分类:[url]}} 摊平成两列 CSV 行；同一分类多个列表页会写成多行，顺序与采集一致
    for cats in index.values():
        for title, urls in cats.items():
            for url in urls:
                yield str(title), url


def _atomic_write_index(csv_path: str, index: Dict) -> None:
    # 原子写索引：统一走 replace_file（临时文件 + os.replace），避免半截文件
    def _write(tmp_path):
        # utf-8-sig 带 BOM，Excel / WPS 直接双击打开中文标题不乱码；newline='' 交给 csv 写行尾
        with open(tmp_path, "w", encoding=config.CSV_ENCODING, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(INDEX_HEADER)
            writer.writerows(_index_rows(index))

    replace_file(csv_path, _write, ".csv")


def _load_index_csv(csv_path: str) -> Dict[str, Dict[str, List[str]]]:
    # 读回两列 CSV 并还原成 {域名:{分类:[url]}}；容忍 BOM、空行、多余列、重复行
    index: Dict[str, Dict[str, List[str]]] = {}
    first_row = True
    with open(csv_path, "r", encoding=config.CSV_ENCODING, newline="") as f:
        for line_no, row in enumerate(csv.reader(f), 1):
            if not row or not any(str(cell).strip() for cell in row):
                continue
            if first_row:  # 表头只可能在第一条非空行；不是表头就照常当数据
                first_row = False
                if len(row) >= 2 and row[0].strip().lower() == INDEX_HEADER[0] \
                        and row[1].strip().lower() == INDEX_HEADER[1]:
                    continue
            # 缺列/空 URL 视为文件损坏：抛出让上层备份原文件后重建，而不是静默丢掉这行历史
            if len(row) < 2:
                raise ValueError(f"第 {line_no} 行少于两列")
            title = str(row[0]).strip()
            url = normalize_request_url(row[1])
            if not url:
                raise ValueError(f"第 {line_no} 行缺少有效 URL")
            urls = index.setdefault(urlparse(url).netloc, {}).setdefault(title, [])
            if url not in urls:
                urls.append(url)
    return index


def _backup_broken_index(path: str, recovery_out: Optional[List[str]], error) -> None:
    # 索引损坏：改名备份后重建，绝不直接覆盖丢失历史；连备份都失败也继续（原文件留原地）
    backup_path = build_recovery_file_path(path)
    try:
        os.replace(path, backup_path)
        if recovery_out is not None:  # 记录备份路径，供报告展示
            recovery_out.append(backup_path)
        logger.log(f"读取已有链接记录失败，原文件已备份为: {backup_path}（{error}）")
    except OSError as move_err:
        logger.log(f"读取已有链接记录失败且备份失败: {error}；备份错误: {move_err}")


def _read_index_for_append(
    csv_path: str,
    legacy_path: str,
    recovery_out: Optional[List[str]],
) -> Dict[str, Dict[str, List[str]]]:
    # 续写用：优先读 CSV；首次升级时兼容旧版 links_index.json，读完仍按 CSV 写回
    if os.path.exists(csv_path):
        try:
            return _load_index_csv(csv_path)
        except (OSError, ValueError, TypeError, csv.Error) as e:
            _backup_broken_index(csv_path, recovery_out, e)
    if os.path.exists(legacy_path):
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            logger.log("已读取旧版 links_index.json 的历史分类，本次起改写入 links_index.csv")
            return _normalize_index(loaded)
        except (OSError, ValueError, TypeError) as e:
            _backup_broken_index(legacy_path, recovery_out, e)
    return {}


def update_link_index(
    output_path: str,
    categories: Sequence,
    recovery_out: Optional[List[str]] = None,
) -> str:
    # 维护 links_index.csv（两列：分类标题、分类URL）：读旧→合并本批分类→原子写；坏文件先备份不覆盖
    csv_path = os.path.join(output_path, config.LINK_INDEX_FILENAME)
    legacy_path = os.path.join(output_path, config.LEGACY_LINK_INDEX_FILENAME)
    index = _read_index_for_append(csv_path, legacy_path, recovery_out)

    added = 0
    title_counts: Dict[tuple, int] = {}  # (域名,标题)→出现次数，用于检测同域名下重名分类
    for item in categories:
        title, url = _unpack_category(item)
        url = normalize_request_url(url)
        if not url:
            continue
        domain = urlparse(url).netloc  # 按域名分桶，与落盘的域名文件一一对应
        title = str(title or "").strip()
        title_counts[(domain, title)] = title_counts.get((domain, title), 0) + 1

        urls = index.setdefault(domain, {}).setdefault(title, [])  # 逐级建桶 domain→title→[urls]
        if url not in urls:  # 已记录过该分类 URL 则不重复（断点续采：分类层去重）
            urls.append(url)
            added += 1

    os.makedirs(output_path, exist_ok=True)
    _atomic_write_index(csv_path, index)
    logger.log(f"已更新链接记录: {csv_path}（新增 {added} 个分类）")

    repeated = [  # 收集同域名下标题重复的分类，提醒但不丢数据（URL 全部保留）
        f"{domain} / {title} × {count}"
        for (domain, title), count in title_counts.items()
        if count > 1
    ]
    if repeated:
        logger.log(
            "提示: 以下分类标题在同一域名下重复，索引已保留全部 URL: "
            + "；".join(repeated)
        )
    return csv_path


def _normalize_index(loaded) -> Dict[str, Dict[str, List[str]]]:
    # 把任意旧版/脏数据结构强转为 {域名:{分类:[url]}}，逐项容错，坏数据丢弃而非报错
    index: Dict[str, Dict[str, List[str]]] = {}
    if not isinstance(loaded, dict):
        return index
    for domain, titles in loaded.items():
        if not isinstance(titles, dict):
            continue
        bucket: Dict[str, List[str]] = {}
        for title, value in titles.items():
            if isinstance(value, dict) or value is None:  # 跳过异常形态
                continue
            urls: List[str] = []
            for raw in (value if isinstance(value, list) else [value]):  # 兼容旧版单值写成字符串
                raw = normalize_request_url(raw)
                if raw and raw not in urls:
                    urls.append(raw)
            if urls:
                bucket[str(title)] = urls
        if bucket:
            index[str(domain)] = bucket
    return index


def _unpack_category(item):
    # 统一取出 (标题, URL)：优先 CategoryItem 属性，否则兼容 (title, url) 元组/列表
    title = getattr(item, "title", None)
    url = getattr(item, "url", None)
    if title is None and url is None and isinstance(item, (tuple, list)):
        if len(item) >= 2:
            return item[0], item[1]
        return "", item[0] if item else ""  # 只有一个元素时当 URL，标题留空
    return title or "", url or ""


def _link_md5(link: str) -> str:
    # 第三列：纯 url 的 md5（小写 32 位十六进制），供下游唯一标识/去重。
    # 只用 url、不掺分类：同一 URL 无论出现在哪个分类，md5 都一致，跨分类去重直观可见。
    return hashlib.md5(link.encode("utf-8")).hexdigest()


def _write_domain_csv(file_path: str, grouped: Dict[str, List[str]]) -> int:
    # 三列 CSV（分类、商品链接、url 的 md5）原子落盘，返回写入的链接总行数；域名由文件名与链接反推
    total = sum(len(links) for links in grouped.values())

    def _write(tmp_path):
        with open(tmp_path, "w", encoding=config.CSV_ENCODING, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(DOMAIN_HEADER)
            for cat, links in grouped.items():
                for link in links:
                    writer.writerow([str(cat), link, _link_md5(link)])

    replace_file(file_path, _write, ".csv")
    return total


@dataclass
class SaveReport:  # 一次落盘的统计结果，供入口生成产物说明与失败提示
    total_rows: int = 0            # 本次待保存的链接行数
    written_rows: int = 0          # 实际写入文件的链接条数（含合并后的新增）
    domain_files: int = 0          # 成功写出的域名文件数
    written_files: List[str] = field(default_factory=list)
    recovery_files: List[str] = field(default_factory=list)     # 因原文件读/写失败而另存的副本
    index_recovery_files: List[str] = field(default_factory=list)  # 索引损坏时的备份文件
    index_error: Optional[str] = None  # 索引更新失败信息（不影响域名文件）
    errors: List[str] = field(default_factory=list)
    error: Optional[str] = None        # 致命错误（如建目录失败）

    def describe(self) -> str:  # 生成一行人类可读的保存结果摘要，用于 GUI 产物文本
        if self.error:
            return f"保存失败: {self.error}"
        if not self.total_rows:
            parts = ["本次没有新增可保存的链接"]
        else:
            parts = [
                f"共写入 {self.domain_files} 个域名文件、"
                f"{self.written_rows} 条链接"
            ]
            if self.recovery_files:
                parts.append(f"其中 {len(self.recovery_files)} 个为恢复文件")
            unwritten = self.total_rows - self.written_rows  # 差值=未能落盘的链接
            if unwritten > 0:
                parts.append(f"另有 {unwritten} 条未能写入")
            if self.index_recovery_files:
                parts.append(f"索引备份 {len(self.index_recovery_files)} 个")
        if self.index_error:  # 索引失败单独提示：域名文件不受影响
            parts.append(f"索引更新失败（域名文件不受影响）: {self.index_error}")
        return "；".join(parts)


def save_results(
    rows: Sequence[dict],
    output_path: str,
    categories: Sequence = (),
) -> SaveReport:
    # 落盘总入口：建目录 → 更新分类索引 → 按域名分组 → 逐域名“读旧合并写新”；任何读/写失败都另存 recovery 保护原数据
    report = SaveReport(total_rows=len(rows))

    try:
        os.makedirs(output_path, exist_ok=True)
    except OSError as e:  # 输出目录都建不了，直接终止并返回错误报告
        report.error = f"创建输出目录失败: {e}"
        report.errors.append(report.error)
        logger.log(report.error)
        return report

    try:
        update_link_index(
            output_path, categories, recovery_out=report.index_recovery_files
        )
    except Exception as e:
        # 索引只是辅助记录，失败不影响商品链接落盘，记入 index_error 后继续
        logger.log(f"更新分类索引失败（不影响域名 CSV 写出）: {e}")
        report.index_error = str(e)
        report.errors.append(f"索引更新失败：{e}")

    logger.log(f"采集结束: 共 {len(rows)} 条链接")

    if not rows:  # 无新增链接：仍更新了索引，直接返回
        logger.log("本次没有新增可保存的链接")
        return report

    domain_groups: Dict[str, List[dict]] = {}
    for raw_row in rows:
        row = dict(raw_row, link=normalize_request_url(raw_row["link"]))  # 链接先统一编码再入库
        domain = urlparse(row["link"]).netloc  # 用链接的域名分组：每域名一个 CSV 文件
        domain_groups.setdefault(domain, []).append(row)

    for domain, domain_rows in domain_groups.items():
        safe_domain = _safe_domain_filename(domain)
        file_name = f"{safe_domain}{config.DOMAIN_FILE_EXT}"
        file_path = os.path.join(output_path, file_name)

        existing = load_existing_domain_data(file_path)  # 断点续采：读回旧链接，合并后再写，只增不丢

        if existing is None:
            # 旧文件存在但读坏了：绝不覆盖，把本轮结果另存到 recovery 文件
            recovery_path = build_recovery_file_path(file_path)
            recovery_grouped: Dict[str, List[str]] = {}
            for row in domain_rows:
                cat = str(row.get("title") or "").strip() or "未分类"  # 无标题归入“未分类”
                links = recovery_grouped.setdefault(cat, [])
                if row["link"] not in links:  # 同分类内去重
                    links.append(row["link"])
            try:
                report.written_rows += _write_domain_csv(
                    recovery_path, recovery_grouped
                )
                report.recovery_files.append(recovery_path)
                report.written_files.append(recovery_path)
                logger.log(
                    f"原文件读取失败，已禁止覆盖: {file_path}"
                    f"；本轮结果另存为: {recovery_path}"
                )
            except Exception as e:  # 连 recovery 也写失败：放弃该域名，继续下一个
                logger.log(f"写入恢复文件也失败: {recovery_path}（{e}）")
                report.errors.append(f"域名文件未能写入：{file_path}")
            continue

        # 正常路径：合并“已有分类链接 + 本批新链接”，实现断点续采式只追加不重复
        merged = {cat: list(links) for cat, links in existing.items()}
        added = 0
        for row in domain_rows:
            cat = str(row.get("title") or "").strip() or "未分类"
            links = merged.setdefault(cat, [])
            if row["link"] not in links:  # 已采过的链接不再重复写入（去重判断点）
                links.append(row["link"])
                added += 1

        try:
            report.written_rows += _write_domain_csv(file_path, merged)
        except Exception as e:
            # 写正式文件失败：把合并结果另存 recovery，保住本轮 + 历史合并成果
            recovery_path = build_recovery_file_path(file_path)
            try:
                report.written_rows += _write_domain_csv(recovery_path, merged)
                report.recovery_files.append(recovery_path)
                report.written_files.append(recovery_path)
                logger.log(
                    f"写入失败，原文件已保护: {file_path}；"
                    f"合并结果另存为: {recovery_path}（{e}）"
                )
            except Exception as e2:  # recovery 也失败：该域名跳过，不影响其他域名
                logger.log(f"写入恢复文件也失败: {recovery_path}（{e2}）")
                report.errors.append(f"域名文件未能写入：{file_path}")
            continue

        report.written_files.append(file_path)
        prev_total = sum(len(v) for v in existing.values())   # 合并前旧链接数
        merged_total = sum(len(v) for v in merged.values())   # 合并后总数
        logger.log(
            f"已保存: {file_path}（已有 {prev_total} 条 + 新增 {added} 条"
            f" = 合并 {merged_total} 条）"
        )

    report.domain_files = len(report.written_files)
    logger.log(
        f"共 {report.domain_files} 个域名文件（输入分组 {len(domain_groups)} 个）"
    )
    return report
