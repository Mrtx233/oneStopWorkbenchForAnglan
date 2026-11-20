# -*- coding: utf-8 -*-
"""功能 8：JSON 尺码调整（统一商品 JSON 的 Size 尺码）。"""

import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from ..constants import SIZE_FIELD, SIZE_SKIP_NAMES, SIZE_FALLBACK_PRESETS


def load_size_presets():
    """读取阶段 02 的标准尺码映射；取不到时用内置兜底，保证本工具独立可用。"""
    presets = {count: list(values) for count, values in SIZE_FALLBACK_PRESETS.items()}
    stage = (
        Path(__file__).resolve().parent.parent.parent
        / "Json Crawler system" / "stages" / "02_product_scraper"
    )
    if stage.is_dir():
        sys.path.insert(0, str(stage))
        try:
            from product_analysis import SIZE_VALUES_BY_COUNT
            presets.update({count: list(values) for count, values in SIZE_VALUES_BY_COUNT.items()})
            return presets
        except Exception:
            pass
        finally:
            sys.path.remove(str(stage))
    return presets


SIZE_PRESETS = load_size_presets()


def iter_targets(source):
    """把输入路径展开成待处理的 json 文件列表。

    支持单个 .json，也支持目录（取目录下的 *.json，跳过索引文件与 recovery 文件）。
    """
    path = Path(source)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.glob("*.json")
            if p.name not in SIZE_SKIP_NAMES and ".recovery-" not in p.name
        )
    raise ValueError(f"路径不存在：{path}")


def load_records(path):
    """读取商品数组 JSON，返回 (记录列表, 原始文本)。"""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("JSON 顶层不是商品数组")
    for index, record in enumerate(data):
        if not isinstance(record, dict):
            raise ValueError(f"第 {index + 1} 条不是对象")
    return data, text


def inspect_records(records):
    """检查每条商品的 Size 选项。

    返回 (有 Size 的清单, 没有 Size 的下标列表)，
    有 Size 的清单元素为 (下标, 尺码个数, 尺码列表)。
    """
    with_size, without = [], []
    for index, record in enumerate(records):
        values = None
        options = record.get("options")
        if isinstance(options, list):
            for entry in options:
                if isinstance(entry, dict) and SIZE_FIELD in entry:
                    raw = entry[SIZE_FIELD]
                    values = list(raw) if isinstance(raw, list) else []
                    break
        if values is None:
            without.append(index)
        else:
            with_size.append((index, len(values), values))
    return with_size, without


def apply_sizes(records, sizes, add_missing=True, adaptive=False):
    """就地把每条商品的 Size 改成目标尺码。

    固定模式（adaptive=False）：所有商品统一改成 sizes。
    自适应模式（adaptive=True）：每个商品按自身现有 Size 个数 N，套用
    SIZE_PRESETS[N]；N 不在预设表（如超过 9 码）时保留原值。

    已有 Size 的替换原值（位置不变，保留同一对象中的其他字段），
    没有的追加到 options 末尾；add_missing=False 时完全保留没有 Size 的商品。
    option_counts 的 Size 记为目标个数。返回 (替换条数, 新增条数)。
    """
    replaced = added = 0
    for record in records:
        options = record.get("options")
        found = isinstance(options, list) and any(
            isinstance(entry, dict) and SIZE_FIELD in entry for entry in options
        )
        if not found and not add_missing:
            continue

        target = sizes
        if adaptive:
            existing = next(
                (entry[SIZE_FIELD] for entry in options
                 if isinstance(entry, dict) and SIZE_FIELD in entry),
                None,
            ) if isinstance(options, list) else None
            count = len(existing) if isinstance(existing, list) else 0
            target = SIZE_PRESETS.get(count)
            if target is None:
                continue
            target = list(target)

        counts = record.get("option_counts")
        if not isinstance(counts, dict):
            counts = {}
            record["option_counts"] = counts
        counts[SIZE_FIELD] = len(target)

        if not isinstance(options, list):
            options = []
            record["options"] = options
        for entry in options:
            if isinstance(entry, dict) and SIZE_FIELD in entry:
                entry[SIZE_FIELD] = list(target)
        if found:
            replaced += 1
        else:
            options.append({SIZE_FIELD: list(target)})
            added += 1
    return replaced, added


