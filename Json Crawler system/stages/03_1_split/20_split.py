# ======================== 切分核心层 ========================
#
# 职责: 两种 CSV 切分算法 + 对应 JSON 同步切分，独立实现、不依赖 switch_gui.py。
#   split_by_title      —— 按 title 分组、按价格排序后，按「商品块(md5)」轮询分配到 N 份
#   split_by_title_each —— 每个不同的 title 值独立写成一个文件
#   split_json_by_md5   —— 按切分 CSV 各份的 md5 集合，从汇总 JSON 筛出对应商品对象
#
# 关键约定：同一 md5 的所有组合行始终落在同一份 CSV（不跨文件），
# 因此 JSON 同步时每个商品对象只归入一份，无重复。
# 依赖: config（00_config）、标准库。
# 禁止: 导入 tkinter / pandas / DrissionPage。
# ========================================================

import csv
import json
import re
from pathlib import Path

import config


# 检测 CSV 编码：优先 utf-8-sig，退回 gbk / latin-1（兼容历史产物）。
def _detect_encoding(path):
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                f.read(2048)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8-sig"


# 把价格（字符串或数字）转 float，无法解析返回 None。
def _parse_price(value):
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


# 价格升序，无法解析的值排到末尾。
def _price_sort_key(value):
    price = _parse_price(value)
    return (price is None, price if price is not None else 0.0)


# 把 title 值清洗成合法文件名：去掉 Windows 非法字符、控制字符、首尾空白与结尾点/空格。
def sanitize_sheet_name(text):
    if text is None:
        text = ""
    text = str(text).strip()
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\x00-\x1f]", "", text)
    text = text.rstrip(". ")
    return text if text else "未命名"


def _read_csv(path):
    """读 CSV，返回 (header, rows)；空文件返回 (None, [])。"""
    encoding = _detect_encoding(path)
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return None, []
        rows = list(reader)
    return header, rows


def _available_output_paths(paths, overwrite):
    """为一组关联文件选同一后缀，任一路径已占用就继续递增。"""
    paths = tuple(Path(path) for path in paths)
    if overwrite:
        return paths
    index = 0
    while True:
        suffix = "" if index == 0 else ("_新" if index == 1 else f"_新{index}")
        candidates = tuple(path.with_stem(path.stem + suffix) for path in paths)
        if not any(path.exists() for path in candidates):
            return candidates
        index += 1


