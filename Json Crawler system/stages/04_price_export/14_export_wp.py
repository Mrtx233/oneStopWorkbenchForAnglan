"""第四步：十字段表（style）直接转 WooCommerce CSV，不再经由 Shopify 中间格式。

输入为阶段 04 产出的原价表 / 匹配表（.csv），列契约与阶段 03 CSV_FIELDS 一致：
title, name, price1, price2, styles1, styles2, styles3, src_links, link-href, details, md5。
styles2/styles3 为占位列，不参与转换，输入可省略。

styles1 结构：`首列属性名#组合1#组合2#...`，每个组合片段为
`首值&属性名2&值2&属性名3&值3$售价$原价@图片`（styles2/styles3 阶段 03 固定留空，
所有维度都塞在 styles1 里，用 & 连接名值对）。

对每张表逐商品完成：选项维度展开 → 派生子/父 SKU → 聚合 WP 商品树 → 写 WP CSV。
输出文件名 wp-<源文件名>.csv，与源表同目录。
"""
import csv
import hashlib
import string
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from common import styles_codec
from common.atomic_io import replace_file
from url_utils import normalize_url_dashes


_SKU_ALPHABET = string.digits + string.ascii_uppercase  # 0-9 + A-Z，共 36 个字符


def deterministic_parent_sku(product_md5, used_skus):
    # 父商品 SKU：由「商品 md5 + 计数器」确定性派生，格式 SKU+8位数字。
    # md5 取其中数字补足 8 位；碰撞时递增计数器重算。
    counter = 0
    while True:
        seed = f"{product_md5 or ''}:{counter}"
        h = hashlib.md5(seed.encode('utf-8')).hexdigest()
        digits = "".join(c for c in h if c.isdigit())
        if len(digits) < 8:
            digits = (digits + "0" * 8)[:8]
        sku = f"SKU{digits[:8]}"
        if sku not in used_skus:
            used_skus.add(sku)
            return sku
        counter += 1


def deterministic_variant_sku(product_md5, variant_index):
    # 变体 SKU：由「商品 md5 + 变体序号」确定性派生，格式 5-5-5（数字+大写字母）。
    # 首字符固定为数字且非 0（1-9），其余 14 位用 36 进制（0-9 + A-Z）。
    seed = f"{product_md5 or ''}:{variant_index}"
    digest = hashlib.md5(seed.encode('utf-8')).hexdigest()
    n = int(digest, 16)
    chars = [string.digits[n % 9 + 1]]  # 首字符从 1-9 里取，保证非 0 开头且不以字母开头
    n //= 9
    for _ in range(14):
        chars.append(_SKU_ALPHABET[n % 36])
        n //= 36
    code = ''.join(chars)
    return f"{code[0:5]}-{code[5:10]}-{code[10:15]}"


def _split_styles(value):
    # styles 按 '#' 切段（只切未转义分隔符）；兼容旧数据 '$' 开头缺属性名前导
    if pd.isna(value):
        return ['']
    text = str(value)
    if text.startswith('$'):
        text = '#' + text
    return styles_codec.split(text, '#')


def _clean_option_name(raw):
    # WP 属性名清洗：占位名 'Title' 或以 '$' 开头（旧数据脏值）视为无属性
    raw = str(raw or '')
    if raw == 'Title' or raw.startswith('$'):
        return ''
    return raw


def WPTitle(opt1, opt2, opt3):
    # 由三档选项值拼 WP 子变体名后缀：Option1 用 '-'、Option2/3 用 ',' 分隔，缺档即止
    title = ''
    if opt1:
        title += "-" + opt1
        if opt2:
            title += "," + opt2
            if opt3:
                title += "," + opt3
    return title


def WPAdd(value, obj):
    # 把 value 追加进逗号列表 obj：跳过空值与已存在项，用于父商品汇总图片/选项值
    if value != "" and value not in obj.split(','):
        obj = value if obj == "" else obj + "," + value
    return obj


def _export_prices(sale, compare):
    """有有效划线价时 Sale=售价、Regular=划线价；无优惠时售价写 Regular、Sale 留空。"""
    try:
        current, original = Decimal(str(sale)), Decimal(str(compare))
        paired = current.is_finite() and original.is_finite() and 0 < current <= original
    except (InvalidOperation, ValueError):
        paired = False
    return (sale, compare) if paired else ('', sale)


