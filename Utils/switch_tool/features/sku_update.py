# -*- coding: utf-8 -*-
"""功能 4：SKU 更新（重新生成父/子 SKU）。"""

import csv
from pathlib import Path

from ..utils import read_csv_rows, output_with_suffix, generate_variant_sku, generate_parent_sku


def sku_update(input_file, log):
    input_path = Path(input_file)
    rows, encoding = read_csv_rows(input_path)
    if not rows:
        raise ValueError("文件中没有数据行。")
    fieldnames = list(rows[0].keys())
    old_to_new_parent = {}
    used_skus = set()
    parent_count = 0
    variation_count = 0

    for row in rows:
        row_type = row.get("Type", "").strip()
        if row_type in ("variable", "simple"):
            old_sku = row.get("SKU", "")
            handle = row.get("Name", "").strip()
            new_sku = generate_parent_sku(handle, used_skus=used_skus)
            row["SKU"] = new_sku
            old_to_new_parent[old_sku] = new_sku
            parent_count += 1
        elif row_type == "variation":
            row["SKU"] = generate_variant_sku(used_skus)
            old_parent = row.get("Parent", "").strip()
            if old_parent in old_to_new_parent:
                row["Parent"] = old_to_new_parent[old_parent]
            variation_count += 1

    output_path = output_with_suffix(input_path, "_新SKU", ".csv")
    with open(output_path, "w", encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log(f"已生成新 SKU 文件: {output_path}")
    log(f"更新父商品 SKU: {parent_count}，变体 SKU: {variation_count}")
    log(f"唯一 SKU 数: {len(used_skus)}")
    return output_path
