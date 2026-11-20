# -*- coding: utf-8 -*-
"""功能 3：SKU 查重。"""

from pathlib import Path

from ..utils import read_csv_rows


def sku_check(input_file, log):
    input_path = Path(input_file)
    rows, encoding = read_csv_rows(input_path)
    sku_rows = {}
    for line_no, row in enumerate(rows, start=2):
        sku = row.get("SKU", "").strip()
        if sku:
            sku_rows.setdefault(sku, []).append(
                (line_no, row.get("Type", ""), row.get("Name", ""), row.get("Parent", "")))

    duplicates = {sku: entries for sku, entries in sku_rows.items() if len(entries) > 1}
    parent_count = sum(1 for row in rows if row.get("Type", "") in ("variable", "simple"))
    variation_count = sum(1 for row in rows if row.get("Type", "") == "variation")
    parent_skus = {row.get("SKU", "").strip() for row in rows if row.get("Type", "") in ("variable", "simple")}
    orphans = [
        (line_no, row)
        for line_no, row in enumerate(rows, start=2)
        if row.get("Type", "") == "variation" and row.get("Parent", "").strip() not in parent_skus
    ]

    log(f"读取编码: {encoding}")
    log(f"总行数: {len(rows)}")
    log(f"variable/simple: {parent_count}，variation: {variation_count}")
    log(f"SKU 总数: {sum(len(v) for v in sku_rows.values())}，唯一 SKU 数: {len(sku_rows)}")
    log(f"重复 SKU 数: {len(duplicates)}，孤立变体数: {len(orphans)}")

    if duplicates:
        log("\n重复 SKU 明细:")
        for sku, entries in sorted(duplicates.items()):
            log(f"  SKU {sku} 出现 {len(entries)} 次")
            for line_no, row_type, name, parent in entries[:10]:
                parent_text = f", Parent={parent}" if parent else ""
                log(f"    行 {line_no}: Type={row_type}, Name={name[:60]}{parent_text}")
    else:
        log("没有发现重复 SKU。")

    if orphans:
        log("\n孤立变体明细:")
        for line_no, row in orphans[:20]:
            log(f"  行 {line_no}: SKU={row.get('SKU', '')}, Parent={row.get('Parent', '')}, Name={row.get('Name', '')[:60]}")
        if len(orphans) > 20:
            log(f"  还有 {len(orphans) - 20} 条未显示。")
    return None