def _wp_header():
    # WooCommerce 产品导入器列头（顺序固定，导入器按此识别）
    return ["Type", "SKU", "Name", "Published", "Visibility in catalog", "Description",
            "In stock?", "Stock", "Sale price", "Regular price", "Categories", "Images",
            "Parent", "Position", "Attribute 1 name", "Attribute 1 value(s)",
            "Attribute 1 visible", "Attribute 1 global", "Attribute 2 name",
            "Attribute 2 value(s)", "Attribute 2 visible", "Attribute 2 global",
            "Attribute 3 name", "Attribute 3 value(s)", "Attribute 3 visible",
            "Attribute 3 global"]


def _to_float(value):
    # 安全转 float，空/非法返回 None
    try:
        if value is None or value == '' or (isinstance(value, float) and pd.isna(value)):
            return None
        f = float(value)
        return f if f == f else None  # 排除 NaN
    except (TypeError, ValueError):
        return None


def convert_to_wp(input_file_name, output_file_name):
    """读一张 style 表，逐商品展开并聚合为 WP 商品树，写入 wp-*.csv。"""
    print(f"读取：{input_file_name}", flush=True)
    input_df = pd.read_csv(input_file_name, dtype=str, keep_default_na=False)

    required = ['title', 'name', 'price1', 'price2', 'details', 'src_links',
                'styles1']
    if not all(col in input_df.columns for col in required):
        raise ValueError(f"输入文件缺少必要的列：{input_file_name}")

    has_md5 = 'md5' in input_df.columns
    priced_flags = (input_df['定价状态'].isin(('已匹配', '原价', '低价'))
                    if '定价状态' in input_df.columns
                    else pd.Series([False] * len(input_df)))

    rows = []
    used_parent_skus = set()
    total = len(input_df)

    for idx in range(total):
        name = str(input_df.at[idx, 'name'] or '').strip()
        title = str(input_df.at[idx, 'title'] or '').strip()
        details = str(input_df.at[idx, 'details'] or '')
        collection = title  # Categories 取自分类标题
        md5 = str(input_df.at[idx, 'md5'] or '').strip() if has_md5 else ''

        main_price1 = input_df.at[idx, 'price1']
        main_price2 = input_df.at[idx, 'price2']
        priced = bool(priced_flags.at[idx])

        # 图片列表：src_links 以 '#' 分隔，破折号归一化，去重保序汇总到父商品
        raw_srcs = str(input_df.at[idx, 'src_links'] or '')
        images = ""
        for src in raw_srcs.split('#'):
            src = normalize_url_dashes(src)
            if src:
                images = WPAdd(src, images)

        # 三档：Option1 Name 取自 styles1 首段；Option1 Value 是各组合片段；
        # styles2/styles3 阶段 03 固定空，Option2/Option3 的名值从 styles1 组合片段的 & 名值对里拆出
        style_parts = _split_styles(input_df.at[idx, 'styles1'])
        opt1_name = _clean_option_name(styles_codec.unescape(style_parts[0]))
        o1_segments = style_parts[1:] or ['']

        # 展开：每个组合片段解码出 (首值, 属性名2, 值2, 属性名3, 值3, ...) 与价格、图片
        variants = []
        for seg in o1_segments:
            values, sale, compare, image = styles_codec.decode_segment(seg)
            opt1_value = values[0] if len(values) > 0 else ''
            opt2_name = values[1] if len(values) > 1 else ''
            opt2_value = values[2] if len(values) > 2 else ''
            opt3_name = values[3] if len(values) > 3 else ''
            opt3_value = values[4] if len(values) > 4 else ''
            sale = sale or main_price1
            # 已定价/保留原价段里的空划线价是明确的“无折扣”，不再回退制造划线价
            compare = compare or ('' if priced else main_price2)
            variants.append({
                'opt1_value': opt1_value, 'opt2_name': opt2_name, 'opt2_value': opt2_value,
                'opt3_name': opt3_name, 'opt3_value': opt3_value,
                'sale': _to_float(sale), 'compare': _to_float(compare),
                'image': normalize_url_dashes(image) if image else '',
            })

        # 判定是否有真实选项：任一变体有非空的首值即视为有维度
        has_real_option = any(v['opt1_value'] or v['opt2_value'] or v['opt3_value']
                              for v in variants)

        if not has_real_option:
            # 单值商品：simple，SKU 直接沿用确定性派生的变体 SKU
            variant_sku = deterministic_variant_sku(md5, 0)
            first = variants[0] if variants else {'sale': None, 'compare': None}
            sale_str, reg_str = _export_prices(first['sale'] or '', first['compare'] or '')
            entity = {
                "Type": "simple", "SKU": variant_sku, "Name": name, "Published": "1",
                "Visibility in catalog": "visible", "Description": details,
                "In stock?": "1", "Stock": "99999",
                "Sale price": sale_str, "Regular price": reg_str,
                "Categories": collection, "Images": images,
                "Parent": "", "Position": "0",
                "Attribute 1 name": "", "Attribute 1 value(s)": "",
                "Attribute 1 visible": "", "Attribute 1 global": "",
                "Attribute 2 name": "", "Attribute 2 value(s)": "",
                "Attribute 2 visible": "", "Attribute 2 global": "",
                "Attribute 3 name": "", "Attribute 3 value(s)": "",
                "Attribute 3 visible": "", "Attribute 3 global": "",
            }
            rows.append(entity)
            continue

        # 有真实选项：variable 父实体 + 逐个 variation 子变体
        parent_sku = deterministic_parent_sku(md5, used_parent_skus)
        parent = {
            "Type": "variable", "SKU": parent_sku, "Name": name, "Published": "1",
            "Visibility in catalog": "visible", "Description": details,
            "In stock?": "1", "Stock": "99999",
            "Sale price": "", "Regular price": "", "Categories": collection,
            "Images": images, "Parent": "", "Position": "0",
            "Attribute 1 name": opt1_name,
            "Attribute 1 value(s)": "",
            "Attribute 1 visible": "1" if opt1_name else "",
            "Attribute 1 global": "1" if opt1_name else "",
            "Attribute 2 name": "", "Attribute 2 value(s)": "",
            "Attribute 2 visible": "", "Attribute 2 global": "",
            "Attribute 3 name": "", "Attribute 3 value(s)": "",
            "Attribute 3 visible": "", "Attribute 3 global": "",
        }
        rows.append(parent)
        parent_index = len(rows) - 1

        for i, v in enumerate(variants):
            sale_str, reg_str = _export_prices(v['sale'] or '', v['compare'] or '')
            # Option2/Option3 属性名取本变体段内解析出的名（首个变体非空时定父级属性名）
            if v['opt2_name'] and not parent["Attribute 2 name"]:
                parent["Attribute 2 name"] = _clean_option_name(v['opt2_name'])
                parent["Attribute 2 visible"] = "1"
                parent["Attribute 2 global"] = "1"
            if v['opt3_name'] and not parent["Attribute 3 name"]:
                parent["Attribute 3 name"] = _clean_option_name(v['opt3_name'])
                parent["Attribute 3 visible"] = "1"
                parent["Attribute 3 global"] = "1"
            variation = {
                "Type": "variation", "SKU": deterministic_variant_sku(md5, i),
                "Name": parent["Name"] + WPTitle(v['opt1_value'], v['opt2_value'], v['opt3_value']),
                "Published": "1", "Visibility in catalog": "visible", "Description": "",
                "In stock?": "1", "Stock": "99999",
                "Sale price": sale_str, "Regular price": reg_str,
                "Categories": collection, "Images": v['image'],
                "Parent": parent_sku, "Position": str(len(rows) - parent_index),
                "Attribute 1 name": parent["Attribute 1 name"],
                "Attribute 1 value(s)": v['opt1_value'],
                "Attribute 1 visible": "", "Attribute 1 global": "1" if v['opt1_value'] else "",
                "Attribute 2 name": parent["Attribute 2 name"],
                "Attribute 2 value(s)": v['opt2_value'],
                "Attribute 2 visible": "", "Attribute 2 global": "1" if v['opt2_value'] else "",
                "Attribute 3 name": parent["Attribute 3 name"],
                "Attribute 3 value(s)": v['opt3_value'],
                "Attribute 3 visible": "", "Attribute 3 global": "1" if v['opt3_value'] else "",
            }
            # 汇总图片与选项值回父实体（去重）
            if v['image']:
                parent["Images"] = WPAdd(v['image'], parent["Images"])
            parent["Attribute 1 value(s)"] = WPAdd(v['opt1_value'], parent["Attribute 1 value(s)"])
            parent["Attribute 2 value(s)"] = WPAdd(v['opt2_value'], parent["Attribute 2 value(s)"])
            parent["Attribute 3 value(s)"] = WPAdd(v['opt3_value'], parent["Attribute 3 value(s)"])
            rows.append(variation)

        if (idx + 1) % 25 == 0 or idx + 1 == total:
            print(f'展开进度：{idx + 1}/{total} 个商品，{len(rows)} 行', flush=True)

    # 原子写出 WP CSV
    target = Path(output_file_name)
    header = _wp_header()

    def _write(path):
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, '') for k in header})

    replace_file(target, _write, '.csv')
    print(f'WP文件 {target} 已生成！')


