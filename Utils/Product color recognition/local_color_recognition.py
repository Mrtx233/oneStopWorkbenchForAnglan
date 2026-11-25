"""Pillow + 标准库本地颜色建议：自适应前景、CIEDE2000 与全局分配。

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
    "oatmeal": "d8ceba", "mocha": "96745d", "caramel": "b97838",
    "terracotta": "bc7056", "rust": "a95032", "mint": "a8d5ba",
    "coral": "ed8277", "lilac": "c4a6d2", "mauve": "ac869e",
    "indigo": "424574", "denim": "527898", "tan": "c29c72",
    "cream white": "f3eddf", "dark khaki": "887956", "light brown": "b48c6d",
    "ash gray": "a5a5a1", "turquoise": "4bafac", "lemon yellow": "eadb65",
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
    "mint green": "mint", "denim blue": "denim", "heather grey": "gray",
    "ash grey": "ash gray", "燕麦": "oatmeal", "燕麦色": "oatmeal",
    "摩卡": "mocha", "摩卡色": "mocha", "焦糖色": "caramel",
    "陶土色": "terracotta", "砖红色": "terracotta", "铁锈色": "rust",
    "薄荷绿": "mint", "薄荷色": "mint", "珊瑚色": "coral", "珊瑚红": "coral",
    "丁香紫": "lilac", "藕紫色": "mauve", "藕紫": "mauve", "靛蓝": "indigo",
    "靛蓝色": "indigo", "牛仔蓝": "denim", "棕褐色": "tan",
    "鼠尾草绿": "sage green", "奶白色": "cream white", "奶油白": "cream white",
    "奶油色": "cream", "象牙白": "ivory", "深卡其": "dark khaki",
    "深卡其色": "dark khaki", "浅棕色": "light brown", "烟灰色": "ash gray",
    "深棕色": "dark brown", "巧克力棕": "chocolate brown", "宝蓝色": "royal blue",
    "薰衣草紫": "lavender", "驼色": "camel", "橄榄绿": "olive",
    "焦糖": "caramel", "陶土": "terracotta", "铁锈": "rust", "深蓝色": "dark blue",
    "浅紫色": "light purple", "米白": "off white", "象牙白色": "ivory",
    "卡其": "khaki", "薄荷绿色": "mint", "炭灰色": "charcoal",
}


def color_key(name: str) -> str | None:
    text = str(name).strip().casefold()
    # Reject patterns/combinations BEFORE removing harmless style suffixes.
    if re.search(r"[/&+]|\b(?:stripes?|striped|plaid|floral|prints?|printed|leopard|"
                 r"tie[ -]?dye|color[ -]?block|colour[ -]?block|multi[ -]?colou?r|"
                 r"multicolou?red|and)\b|条纹|格纹|格子|碎花|印花|豹纹|扎染|拼色|撞色|多色", text):
        return None
    text = re.sub(r"[（(]\s*(?:(?:normal|winter|regular|standard)\s+thickness|常规厚度|普通厚度|加厚)\s*[）)]", "", text)
    text = re.sub(r"(?:[-_ ]+\d+|[-_ ]+[a-z])$", "", text.strip())
    text = re.sub(r"[\s_-]+", " ", text).strip()
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
    """CIEDE2000, kL=kC=kH=1 (Sharma/Wu/Dalal reference formulation)."""
    l1, a1, b1 = a
    l2, a2, b2 = b
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = .5 * (1 - math.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7)))
    ap1, ap2 = (1 + g) * a1, (1 + g) * a2
    cp1, cp2 = math.hypot(ap1, b1), math.hypot(ap2, b2)
    h1 = math.degrees(math.atan2(b1, ap1)) % 360 if cp1 else 0
    h2 = math.degrees(math.atan2(b2, ap2)) % 360 if cp2 else 0
    dh = h2 - h1
    if cp1 * cp2 == 0:
        dh = 0
    elif dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dl, dc = l2 - l1, cp2 - cp1
    dhp = 2 * math.sqrt(cp1 * cp2) * math.sin(math.radians(dh / 2))
    lm, cpm = (l1 + l2) / 2, (cp1 + cp2) / 2
    if cp1 * cp2 == 0:
        hm = h1 + h2
    elif abs(h1 - h2) <= 180:
        hm = (h1 + h2) / 2
    else:
        hm = (h1 + h2 + (360 if h1 + h2 < 360 else -360)) / 2
    t = (1 - .17 * math.cos(math.radians(hm - 30)) + .24 * math.cos(math.radians(2 * hm))
         + .32 * math.cos(math.radians(3 * hm + 6)) - .20 * math.cos(math.radians(4 * hm - 63)))
    sl = 1 + .015 * (lm - 50) ** 2 / math.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + .045 * cpm, 1 + .015 * cpm * t
    rt = -2 * math.sqrt(cpm ** 7 / (cpm ** 7 + 25 ** 7)) * math.sin(
        math.radians(60 * math.exp(-((hm - 275) / 25) ** 2)))
    x, y, z = dl / sl, dc / sc, dhp / sh
    return math.sqrt(max(0, x * x + y * y + z * z + rt * y * z))


TARGET_LAB = {name: rgb_to_lab(tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)))
              for name, value in PALETTE.items()}


def _border_models(labs, w, h):
    """Cluster short patches on all four edges; keep local shadow/gradient modes."""
    sides = ([y * w for y in range(h)], [y * w + w - 1 for y in range(h)],
             list(range(w)), list(range((h - 1) * w, h * w)))
    models = []
    for side in sides:
        for start in range(0, len(side), max(2, len(side) // 6)):
            patch = [labs[i] for i in side[start:start + max(2, len(side) // 6)]]
            center = tuple(statistics.median(p[c] for p in patch) for c in range(3))
            spread = statistics.median(_delta(p, center) for p in patch)
            if spread > 9:  # busy borders are poor background evidence
                continue
            radius = min(7.0, max(2.4, spread * 2.5 + 1.8))
            if not any(_delta(center, model[0]) < 1.5 for model in models):
                models.append((center, radius))
    return models


def _skin(rgb, lab):
    r, g, b = rgb
    _, a, bb = lab
    return r > 70 and r > g > b and 5 < a < 30 and 8 < bb < 38 and r - b > 18


def extract_features(path: Path) -> dict[str, Any]:
    """Analyze <=9216 pixels, with a soft spatial prior instead of a fixed crop."""
    with Image.open(path) as source:
        source = ImageOps.exif_transpose(source)
        source.thumbnail((96, 96), Image.Resampling.LANCZOS)
        rgba = source.convert('RGBA')
        canvas = Image.new('RGBA', rgba.size, 'white')
        canvas.alpha_composite(rgba)
        image = canvas.convert('RGB')
    w, h = image.size
    if w < 8 or h < 8:
        return {'clusters': [], 'warning': '图片尺寸过小', 'quality_penalty': 50, 'invalid': True}
    reader = getattr(image, 'get_flattened_data', None)
    pixels = list(reader() if reader else image.getdata())
    lookup = {rgb: rgb_to_lab(rgb) for rgb in set(pixels)}
    labs = [lookup[p] for p in pixels]
    n = len(pixels)
    neutral = sum(math.hypot(a, b) < 9 for _, a, b in labs) / n
    extremes = sum(l < 22 or l > 85 for l, _, _ in labs) / n
    transitions = pairs = 0
    for y in range(h):
        for x in range(w):
            i = y * w + x
            for j in ((i + 1,) if x + 1 < w else ()) + ((i + w,) if y + 1 < h else ()):
                transitions += abs(labs[i][0] - labs[j][0]) > 28
                pairs += 1
    frequency = transitions / max(1, pairs)
    blank = statistics.pstdev(p[0] for p in labs) < 1.2 and (
        statistics.mean(p[0] for p in labs) > 96 or statistics.mean(p[0] for p in labs) < 4)
    document = neutral > .88 and extremes > .72 and frequency > .10
    warnings = []
    penalty = 0.0
    if blank:
        warnings.append('纯白或纯黑空白图')
        penalty += 80
    if document:
        warnings.append('疑似尺码表或高对比文字说明图')
        penalty += 55

    models = _border_models(labs, w, h)
    border = set(range(w)) | set(range((h - 1) * w, n)) | {y * w for y in range(h)} | {y * w + w - 1 for y in range(h)}
    background = set()
    checked = set()
    queue = deque()
    def visit(i):
        if i in checked:
            return
        checked.add(i)
        if any(_delta(labs[i], center) <= radius for center, radius in models):
            background.add(i)
            queue.append(i)
    for i in border:
        visit(i)
    while queue:
        i = queue.popleft()
        x, y = i % w, i // w
        if x: visit(i - 1)
        if x + 1 < w: visit(i + 1)
        if y: visit(i - w)
        if y + 1 < h: visit(i + w)
    foreground = [i for i in range(n) if i not in background]
    subject_share = len(foreground) / n
    border_clearance = len(border & background) / len(border)
    # If the whole frame has one color, retain evidence but prefer composed views.
    if subject_share < .025:
        foreground = list(range(n))
        warnings.append('满幅近似单色或前景与背景难以分离，建议核对主图')
        penalty += 10
    skin = {i for i in foreground if _skin(pixels[i], labs[i])}
    nonskin_share = (len(foreground) - len(skin)) / max(1, len(foreground))
    suppress_skin = bool(skin) and nonskin_share >= .32
    lower_share = sum(i // w >= h * .3 for i in foreground) / max(1, len(foreground))
    samples = []
    suppressed = 0
    for i in foreground:
        x, y = i % w, i // w
        # Full foreground, with continuous emphasis on torso/center.
        weight = .65 + .35 * (1 - abs((x + .5) / w - .5) * 2)
        if lower_share > .45 and y < h * .30 and suppress_skin:
            weight *= .16
        if suppress_skin and i in skin:
            weight *= .18 if y < h * .40 else .35
            suppressed += 1
        samples.extend([pixels[i]] * max(1, round(weight * 8)))
    if suppressed:
        warnings.append('已降低头部及肤色干扰权重')
    sample = Image.new('RGB', (len(samples), 1))
    sample.putdata(samples)
    quantized = sample.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()
    clusters = []
    for count, index in sorted(quantized.getcolors() or [], reverse=True):
        rgb = tuple(palette[index * 3:index * 3 + 3])
        clusters.append({'lab': rgb_to_lab(rgb), 'rgb': rgb, 'share': count / len(samples)})
    # Main views have a meaningful silhouette plus margin around it. Full-frame
    # crops can still be reviewed, but no longer outrank an equally good main view.
    composition = max(0, 1 - abs(subject_share - .48) / .52) * (.45 + .55 * border_clearance)
    if subject_share < .025:
        composition = .08
    if subject_share > .90:
        warnings.append('主体接近满屏，可能是面料特写')
    penalty += 5 * (1 - composition)
    # Only neutral, bright, mutually consistent edge patches justify a small
    # illuminant correction. Never normalize the garment's own mean color.
    neutral_models = [lab for lab, _ in models if lab[0] > 75 and math.hypot(lab[1], lab[2]) < 16]
    illuminant = (0.0, 0.0)
    if neutral_models and len(background) > n * .12:
        illuminant = tuple(max(-4, min(4, statistics.median(lab[c] for lab in neutral_models))) for c in (1, 2))
    return {'clusters': clusters, 'warning': '；'.join(warnings),
            'quality_penalty': round(penalty, 3), 'invalid': blank or document,
            'subject_share': round(subject_share, 3), 'border_clearance': round(border_clearance, 3),
            'composition_score': round(composition, 3), 'skin_suppressed': suppressed,
            'edge_frequency': round(frequency, 3), 'illuminant': illuminant}


def _perceptual_distance(lab, target, illuminant=(0, 0)):
    """Bounded exposure and background-supported white balance tolerance.

    The original delta remains available to the reviewer; correction is small
    and retains chroma, preventing dark navy from becoming neutral black.
    """
    raw = _delta(lab, target)
    l, a, b = lab
    adjusted = (l + max(-5, min(5, target[0] - l)) * .65,
                a - illuminant[0] * .65, b - illuminant[1] * .65)
    return min(raw, _delta(adjusted, target) + .35)


def minimum_cost_assignment(costs: list[list[float]]) -> list[int | None]:
    """Rectangular Hungarian algorithm; None denotes an unmatched row.

    O(rows^2 * columns), one real column per unique URL. Padding also handles
    more colors than images and gives deterministic, distinct review suggestions.
    """
    n = len(costs)
    if not n:
        return []
    m = len(costs[0])
    if any(len(row) != m for row in costs):
        raise ValueError('匹配矩阵每行长度必须一致')
    width = max(n, m)
    pad = max((v for row in costs for v in row), default=0) + 1000
    matrix = [row + [pad] * (width - m) for row in costs]
    u, v, p, way = [0.] * (n + 1), [0.] * (width + 1), [0] * (width + 1), [0] * (width + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        best, used = [math.inf] * (width + 1), [False] * (width + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, width + 1):
                if used[j]: continue
                value = matrix[i0 - 1][j - 1] - u[i0] - v[j]
                if value < best[j]:
                    best[j], way[j] = value, j0
                if best[j] < delta:
                    delta, j1 = best[j], j
            for j in range(width + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    best[j] -= delta
            j0 = j1
            if not p[j0]: break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    assignment = [None] * n
    for j in range(1, width + 1):
        if p[j] and j <= m:
            assignment[p[j] - 1] = j - 1
    return assignment


def recognize_product(colors: list[str], features: dict[int, dict[str, Any]],
                      reserved_urls: set[str], images: list[Any],
                      targets: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Globally assign known colors, then independently validate each result."""
    keys = {name: color_key(name) for name in colors}
    known = {name: key for name, key in keys.items() if key}
    key_counts = Counter(known.values())
    mixed = any(key is None for key in keys.values())
    wanted = list(colors if targets is None else targets)
    scored = {name: [] for name in known}
    visual_candidates = []
    missing = sum(bool(f.get('error')) for f in features.values())
    for index, feature in sorted(features.items()):
        if (type(index) is not int or not 0 <= index < len(images)
                or not isinstance(images[index], str) or not images[index].strip()
                or images[index] in reserved_urls):
            continue
        clusters = feature.get('clusters', [])
        if not clusters:
            continue
        visual_candidates.append({
            'image_index': index, 'delta_e': None,
            'share': round(max(c['share'] for c in clusters), 3),
            'score': feature.get('quality_penalty', 0),
            'composition_score': feature.get('composition_score', 0),
            'invalid': feature.get('invalid', False), 'warning': feature.get('warning', ''),
            'reason': '未知色或图案无单色参考，按主图构图推荐；需人工判断',
        })
        per_color = []
        for name, key in known.items():
            target = TARGET_LAB[key]
            best = min(({
                'delta': _perceptual_distance(c['lab'], target, feature.get('illuminant', (0, 0))),
                'raw_delta': _delta(c['lab'], target),
                'share': min(1, sum(other['share'] for other in clusters if _delta(c['lab'], other['lab']) <= 6)),
            } for c in clusters), key=lambda c: c['delta'] + 25 * (1 - c['share']))
            score = best['delta'] + 25 * (1 - best['share']) + feature.get('quality_penalty', 0)
            per_color.append((score, name, best))
        per_color.sort(key=lambda entry: (entry[0], entry[1]))
        for rank, (score, name, best) in enumerate(per_color):
            other = min((entry[0] for entry in per_color if entry[1] != name), default=score + 30)
            scored[name].append({'image_index': index, 'score': round(score, 3),
                                 'delta_e': round(best['raw_delta'], 3),
                                 'adjusted_delta_e': round(best['delta'], 3), 'share': round(best['share'], 3),
                                 'margin': round(other - score, 3), 'best_color': rank == 0,
                                 'warning': feature.get('warning', ''), 'invalid': feature.get('invalid', False),
                                 'composition_score': feature.get('composition_score', 0)})
    active = [name for name in wanted if keys[name]]
    # Duplicated source URLs are ONE image resource, regardless of file suffix/index.
    urls = list(dict.fromkeys(images[c['image_index']] for name in active for c in scored[name]))
    by_url = {}
    for name in active:
        for c in scored[name]:
            url = images[c['image_index']]
            if (name, url) not in by_url or c['score'] < by_url[name, url]['score']:
                by_url[name, url] = c
    # Large cost for impossible edges maximizes feasible automatic results first;
    # remaining review rows get distinct suggestions whenever resources permit.
    def confident(name, c):
        return (not c['invalid'] and key_counts[keys[name]] == 1 and c['best_color']
                and c['margin'] >= (9 if mixed else 4)
                and c['adjusted_delta_e'] <= (13 if mixed else 18)
                and c['score'] <= (29 if mixed else 36) and c['share'] >= (.52 if mixed else .36))
    costs = [[c['score'] + (0 if confident(name, c) else 10000)
              if (c := by_url.get((name, url))) else 1e8 for url in urls] for name in active]
    assignment = dict(zip(active, minimum_cost_assignment(costs)))
    result = {}
    for name in wanted:
        if keys[name] is None:
            result[name] = {'status': 'review', 'reason': '颜色名为图案、组合色或未收录名称，请人工判断', 'candidates': []}
            continue
        column = assignment.get(name)
        best = by_url.get((name, urls[column])) if column is not None else None
        candidates = sorted(scored[name], key=lambda c: (c['score'], c['image_index']))
        unique = []
        seen = set()
        # Lead with the global suggestion, then the next best distinct URLs.
        for c in ([best] if best else []) + candidates:
            url = images[c['image_index']]
            if url in seen: continue
            seen.add(url)
            unique.append({**c, 'reason': c['warning'] or '按色差、目标占比和主图构图排序'})
            if len(unique) == 3: break
        if best is None:
            result[name] = {'status': 'review', 'candidates': unique,
                            'reason': '没有可用的未占用图片' + (f'；{missing} 张本地图片缺失或损坏' if missing else '')}
            continue
        reasons = []
        if key_counts[keys[name]] > 1: reasons.append('多个选项属于相同基础色，需人工区分款式')
        if best['invalid']: reasons.append(best['warning'] or '疑似非主图或无效图')
        if not best['best_color'] or best['margin'] < (9 if mixed else 4): reasons.append('与其他颜色太接近或存在分配冲突')
        if best['adjusted_delta_e'] > (13 if mixed else 18) or best['score'] > (29 if mixed else 36): reasons.append('色差或图片质量未通过阈值')
        if best['share'] < (.52 if mixed else .36): reasons.append('目标色占比不足')
        result[name] = {**best, 'status': 'review' if reasons else 'success', 'candidates': unique,
                        'reason': '；'.join(reasons) or ('纯色独立严格校验通过（同组含未知色）' if mixed else '色差、占比和区分度通过自动识别阈值')}
    # Unknown names cannot supply a meaningful delta E. Offer composed, unused
    # views for manual inspection without competing with known-color matching.
    suggested_urls = {images[info['image_index']] for info in result.values() if 'image_index' in info}
    for name in wanted:
        if keys[name] is not None:
            continue
        ranked = sorted(visual_candidates, key=lambda c: (
            images[c['image_index']] in suggested_urls, c['invalid'], c['score'],
            -c['composition_score'], c['image_index']))
        seen = set()
        candidates = []
        for c in ranked:
            url = images[c['image_index']]
            if url in seen:
                continue
            seen.add(url)
            candidate = dict(c)
            if url in suggested_urls:
                candidate['reason'] += '；与其他颜色的绑定或候选冲突'
            candidates.append(candidate)
            if len(candidates) == 3:
                break
        info = result[name]
        info['candidates'] = candidates
        if candidates and images[candidates[0]['image_index']] not in suggested_urls:
            info['image_index'] = candidates[0]['image_index']
            suggested_urls.add(images[info['image_index']])
    return result
