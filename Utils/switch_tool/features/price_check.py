# -*- coding: utf-8 -*-
"""功能 1：WP 价格检查。"""

from pathlib import Path

import pandas as pd

from ..constants import PRICE_LIBRARY
from ..utils import read_table


def price_check(input_file, log):
    input_path = Path(input_file)
    df = read_table(input_path)

    sale_col = None
    regular_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if "sale" in col_lower and "price" in col_lower:
            sale_col = col
        if "regular" in col_lower and "price" in col_lower:
            regular_col = col

    if not sale_col or not regular_col:
        raise ValueError(f"未找到 Sale price 或 Regular price 列。当前列: {df.columns.tolist()}")

    extracted_prices = []
    for _, row in df.iterrows():
        sale_price = pd.to_numeric(row[sale_col], errors="coerce")
        regular_price = pd.to_numeric(row[regular_col], errors="coerce")
        if pd.notna(sale_price):
            extracted_prices.append(round(float(sale_price), 2))
        elif pd.notna(regular_price):
            extracted_prices.append(round(float(regular_price), 2))

    missing_prices = sorted([price for price in set(PRICE_LIBRARY) if price not in set(extracted_prices)])

    log(f"读取: {input_path}")
    log(f"使用价格列: {sale_col} / {regular_col}")
    for price in missing_prices:
        log(f"{price:.2f}")
    log("-" * 50)
    log(f"{len(missing_prices)} 个")
    return None