def save_records(records, path, backup=True):
    """按主系统格式原子写回，可选先备份。返回备份路径或 None。

    备份名带时间戳与唯一后缀，避免覆盖旧备份；先写同目录临时文件再 os.replace，
    中途失败不破坏原文件。
    """
    target = Path(path)
    backup_path = None
    if backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_handle, backup_name = tempfile.mkstemp(
            prefix=f"{target.name}.{stamp}.", suffix=".bak", dir=str(target.parent),
        )
        os.close(backup_handle)
        backup_path = Path(backup_name)
        try:
            shutil.copy2(target, backup_path)
        except Exception:
            backup_path.unlink(missing_ok=True)
            raise

    handle, temporary = tempfile.mkstemp(
        prefix=f".{target.stem}_tmp_", suffix=".json", dir=str(target.parent),
    )
    os.close(handle)
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(records, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return backup_path


def parse_size_list(text):
    """解析自定义尺码列表，支持中英文逗号、分号与换行分隔。"""
    parts = re.split(r"[,，;；\n\r]+", text or "")
    return [part.strip() for part in parts if part.strip()]


def format_matches(records, original_text):
    """判断文件是否已经是主系统标准序列化格式（ensure_ascii=False / indent=2）。

    必须在改动 records 之前调用；不一致时写回会把整个文件重排，
    提示用户是必要的。
    """
    return json.dumps(records, ensure_ascii=False, indent=2) == original_text


def process_json_sizes(files, sizes, add_missing=True, backup=True, check_only=False,
                       adaptive=False, log=print):
    """复用尺码工具的读写逻辑；检查只读，修改只处理传入的已检查文件。

    adaptive=True 时按各商品自身 Size 个数套标准序列，忽略传入的 sizes。
    """
    if not adaptive and not sizes:
        raise ValueError("请指定有效的目标尺码。")
    stats = {"readable": [], "written": 0, "skipped": 0, "failed": 0,
             "replaced": 0, "added": 0}
    if adaptive:
        log("目标尺码：自适应（按各商品 Size 个数套标准序列）")
    else:
        log(f"目标尺码：{' / '.join(sizes)}")
    log("处理范围：已有 Size 的调整，缺失的补上" if add_missing
        else "处理范围：只调整已有 Size，没有 Size 的商品跳过")
    for path in files:
        try:
            records, text = load_records(path)
            with_size, without = inspect_records(records)
            log(f"\n文件：{path.name}，商品总数：{len(records)}")
            log(f"  已有 Size：{len(with_size)} 条")
            action = "补上" if add_missing else "跳过"
            log(f"  没有 Size，将{action}：{len(without)} 条")
            if check_only:
                distribution = Counter(count for _, count, _ in with_size)
                if distribution:
                    log("  当前尺码分布：" + "，".join(
                        f"{count} 码 × {amount}" for count, amount in sorted(distribution.items())
                    ))
                for index, count, values in with_size[:3]:
                    sample = " / ".join(map(str, values)) if values else "（空）"
                    target = " / ".join(map(str, SIZE_PRESETS.get(count, values))) if adaptive else "（固定）"
                    log(f"    例 #{index + 1}：{count} 码 → {sample}"
                        + (f"，自适应将替换为 {target}" if adaptive else ""))
                stats["readable"].append(path)
                continue

            reformat = not format_matches(records, text)
            replaced, added = apply_sizes(records, sizes, add_missing=add_missing,
                                          adaptive=adaptive)
            if replaced + added == 0:
                stats["skipped"] += 1
                log("  无需修改，保留原文件")
                continue
            backup_path = save_records(records, path, backup=backup)
            stats["written"] += 1
            stats["replaced"] += replaced
            stats["added"] += added
            log(f"  已写入：{path}，调整 {replaced} 条，新增 {added} 条")
            if backup_path:
                log(f"  备份：{backup_path.name}")
            if reformat:
                log("  注意：原文件已按主系统标准格式重写")
        except Exception as exc:
            stats["failed"] += 1
            log(f"[失败] {path.name}：{exc}")

    if check_only:
        log(f"检查完成：成功读取 {len(stats['readable'])} 个文件，失败 {stats['failed']} 个")
    else:
        log(f"完成：写入 {stats['written']} 个文件，跳过 {stats['skipped']} 个，"
            f"失败 {stats['failed']} 个；调整 {stats['replaced']} 条商品，新增 {stats['added']} 条")
    return stats
