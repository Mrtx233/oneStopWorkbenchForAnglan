"""轻量本地颜色建议：中心区域采样、边缘背景剔除和 Lab 色差。

只依赖 Pillow；分数是启发式指标，不是识别正确率。图案、组合色、近似色
和低质量图片留给人工复核，不把颜色名的语义猜测当成可靠结果。
"""
from __future__ import annotations

from collections import Counter, deque
import math
from pathlib import Path
import re
import statistics
from typing import Any

from PIL import Image, ImageOps


PALETTE = {
    "black": "171717", "white": "f4f3ef", "ivory": "f5efda",
    "off white": "eee9dc", "cream": "f3e3be", "beige": "d6c4a4",
    "apricot": "dfbb8c", "champagne": "dfcaa6", "sand": "cbb18b",
    "gray": "888888", "light gray": "c4c4c4", "dark gray": "494949",
    "charcoal": "363b3f", "silver": "bdbdbd", "ash": "a1a09b",
    "brown": "80593f", "dark brown": "503629", "chocolate brown": "583a2a",
    "coffee": "71513e", "camel": "b78c5b", "khaki": "b6a078",
    "taupe": "928477", "red": "c92c35", "dark red": "86262e",
    "burgundy": "722b3e", "wine red": "79293e", "claret": "742b40",
    "pink": "d895ac", "light pink": "efb6c7", "dusty pink": "bd8d99",
    "dusty rose": "b67d88", "blush pink": "deb0ae", "rose": "d3668d",
    "rose red": "bf3268", "fuchsia": "c0348a", "peach": "ecad91",
    "orange": "dd792b", "yellow": "e5bb3d", "mustard": "bd952b",
    "gold": "bc983d", "purple": "825d9c", "light purple": "b499c9",
    "lavender": "b0a1ca", "plum": "704565", "blue": "417cac",
    "light blue": "92b6cf", "sky blue": "78afce", "dark blue": "264367",
    "navy blue": "202b46", "royal blue": "3b58b1", "dusty blue": "819bac",
    "cyan": "44b4c5", "teal": "287b7c", "deep teal": "235c60",
    "peacock blue": "227a91", "green": "507f52", "light green": "a3b987",
    "dark green": "28543e", "sage green": "9ca991", "olive": "7e8150",
    "army green": "626b44", "bean green": "9da77f", "emerald": "278268",
}
ALIASES = {
    "grey": "gray", "light grey": "light gray", "dark grey": "dark gray",
    "navy": "navy blue", "navyblue": "navy blue", "deep blue": "dark blue",
    "lightblue": "light blue", "wine": "wine red", "pure white": "white",
    "jet black": "black", "offwhite": "off white", "heather gray": "gray",
    "olive green": "olive", "sage": "sage green", "blush": "blush pink",
    "黑色": "black", "白色": "white", "米白色": "off white", "米色": "beige",
    "杏色": "apricot", "卡其色": "khaki", "灰色": "gray", "浅灰色": "light gray",
    "深灰色": "dark gray", "棕色": "brown", "咖啡色": "coffee", "红色": "red",
    "酒红色": "wine red", "粉色": "pink", "浅粉色": "light pink",
    "黄色": "yellow", "橙色": "orange", "紫色": "purple", "蓝色": "blue",
    "浅蓝色": "light blue", "藏青色": "navy blue", "绿色": "green",
    "浅绿色": "light green", "深绿色": "dark green", "银色": "silver",
}


def color_key(name: str) -> str | None:
    text = re.sub(r"[\s_-]+", " ", name.strip().casefold())
    # 厚度只影响款式；图案、条纹等修饰语不剥除，以免误判成纯色。
    text = re.sub(r"\s*\((?:normal|winter) thickness\)\s*$", "", text)
    text = ALIASES.get(text, text)
    return text if text in PALETTE else None


def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    linear = [c / 3294.6 if c <= 10.31475 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
    r, g, b = linear
    xyz = ((r * .4124564 + g * .3575761 + b * .1804375) / .95047,
           r * .2126729 + g * .7151522 + b * .0721750,
           (r * .0193339 + g * .1191920 + b * .9503041) / 1.08883)
    x, y, z = [v ** (1 / 3) if v > .008856 else 7.787 * v + 16 / 116 for v in xyz]
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)


def _delta(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


TARGET_LAB = {name: rgb_to_lab(tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)))
              for name, value in PALETTE.items()}