def _write_csv(path, header, rows, overwrite=True):
    """按 utf-8 写出切分结果（与阶段三十字段表同编码约定）。"""
    with open(path, "w" if overwrite else "x", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _bucket_by_product(groups, price_index, parts, md5_index):
    """把按 title 分好的行，按「商品块(md5)」轮询分配到 parts 个桶。

    同一 md5 的所有行始终在同一桶（不跨文件）；商品块按价格排序后，用全局轮询计数
    依次分配到各桶，使各桶的商品数量尽量均匀。返回 [(bucket_rows, md5集合), ...]。
    """
    buckets = [[] for _ in range(parts)]
    buckets_md5 = [set() for _ in range(parts)]
    # 全局轮询计数：跨 title 组累加，避免每组都从桶 0 开始导致全部挤进第一份。
    counter = 0
    for rows in groups.values():
        # 先把行按 md5 聚成商品块，保持块内原始行顺序。
        blocks = []
        for r in rows:
            if blocks and blocks[-1][0] == _row_md5(r, md5_index):
                blocks[-1][1].append(r)
            else:
                blocks.append([_row_md5(r, md5_index), [r]])
        # 有价格列时，商品块按「块内第一条行的价格」排序（同商品价格一致，取首条即可）。
        if price_index is not None:
            blocks.sort(key=lambda b: _price_sort_key(b[1][0][price_index]))
        # 轮询分配商品块：全局计数 i%parts，同一 md5 的块内行整体进同一桶。
        for md5, block_rows in blocks:
            k = counter % parts
            counter += 1
            buckets[k].extend(block_rows)
            buckets_md5[k].add(md5)
    return list(zip(buckets, buckets_md5))


def _row_md5(row, md5_index):
    """按表头位置取商品标识，不依赖 md5 恰好是最后一列。"""
    return row[md5_index].strip() if md5_index is not None and md5_index < len(row) else ""


def split_by_title(csv_path, parts, title_col=config.DEFAULT_TITLE_COL,
                   price_col=config.DEFAULT_PRICE_COL, overwrite=True, log=print):
    """按 title_col 分组、按 price_col 排序后，按「商品块(md5)」轮询分配到 parts 个 CSV。

    同一 md5 的所有组合行不跨文件。返回统计 dict，失败返回 None。
    """
    csv_path = Path(csv_path)
    parts = max(1, int(parts))

    header, rows = _read_csv(csv_path)
    if header is None:
        log(f"[跳过] 空文件：{csv_path.name}")
        return None
    if title_col not in header:
        log(f"[跳过] 缺少「{title_col}」列：{csv_path.name}")
        return None

    ti = header.index(title_col)
    has_price = price_col in header
    if not has_price:
        log(f"[提示] 缺少「{price_col}」列，商品块保持原顺序：{csv_path.name}")
    pi = header.index(price_col) if has_price else None
    # md5 列用于商品块聚合；缺失时整块作为单商品（不聚块），保持旧行为。
    has_md5 = config.MD5_COL in header
    md5_index = header.index(config.MD5_COL) if has_md5 else None

    # 按 title 分组。
    groups = {}
    for r in rows:
        groups.setdefault(r[ti], []).append(r)

    # 若无 md5 列，退回旧行为：按行轮询（仍能均分，但无法保证商品不跨文件）。
    if not has_md5:
        buckets = [[] for _ in range(parts)]
        buckets_md5 = [set() for _ in range(parts)]
        for g in groups.values():
            for i, r in enumerate(g):
                buckets[i % parts].append(r)
        pairs = list(zip(buckets, buckets_md5))
    else:
        # 按商品块轮询（同一 md5 不跨文件）。
        pairs = _bucket_by_product(groups, pi, parts, md5_index)

    stem = csv_path.stem
    outdir = csv_path.parent
    outputs = []
    md5_sets = {}
    json_targets = {}
    for k, (bucket, md5_set) in enumerate(pairs, 1):
        part_name = f"{stem}_{k}"
        # 每一份一个子文件夹，内部再分 csv/ 与 json/。
        part_folder = outdir / part_name
        csv_dir = part_folder / "csv"
        json_dir = part_folder / "json"
        csv_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)
        out_path, json_path = _available_output_paths(
            (csv_dir / f"{part_name}.csv", json_dir / f"{part_name}.json"), overwrite)
        _write_csv(out_path, header, bucket, overwrite=overwrite)
        outputs.append(out_path)
        md5_sets[str(out_path)] = md5_set
        json_targets[str(out_path)] = json_path
        log(f"[完成] {out_path.name} -> {len(bucket)} 行 / {len(md5_set)} 个商品")

    log(f"[完成] {csv_path.name}：共 {len(rows)} 行 / {len(groups)} 组，拆分 {parts} 份")
    return {
        "file": csv_path,
        "total": len(rows),
        "groups": len(groups),
        "parts": parts,
        "outputs": outputs,
        "md5_sets": md5_sets,     # {输出CSV路径: 该份含有的md5集合}
        "json_targets": json_targets,     # {输出CSV路径: 该份JSON目标路径}
    }


