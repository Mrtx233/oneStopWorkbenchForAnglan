# -*- coding: utf-8 -*-
"""功能 7：图片链接精简（按 styles1 精简 src_links 列）。"""

import shutil
from pathlib import Path

import openpyxl

from ..constants import SRC_ONLY_KEEP, SLIM_SUFFIX
from ..utils import clean_cell, strip_quotes, split_unescaped, last_unescaped_index
from .split_by_title import collect_xlsx_files, save_workbook


def extract_style_images(styles_value):
    """提取 styles1 各变体段 @ 后的图片链接，按出现顺序去重返回。"""
    text = clean_cell(styles_value)
    if not text:
        return []
    images = []
    seen = set()
    for segment in split_unescaped(text, "#"):
        pos = last_unescaped_index(segment, "@")
        if pos < 0:
            continue
        url = segment[pos + 1:].strip()
        if url and url not in seen:
            seen.add(url)
            images.append(url)
    return images


def split_src_links(src_value):
    """src_links 按 # 拆分（图片链接不参与转义），保持原顺序。"""
    return [url.strip() for url in clean_cell(src_value).split("#") if url.strip()]


def slim_src_links(styles_value, src_value, keep=SRC_ONLY_KEEP):
    """精简 src_links：styles1 未引用的保留前 keep 张，被引用的全部保留。

    返回 (新 src_links, 原图片数, 精简后图片数)。
    """
    referenced = set(extract_style_images(styles_value))
    src_list = split_src_links(src_value)
    src_only = [url for url in src_list if url not in referenced]
    shared = [url for url in src_list if url in referenced]
    kept = src_only[:keep] + shared
    return "#".join(kept), len(src_list), len(kept)


def slim_src_links_xlsx(xlsx_path, keep=SRC_ONLY_KEEP, overwrite=True, log=print):
    """按 styles1 精简 xlsx 的 src_links 列；覆盖原文件时先备份为 .bak。"""
    xlsx_path = Path(xlsx_path)
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    header = [clean_cell(cell.value) for cell in ws[1]]
    for column in ("styles1", "src_links"):
        if column not in header:
            wb.close()
            log(f"[跳过] 缺少「{column}」列：{xlsx_path.name}")
            return None

    styles_idx = header.index("styles1") + 1
    src_idx = header.index("src_links") + 1

    rows = changed = before_total = after_total = 0
    for row_no in range(2, ws.max_row + 1):
        styles_value = ws.cell(row=row_no, column=styles_idx).value
        src_cell = ws.cell(row=row_no, column=src_idx)
        new_links, before, after = slim_src_links(styles_value, src_cell.value, keep)
        rows += 1
        before_total += before
        after_total += after
        if new_links != clean_cell(src_cell.value):
            src_cell.value = new_links
            changed += 1

    if overwrite:
        output_path = xlsx_path
        backup_path = Path(f"{xlsx_path}.bak")
        try:
            shutil.copy2(xlsx_path, backup_path)
        except PermissionError:
            wb.close()
            raise PermissionError(f"备份失败，文件被其他程序占用（如 Excel）：{xlsx_path}") from None
        log(f"已备份原文件: {backup_path.name}")
    else:
        output_path = xlsx_path.with_name(f"{xlsx_path.stem}{SLIM_SUFFIX}{xlsx_path.suffix}")

    save_workbook(wb, output_path)
    wb.close()

    log(f"[完成] {xlsx_path.name}：{rows} 行，改写 {changed} 行，"
        f"图片 {before_total} -> {after_total} 张 -> {output_path.name}")
    return {
        "file": xlsx_path,
        "rows": rows,
        "changed": changed,
        "before": before_total,
        "after": after_total,
        "output": output_path,
    }


def slim_src_links_target(target, keep=SRC_ONLY_KEEP, overwrite=True, log=print):
    """适配 GUI 的包装：target 可以是单个 xlsx 或一个文件夹（递归收集）。"""
    files = collect_xlsx_files(target)
    if not files:
        raise ValueError(f"未找到 xlsx 文件: {target}")

    mode_text = "覆盖原文件，自动备份 .bak" if overwrite else f"另存为 {SLIM_SUFFIX} 后缀"
    log(f"开始处理 {len(files)} 个文件（{mode_text}）")
    log("-" * 60)

    total_rows = total_changed = total_before = total_after = failed = 0
    for path in files:
        try:
            stat = slim_src_links_xlsx(path, keep=keep, overwrite=overwrite, log=log)
        except Exception as exc:
            failed += 1
            log(f"[失败] {path.name}：{exc}")
            continue
        if stat:
            total_rows += stat["rows"]
            total_changed += stat["changed"]
            total_before += stat["before"]
            total_after += stat["after"]

    log("-" * 60)
    summary = (f"处理完成：{len(files) - failed} 个文件，共 {total_rows} 行，"
               f"改写 {total_changed} 行，图片 {total_before} -> {total_after} 张")
    if failed:
        summary += f"，失败 {failed} 个"
    log(summary)

    return Path(strip_quotes(target))
