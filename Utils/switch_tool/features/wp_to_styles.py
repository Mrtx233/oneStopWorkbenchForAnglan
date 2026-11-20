# -*- coding: utf-8 -*-
"""功能 2：WP 还原 styles（读 wp-*.csv，逆向还原成十字段表 xlsx）。"""

from pathlib import Path

import openpyxl

from ..constants import STYLES_HEADERS
from ..utils import read_csv_rows, strip_quotes, style_escape, format_price


def parse_wp_products(input_path):
    rows, _ = read_csv_rows(input_path)
    products = []
    sku_to_product = {}
    for row in rows:
        row_type = row.get("Type", "").strip()
        if row_type in ("variable", "simple"):
            product_data = {"parent": row, "variations": []}
            products.append(product_data)
            sku_to_product[row.get("SKU", "")] = product_data
        elif row_type == "variation":
            product_data = sku_to_product.get(row.get("Parent", "").strip())
            if product_data:
                product_data["variations"].append(row)
    return products


def build_styles_segment(variation):
    parts = [style_escape(variation.get("Attribute 1 value(s)", "") or "")]
    for name_key, value_key in (
            ("Attribute 2 name", "Attribute 2 value(s)"),
            ("Attribute 3 name", "Attribute 3 value(s)"),
    ):
        name = variation.get(name_key, "") or ""
        value = variation.get(value_key, "") or ""
        if name and value:
            parts.extend([style_escape(name), style_escape(value)])
    segment = (f"{'&'.join(parts)}"
               f"${format_price(variation.get('Sale price', ''))}"
               f"${format_price(variation.get('Regular price', ''))}")
    image = (variation.get("Images", "") or "").split(",")[0].strip()
    return f"{segment}@{image}" if image else segment


def reconstruct_styles_product(product_data):
    parent = product_data["parent"]
    variations = product_data["variations"]
    product_row = {header: "" for header in STYLES_HEADERS}
    product_row["name"] = parent.get("Name", "")
    product_row["details"] = parent.get("Description", "")
    product_row["title"] = parent.get("Categories", "")
    product_row["link-href"] = parent.get("Link-Href", "")

    if variations:
        product_row["price1"] = variations[0].get("Sale price", "")
        product_row["price2"] = variations[0].get("Regular price", "")
    else:
        product_row["price1"] = parent.get("Sale price", "")
        product_row["price2"] = parent.get("Regular price", "")

    option1_name = parent.get("Attribute 1 name", "")
    segments = [
        build_styles_segment(variation)
        for variation in variations
        if variation.get("Attribute 1 value(s)", "") not in ("", "Default Title")
    ]
    if option1_name and segments:
        product_row["styles1"] = f"{style_escape(option1_name)}#{'#'.join(segments)}"
    elif segments:
        product_row["styles1"] = "#".join(segments)

    images = [img.strip() for img in (parent.get("Images", "") or "").split(",") if img.strip()]
    product_row["src_links"] = "#".join(images)
    return product_row


def wp_to_styles(input_file, log):
    input_path = Path(strip_quotes(input_file))
    products = parse_wp_products(input_path)

    stem = input_path.stem
    if stem.startswith("wp-"):
        stem = stem[3:]
    output_path = input_path.parent / f"{stem}_styles.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = stem[:31]
    ws.append(STYLES_HEADERS)

    for product_data in products:
        product = reconstruct_styles_product(product_data)
        ws.append([product.get(header, "") for header in STYLES_HEADERS])

    wb.save(output_path)
    log(f"读取: {input_path}")
    log(f"解析到 {len(products)} 个商品")
    log(f"输出: {output_path} ({ws.max_row - 1} 行)")
    return output_path