def split_by_title_each(csv_path, title_col=config.DEFAULT_TITLE_COL,
                        overwrite=True, log=print):
    """按 title 切分：每个不同的 title 值独立写成一个 CSV 文件。

    同一 title 的行天然不跨文件（同一 md5 也只属于一个 title）。
    输出结构：<stem>_按title拆分/<分类>/csv/<分类>.csv，对应 JSON 放到
    <stem>_按title拆分/<分类>/json/<分类>.json（由 split_json_by_md5 按 json_targets 写入）。
    返回统计 dict，失败返回 None。
    """
    csv_path = Path(csv_path)

    header, rows = _read_csv(csv_path)
    if header is None:
        log(f"[跳过] 空文件：{csv_path.name}")
        return None
    if title_col not in header:
        log(f"[跳过] 缺少「{title_col}」列：{csv_path.name}")
        return None

    ti = header.index(title_col)
    has_md5 = config.MD5_COL in header
    md5_index = header.index(config.MD5_COL) if has_md5 else None

    # 按 title 值分组，保持组内原始顺序。
    groups = {}
    for r in rows:
        groups.setdefault(r[ti], []).append(r)

    stem = csv_path.stem
    outdir = csv_path.parent
    out_folder = outdir / f"{stem}{config.EACH_DIR_SUFFIX}"
    out_folder.mkdir(exist_ok=True)

    outputs = []
    md5_sets = {}
    json_targets = {}       # {csv路径: 目标json路径}
    used_names = {}
    for title, group in groups.items():
        name = sanitize_sheet_name(title)
        count = used_names.get(name, 0)
        used_names[name] = count + 1
        if count:
            name = f"{name}_{count + 1}"
        # 每个分类一个子文件夹，内部再分 csv/ 与 json/。
        cat_folder = out_folder / name
        csv_dir = cat_folder / "csv"
        json_dir = cat_folder / "json"
        csv_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)
        out_path, json_path = _available_output_paths(
            (csv_dir / f"{name}.csv", json_dir / f"{name}.json"), overwrite)
        _write_csv(out_path, header, group, overwrite=overwrite)
        outputs.append(out_path)
        md5_set = {_row_md5(r, md5_index) for r in group} if has_md5 else set()
        md5_sets[str(out_path)] = md5_set
        json_targets[str(out_path)] = json_path
        log(f"[完成] {out_path.name} -> {len(group)} 行")

    log(f"[完成] {csv_path.name}：共 {len(rows)} 行 / {len(groups)} 个 title，已按 title 各写一个文件")
    return {
        "file": csv_path,
        "total": len(rows),
        "groups": len(groups),
        "parts": len(groups),
        "outputs": outputs,
        "md5_sets": md5_sets,
        "json_targets": json_targets,     # 每个分类 JSON 的目标路径
    }


def load_json_products(json_path):
    """读汇总 JSON，返回商品对象列表（每个元素是九字段 dict）；失败返回 None。"""
    json_path = Path(json_path)
    if not json_path.is_file():
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def split_json_by_md5(products, md5_sets, json_targets=None, overwrite=True, log=print):
    """按 md5_sets（{csv路径: md5集合}）把商品对象筛进对应的 .json。

    每个商品对象只归入其 md5 首次命中的那份（md5 不跨文件，故每个商品只出现一次）。
    json_targets 指定每个 CSV 对应的 JSON 目标路径；缺省时与 CSV 同名同目录（.json 后缀替换）。
    返回 [(json_path, 商品数), ...]。
    """
    json_targets = json_targets or {}

    # 建立 md5 -> 商品 映射；同一 md5 只保留一个对象（商品级唯一）。
    by_md5 = {}
    for prod in products:
        md5 = str(prod.get("md5") or "").strip()
        if md5:
            by_md5.setdefault(md5, prod)

    # 新拆色商品只存在于阶段三的配套 JSON；缺失时应提示重新导出，避免静默写出空 JSON。
    required = set().union(*md5_sets.values())
    missing = required.difference(by_md5)
    if missing:
        raise ValueError(f'对应 JSON 缺少 {len(missing)} 个商品 md5，请重新运行阶段三生成配套 CSV 和 JSON')

    written = []
    for csv_path, md5_set in md5_sets.items():
        csv_path = Path(csv_path)
        # JSON 目标路径：优先用 json_targets 指定，否则与 CSV 同名同目录。
        target = json_targets.get(str(csv_path))
        if target is None:
            # 独立调用时可另存；主切分传入的目标已与 CSV 配对，不能再单独改名。
            target, = _available_output_paths((csv_path.with_suffix(".json"),), overwrite)
        json_path = Path(target)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        matched = [by_md5[m] for m in md5_set if m in by_md5]
        with open(json_path, "w" if overwrite else "x", encoding="utf-8") as f:
            json.dump(matched, f, ensure_ascii=False, indent=2)
        written.append((json_path, len(matched)))
        log(f"[完成] {json_path.name} -> {len(matched)} 个商品")
    return written