def check_wp_skus(input_file_name):
    """检查 WP CSV 中的 SKU 重复和孤立 variation，不修改导出文件。"""
    path = Path(input_file_name)
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))

    sku_rows = {}
    for line_no, row in enumerate(rows, start=2):
        sku = str(row.get('SKU', '') or '').strip()
        if sku:
            sku_rows.setdefault(sku, []).append((
                line_no, row.get('Type', ''), row.get('Name', ''), row.get('Parent', ''),
            ))

    duplicates = {sku: entries for sku, entries in sku_rows.items() if len(entries) > 1}
    parent_skus = {
        str(row.get('SKU', '') or '').strip()
        for row in rows
        if row.get('Type', '') in ('variable', 'simple') and str(row.get('SKU', '') or '').strip()
    }
    orphans = [
        (line_no, row)
        for line_no, row in enumerate(rows, start=2)
        if row.get('Type', '') == 'variation'
        and str(row.get('Parent', '') or '').strip() not in parent_skus
    ]

    print(f'SKU查重：{path}', flush=True)
    print(f'总行数：{len(rows)}，SKU总数：{sum(len(v) for v in sku_rows.values())}，'
          f'唯一SKU数：{len(sku_rows)}', flush=True)
    print(f'重复SKU数：{len(duplicates)}，孤立变体数：{len(orphans)}', flush=True)
    if duplicates:
        print('重复SKU明细：', flush=True)
        for sku, entries in sorted(duplicates.items()):
            print(f'  SKU {sku} 出现 {len(entries)} 次', flush=True)
            for line_no, row_type, name, parent in entries[:10]:
                parent_text = f', Parent={parent}' if parent else ''
                print(f'    行 {line_no}: Type={row_type}, Name={str(name)[:60]}{parent_text}', flush=True)
            if len(entries) > 10:
                print(f'    还有 {len(entries) - 10} 条未显示。', flush=True)
    else:
        print('没有发现重复 SKU。', flush=True)
    if orphans:
        print('孤立变体明细：', flush=True)
        for line_no, row in orphans[:20]:
            print(f"  行 {line_no}: SKU={row.get('SKU', '')}, "
                  f"Parent={row.get('Parent', '')}, Name={str(row.get('Name', ''))[:60]}", flush=True)
        if len(orphans) > 20:
            print(f'  还有 {len(orphans) - 20} 条未显示。', flush=True)
    return {'duplicates': duplicates, 'orphans': orphans}


def run(sources):
    # 输入为若干 style 表（原价表 / 匹配表），逐个直接转 WP；产物名 wp-<源文件名 stem>.csv
    outputs = []
    print('第四步：style 直转 WooCommerce')
    for source in sources:
        source = Path(source)
        target = source.with_name(f"wp-{source.stem}.csv")
        convert_to_wp(str(source), str(target))
        outputs.append(target)
        print(f"已保存: {target}")
        check_wp_skus(target)
    return outputs
