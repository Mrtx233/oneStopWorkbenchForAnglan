# -*- coding: utf-8 -*-
"""通用工具：单元格清洗、编码探测、价格解析、SKU 生成、styles 转义。"""

import csv
import hashlib
import random
import string
from pathlib import Path

import pandas as pd

from .constants import STYLE_RESERVED


# ── 单元格 / 路径 ──

def clean_cell(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def strip_quotes(path):
    """去除路径两端可能包裹的引号（用户粘贴路径时可能带有引号）。"""
    path = str(path).strip()
    if len(path) >= 2 and (
            (path[0] == '"' and path[-1] == '"') or (path[0] == "'" and path[-1] == "'")
    ):
        path = path[1:-1].strip()
    return path


def detect_encoding(path):
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                f.read(2048)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8-sig"


def read_table(path):
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path, encoding=detect_encoding(path))


def output_with_suffix(input_path, suffix, extension=None):
    input_path = Path(input_path)
    ext = extension or input_path.suffix
    return input_path.with_name(f"{input_path.stem}{suffix}{ext}")


# ── 价格 ──

def parse_price(value):
    """把价格（字符串或数字）转成 float，无法解析返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("$", "").replace("￥", "").replace("¥", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def price_sort_key(value):
    """价格升序，无法解析的值排到末尾。"""
    price = parse_price(value)
    return (price is None, price if price is not None else 0.0)


def read_csv_rows(path):
    encoding = detect_encoding(path)
    with open(path, encoding=encoding, newline="") as f:
        return list(csv.DictReader(f)), encoding


# ── SKU 生成 ──

def generate_variant_sku(used_skus=None):
    while True:
        first_digit = random.choice("123456789")
        digits1 = "".join(random.choices(string.digits, k=2))
        letters1 = "".join(random.choices(string.ascii_uppercase, k=2))
        letter1 = random.choice(string.ascii_uppercase)
        digits2 = "".join(random.choices(string.digits, k=2))
        letters2 = "".join(random.choices(string.ascii_uppercase, k=2))
        digits3 = "".join(random.choices(string.digits, k=3))
        sku = f"{first_digit}{digits1}{letters1}-{letter1}{digits2}{letters2}-{digits3}{letters1}"
        if used_skus is None or sku not in used_skus:
            if used_skus is not None:
                used_skus.add(sku)
            return sku


def generate_parent_sku(handle="", counter=0, used_skus=None):
    """基于商品 Handle 生成确定性 parent SKU，同一 Handle 始终返回相同 SKU。"""
    while True:
        hash_input = f"{handle}_{counter}" if handle else str(counter)
        h = hashlib.md5(hash_input.encode()).hexdigest()
        digits = "".join(c for c in h if c.isdigit())
        if len(digits) < 8:
            digits = (digits + "0" * 8)[:8]
        sku = f"SKU{digits[:8]}"
        if used_skus is None or sku not in used_skus:
            if used_skus is not None:
                used_skus.add(sku)
            return sku
        counter += 1


# ── styles 转义 ──

def style_escape(value):
    """转义选项值/选项名里的保留分隔符（\\ & # @）；不含则原样返回。"""
    if value is None:
        return ""
    text = str(value)
    if not any(ch in text for ch in STYLE_RESERVED):
        return text
    return (text.replace("\\", "\\\\")
                .replace("&", "\\&")
                .replace("#", "\\#")
                .replace("@", "\\@"))


def split_unescaped(text, sep):
    """按未转义的 sep 切分（\\& \\# \\@ \\\\ 视为字面量，不参与切分）。"""
    parts = []
    buf = []
    escaped = False
    for ch in text:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            buf.append(ch)
            escaped = True
        elif ch == sep:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def last_unescaped_index(text, sep):
    """返回最后一个未转义 sep 的下标，没有则返回 -1。"""
    found = -1
    escaped = False
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == sep:
            found = i
    return found


def format_price(value):
    """styles 用：数值去掉多余的 .0，非数值原样返回，空值返回 '0'。"""
    text = clean_cell(value)
    if not text:
        return "0"
    try:
        number = float(text)
        return str(int(number)) if number == int(number) else str(number)
    except ValueError:
        return text
