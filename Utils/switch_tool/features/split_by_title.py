# -*- coding: utf-8 -*-
"""功能 5：CSV 按 title 拆分（均分 N 份）。

共享辅助（collect_*、save_*、sanitize_sheet_name）也供功能 6（按 title 切分）复用。
"""

import csv
import re
from pathlib import Path

from ..constants import DEFAULT_TITLE_COL, DEFAULT_PRICE_COL, DEFAULT_PARTS
from ..utils import strip_quotes, detect_encoding, price_sort_key


def collect_xlsx_files(target):
    """目标可以是单个 xlsx 文件，也可以是一个文件夹（递归收集其中的 xlsx）。"""
    path = Path(strip_quotes(target))
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*.xlsx")
            if p.is_file() and not p.name.startswith("~$")
        )
    if path.is_file() and path.suffix.lower() == ".xlsx":
        return [path]
    return []


def collect_csv_files_split(target):
    """目标可以是单个 csv 文件，也可以是一个文件夹（递归收集其中的 csv）。"""
    path = Path(strip_quotes(target))
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*.csv")
            if p.is_file() and not p.name.startswith("~$")
        )
    if path.is_file() and path.suffix.lower() == ".csv":
        return [path]
    return []


def save_workbook(wb, path):
    """保存工作簿；被其他程序占用时抛出可读的错误。"""
    try:
        wb.save(path)
    except PermissionError:
        raise PermissionError(f"文件被其他程序占用（如 Excel），请关闭后重试：{path}") from None


def save_split_workbook(path, header, rows):
    """按 utf-8 写出 CSV 拆分结果。"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def sanitize_sheet_name(text):
    """把 title 值清洗成可用的文件名：去除 Windows 非法字符与首尾空白，空则用占位。"""
    if text is None:
        text = ""
    text = str(text).strip()
    # Windows 文件名非法字符：\ / : * ? " < > |
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = re.sub(r"\s+", " ", text)
    # 控制字符
    text = re.sub(r"[\x00-\x1f]", "", text)
    # 去掉结尾的点/空格（Windows 不允许）
    text = text.rstrip(". ")
    return text if text else "未命名"


def split_by_title(csv_path, parts, title_col=DEFAULT_TITLE_COL, price_col=DEFAULT_PRICE_COL,
                   overwrite=True, log=print):
    """按 title_col 分组、按 price_col 排序后轮询分配到 parts 个 csv，返回统计信息 dict。"""
    csv_path = Path(csv_path)
    parts = max(1, int(parts))

    encoding = detect_encoding(csv_path)
    with open(csv_path, encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            log(f"[跳过] 空文件：{csv_path.name}")
            return None
        rows = list(reader)

    if title_col not in header:
        log(f"[跳过] 缺少「{title_col}」列：{csv_path.name}")
        return None

    ti = header.index(title_col)
    has_price = price_col in header
    if not has_price:
        log(f"[提示] 缺少「{price_col}」列，组内保持原顺序：{csv_path.name}")
    pi = header.index(price_col) if has_price else None

    groups = {}
    for r in rows:
        groups.setdefault(r[ti], []).append(r)
    if pi is not None:
        for g in groups.values():
            g.sort(key=lambda r: price_sort_key(r[pi]))

    buckets = [[] for _ in range(parts)]
    for g in groups.values():
        for i, r in enumerate(g):
            buckets[i % parts].append(r)

    stem = csv_path.stem
    outdir = csv_path.parent
    outputs = []
    for k, bucket in enumerate(buckets, 1):
        out_path = outdir / f"{stem}_{k}.csv"
        if not overwrite and out_path.exists():
            out_path = outdir / f"{stem}_{k}_新.csv"
        save_split_workbook(out_path, header, bucket)
        outputs.append(out_path)
        log(f"[完成] {out_path.name} -> {len(bucket)} 行")

    log(f"[完成] {csv_path.name}：共 {len(rows)} 行 / {len(groups)} 组，拆分 {parts} 份")
    return {
        "file": csv_path,
        "total": len(rows),
        "groups": len(groups),
        "parts": parts,
        "outputs": outputs,
    }