def extract_features(path: Path) -> dict[str, Any]:
    """先缩图再分析，最多约 9 千像素，避免旧实现的大图逐像素开销。"""
    with Image.open(path) as source:
        source = ImageOps.exif_transpose(source)
        source.thumbnail((96, 96), Image.Resampling.LANCZOS)
        rgba = source.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, "white")
        canvas.alpha_composite(rgba)
        image = canvas.convert("RGB")
    w, h = image.size
    if w < 8 or h < 8:
        return {"clusters": [], "warning": "图片尺寸过小"}
    read_pixels = getattr(image, "get_flattened_data", None)
    pixels = list(read_pixels() if read_pixels else image.getdata())
    border = [pixels[y * w + x] for y in range(h) for x in range(w)
              if x in {0, w - 1} or y in {0, h - 1}]
    buckets = Counter(tuple(c // 24 for c in p) for p in border)
    bucket, count = buckets.most_common(1)[0]
    matching = [p for p in border if tuple(c // 24 for c in p) == bucket]
    bg = tuple(int(statistics.median(p[c] for p in matching)) for c in range(3))
    removed: set[int] = set()
    if count / len(border) >= .30:
        queue: deque[int] = deque()

        def visit(index: int) -> None:
            if index not in removed and sum((a - b) ** 2 for a, b in zip(pixels[index], bg)) < 22 ** 2:
                removed.add(index)
                queue.append(index)

        for x in range(w):
            visit(x); visit((h - 1) * w + x)
        for y in range(h):
            visit(y * w); visit(y * w + w - 1)
        while queue:
            index = queue.popleft()
            x, y = index % w, index // w
            if x: visit(index - 1)
            if x + 1 < w: visit(index + 1)
            if y: visit(index - w)
            if y + 1 < h: visit(index + w)
    roi = [(y * w + x, 2 if y < h * .65 else 1)
           for y in range(int(h * .18), max(int(h * .80), int(h * .18) + 1))
           for x in range(int(w * .22), max(int(w * .78), int(w * .22) + 1))]
    kept = [(index, weight) for index, weight in roi if index not in removed]
    fraction = len(kept) / max(1, len(roi))
    warning = "前景与背景难以分离" if fraction < .35 else ""
    if not kept:
        kept = roi
    sample_pixels = [pixels[index] for index, weight in kept for _ in range(weight)]
    sample = Image.new("RGB", (len(sample_pixels), 1))
    sample.putdata(sample_pixels)
    quantized = sample.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()
    clusters = []
    for count, i in sorted(quantized.getcolors() or [], reverse=True):
        rgb = tuple(palette[i * 3:i * 3 + 3])
        clusters.append({"lab": rgb_to_lab(rgb), "rgb": rgb, "share": count / len(sample_pixels)})
    return {"clusters": clusters, "warning": warning}


def recognize_product(colors: list[str], features: dict[int, dict[str, Any]],
                      reserved_urls: set[str], images: list[Any],
                      targets: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """只有唯一且有足够色差优势的匹配返回 success，其余返回 review。"""
    keys = {name: color_key(name) for name in colors}
    known = {name: key for name, key in keys.items() if key}
    key_counts = Counter(known.values())
    unknown = any(key is None for key in keys.values())
    scored: dict[str, list[dict[str, Any]]] = {name: [] for name in known}
    missing = sum(bool(value.get("error")) for value in features.values())
    for index, feature in features.items():
        if index >= len(images) or images[index] in reserved_urls:
            continue
        clusters = feature.get("clusters", [])
        if not clusters:
            continue
        per_color = []
        for name, key in known.items():
            # 不是从所有小色块中任取最近色：低占比色块必须承担明显惩罚。
            # 合并相近聚类，避免同一衣物的明暗层次被量化成多个小色块后误判占比不足。
            best = min(({"delta": _delta(c["lab"], TARGET_LAB[key]),
                         "share": sum(other["share"] for other in clusters if _delta(c["lab"], other["lab"]) <= 22)} for c in clusters),
                       key=lambda c: c["delta"] + 30 * (1 - c["share"]))
            score = best["delta"] + 30 * (1 - best["share"])
            per_color.append((score, name, best))
        per_color.sort(key=lambda entry: entry[0])
        for rank, (score, name, best) in enumerate(per_color):
            other = min((value[0] for value in per_color if value[1] != name), default=score + 30)
            scored[name].append({"image_index": index, "score": round(score, 2),
                                "delta_e": round(best["delta"], 2), "share": round(best["share"], 3),
                                "margin": round(other - score, 2), "best_color": rank == 0,
                                "warning": feature.get("warning", "")})
    result = {}
    used = set(reserved_urls)
    # 先分配最强候选，后续颜色不得复用同一 URL。
    order = sorted(targets if targets is not None else colors,
                   key=lambda name: min((c["score"] for c in scored.get(name, [])), default=999))
    for name in order:
        if keys[name] is None:
            result[name] = {"status": "review", "reason": "颜色名为图案、组合色或未收录名称，请人工判断"}
            continue
        candidates = sorted(scored[name], key=lambda c: (c["score"], c["image_index"]))
        best = next((c for c in candidates if images[c["image_index"]] not in used), None)
        if best is None:
            reason = "没有可用的未占用图片" + (f"；{missing} 张本地图片缺失或损坏" if missing else "")
            result[name] = {"status": "review", "reason": reason}
            continue
        reasons = []
        if unknown: reasons.append("同组存在图案或未知颜色，无法可靠排除混淆")
        if key_counts[keys[name]] > 1: reasons.append("多个选项属于相同基础色，需人工区分款式")
        if best["warning"]: reasons.append(best["warning"])
        if not best["best_color"] or best["margin"] < 7: reasons.append("与其他颜色太接近")
        if best["delta_e"] > 22 or best["score"] > 39: reasons.append("色差较大")
        if best["share"] < .32: reasons.append("目标色占比不足")
        status = "review" if reasons else "success"
        result[name] = {**best, "status": status, "reason": "；".join(reasons) or "色差和区分度通过自动识别阈值"}
        if status == "success":
            used.add(images[best["image_index"]])
    return result
