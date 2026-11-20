# -*- coding: utf-8 -*-
"""功能 6：CSV 按 title 切分（每个 title 独立成一个文件）。"""

import csv
from pathlib import Path

from ..constants import DEFAULT_TITLE_COL
from ..utils import detect_encoding
from .split_by_title import sanitize_sheet_name, save_split_workbook


def split_by_title_each(csv_path, title_col=DEFAULT_TITLE_COL, overwrite=True, log=print):
    """CSV 按 title 切分：每个不同的 title 值独立写成一个 csv 文件。"""
    csv_path = Path(csv_path)

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

    # 按 title 值分组，保持组内原始顺序
    groups = {}
    for r in rows:
        groups.setdefault(r[ti], []).append(r)

    stem = csv_path.stem
    outdir = csv_path.parent
    out_folder = outdir / f"{stem}_按title拆分"
    out_folder.mkdir(exist_ok=True)

    outputs = []
    used_names = {}
    for title, group in groups.items():
        name = sanitize_sheet_name(title)
        count = used_names.get(name, 0)
        used_names[name] = count + 1
        if count:
            name = f"{name}_{count + 1}"
        out_path = out_folder / f"{name}.csv"
        if not overwrite and out_path.exists():
            out_path = out_folder / f"{name}_新.csv"
        save_split_workbook(out_path, header, group)
        outputs.append(out_path)
        log(f"[完成] {out_path.name} -> {len(group)} 行")

    log(f"[完成] {csv_path.name}：共 {len(rows)} 行 / {len(groups)} 个 title，已按 title 各写一个文件")
    return {
        "file": csv_path,
        "total": len(rows),
        "groups": len(groups),
        "parts": len(groups),
        "outputs": outputs,
    }
