"""准备输出路径，读取单表或合并目录内十字段表。"""
from common.atomic_io import replace_file
from dataclasses import dataclass
from pathlib import Path
import hashlib
import re
import pandas as pd


@dataclass(frozen=True)
class OutputPaths:
    # 本阶段所有产物的落盘位置：合并表、原价表、匹配表、未用价清单，供后续步骤复用
    base_dir: Path
    merged: Path
    raw: Path
    matched: Path
    unused: Path


def run(input_file, stop=None):
    # 输入既可以是目录（合并其下所有十字段表），也可以是单个表文件
    input_path = Path(input_file)
    if not input_path.exists():
        raise ValueError(f"输入不存在：{input_path}\n"
                         f"（INPUT_FILE 可给目录——合并目录下所有 *.csv；也可给单个表文件）")

    if input_path.is_dir():
        # 目录模式：源即该 CSV 目录；输出基准目录取 CSV 的上一级（名字用于产物命名）
        source_dir = input_path
        base_dir = input_path.parent if input_path.name.lower() == "csv" else input_path
        merged_name = f"{base_dir.name}_合并.csv"
        suffix = ".csv"
    else:
        # 单文件模式：直接把该文件当合并结果，仍按 CSV 上级建目录结构
        source_dir = input_path.parent
        base_dir = input_path.parent.parent if input_path.parent.name.lower() == "csv" else input_path.parent
        merged_name = input_path.name
        suffix = input_path.suffix

    # 原价 / 价格匹配两个子目录分开存放，互不覆盖。
    # 这里只算路径不建目录：对应流程没勾选时不该留下空目录，写文件时由 replace_file 补建。
    raw_dir = base_dir / "原价"
    match_dir = base_dir / "价格匹配"

    merged_path = source_dir / merged_name
    stem = Path(merged_name).stem
    raw_path = raw_dir / f"{stem}_原价{suffix}"
    output_path = match_dir / f"{stem}_价格匹配{suffix}"

    if input_path.is_dir():
        print('#' * 110)
        print(f'合并十字段表：{source_dir}')
        print('#' * 110)
        # 排除项：已存在的合并表与本目录规范名表，避免把上轮产物再并入造成重复
        excluded_paths = {merged_path.resolve(),
                          (source_dir / f"{base_dir.name}_style.csv").resolve()}
        # 递归收集所有十字段表：兼容切分后「每份一个文件夹，内分 csv/」的嵌套结构。
        # 阶段四自己的产物目录（原价/ 价格匹配/）与 json 目录里的内容要排除，避免重复并入。
        skip_dirs = {"原价", "价格匹配", "json"}
        # 切分产物优先：目录里存在阶段 03.1 的切分产物（<域名>_style_N/ 或 <域名>_style_按title拆分/）
        # 时，只收集切分产物，跳过根目录的原表 _style.csv，避免同一批商品被原表与切分产物重复并入。
        has_split_products = any(
            d.is_dir() and re.match(r".*_style_(\d+|按title拆分)$", d.name)
            for d in source_dir.iterdir()
        )
        tables = sorted(
            p for p in source_dir.rglob("*.csv")
            if p.is_file()
            and p.resolve() not in excluded_paths
            and not p.name.startswith(("~$", "."))
            and not any(part.lower() in skip_dirs for part in p.relative_to(source_dir).parts[:-1])
            # 有切分产物时，跳过直接位于 source_dir 根目录下的原表 _style.csv
            and not (has_split_products and p.parent == source_dir and p.name.endswith("_style.csv"))
        )
        if not tables:
            raise ValueError(f"目录里没有可合并的 csv：{source_dir}")
        frames, first_name, first_cols = [], "", ()
        for t in tables:
            if stop is not None and stop.is_set():
                print('合并已停止，保留已读入的表', flush=True)
                break
            part = pd.read_csv(t, dtype=str, keep_default_na=False)
            print(f"  {t.name}: {len(part)} 行")
            # 记录首表列名作为基准；后续表列不一致时按列名合并、缺失列自动留空
            if not frames:
                first_name, first_cols = t.name, tuple(part.columns)
            elif tuple(part.columns) != first_cols:
                print(f"  [警告] {t.name} 的列与 {first_name} 不一致，按列名合并（缺失列留空）")
            frames.append(part)
        if not frames:
            raise ValueError(f"停止于合并开始之前，没有可读入的表：{source_dir}")
        # concat 按列名对齐合并，ignore_index 重排行号；合并表在补算 md5 之后统一写盘
        df = pd.concat(frames, ignore_index=True)
        print(f"\n{len(frames)} 张表 → {len(df)} 行")
    else:
        df = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    df = df.reset_index(drop=True)
    # 补齐 md5：旧表可能没有 md5 列或个别行为空，统一用 link-href（商品链接）的 md5 补算，
    # 保证合并产物每一行都带「链接的 md5」，阶段四据此确定性生成 SKU，避免空 md5 导致 SKU 碰撞。
    df = _ensure_link_md5(df)
    # 价格列强制 object：保留原值类型，避免 NaN 把整数列提升为 float 影响后续判定
    for price_column in ('price1', 'price2'):
        if price_column in df.columns:
            df[price_column] = df[price_column].astype(object)
    # 合并表（含补齐后的 md5）统一落盘：目录模式与单文件模式都在此写回
    replace_file(merged_path, lambda path: df.to_csv(path, index=False, encoding='utf-8-sig'), ".csv")
    print(f"已保存合并表: {merged_path}")
    return df, OutputPaths(base_dir, merged_path, raw_path, output_path, match_dir / f"{stem}_未匹配到的价格.csv")


def _ensure_link_md5(df: pd.DataFrame) -> pd.DataFrame:
    # 补齐每行的 md5：优先用已有 md5，缺失/空值时用 link-href 的 md5(url) 派生。
    # link-href 列缺失时退回 src_links 首段，仍取不到才置空。
    if 'md5' not in df.columns:
        df['md5'] = ''  # 旧表缺列，先建空列再逐行补
    if 'link-href' not in df.columns:
        link_col = 'src_links' if 'src_links' in df.columns else None
    else:
        link_col = 'link-href'

    def _url_md5(link: str) -> str:
        link = (link or '').strip()
        return hashlib.md5(link.encode('utf-8')).hexdigest() if link else ''

    filled = 0
    for i in range(len(df)):
        md5_val = str(df.at[i, 'md5'] or '').strip()
        if md5_val:
            continue
        raw_link = ''
        if link_col and link_col in df.columns:
            raw_link = str(df.at[i, link_col] or '').strip()
            if link_col == 'src_links':  # src_links 是 '#' 分隔的图片列表，取首段非空链接兜底
                raw_link = next((seg for seg in raw_link.split('#') if seg.strip()), '')
        df.at[i, 'md5'] = _url_md5(raw_link)
        if df.at[i, 'md5']:
            filled += 1
    if filled:
        print(f"  已为 {filled} 行补齐链接 md5", flush=True)
    return df
