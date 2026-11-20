# ======================== 产品解析层 ========================
# 本文件是 product_parser 的前半段：与 32_parser_part2 一起被 30_product_parser 依次 exec 进同一命名空间，
# 因此这里定义的名字（format_combo_value、_style_escape、is_color_name、analysis_options 等）都由后半段直接取用。
# 依赖是单向的：后半段用本文件的名字，本文件不再引用后半段的定义，但加载顺序仍须保持 part1 → part2，
# 因为 30_product_parser 把合并后的命名空间整体搬进模块 globals，先定义的先落地更好排查。
#
# 输入只有阶段二的九字段汇总记录一种形态：入口 40_analyzer.iter_products 已用 is_analysis_product
# 做过守卫，非法输入在那里就报错，所以本文件不再保留原始 Shopify 商品的解析分支。
from itertools import product as itertools_product
from urllib.parse import urlparse, urlunparse

# 注意：下面这四个 import 里有几个本文件自己并不直接用，而是给 32_parser_part2 用的——
# part2 没有任何自己的 import，它取用的 config / styles_codec / normalize_url_dashes /
# clean_product_option_values 全部来自这里 exec 进同一命名空间的名字。
# 静态检查工具按单文件分析会把它们报成「未使用导入」，删掉就会让 part2 在运行时 NameError。
import config
from common import styles_codec
from common.option_values import clean_product_option_values
from url_utils import normalize_url_dashes

# 这里只认 color/colour 两种写法（Shopify 常见列名）；colors/colours 的扩展在 option_split 的勾选侧做
COLOR_NAMES = {"color", "colour"}


# 判断是否为阶段 02 汇总 JSON 的九字段形态；入口守卫与拆行都靠它认定输入合法。
def is_analysis_product(product):
    # option_counts + url + price 同时存在是汇总文件的稳定特征，原始 Shopify 商品没有这组键
    return "option_counts" in product and "url" in product and "price" in product


# 是否是颜色列：大小写、首尾空格都算命中，各店列名写法不一。
def is_color_name(name):
    return str(name or "").strip().casefold() in COLOR_NAMES


# 汇总形态的 options（{列名: 取值或 颜色→图}）转成统一的 [{name, values}] 列表。
def analysis_options(product, selected_options=None, skip_options=None):
    product = clean_product_option_values(product)
    return _analysis_options(product, selected_options, skip_options)


def _analysis_options(product, selected_options=None, skip_options=None):
    """内部入口：调用方已经清洗选项及颜色键。"""
    options = []
    selected = None if selected_options is None else {n.casefold() for n in selected_options}
    # 勾了 color 就把 colour 也放行，否则同一维度会因为拼写不同被漏掉
    if selected is not None and "color" in selected:
        selected.add("colour")
    skip = [n.casefold() for n in (skip_options or [])]
    for entry in product.get("options", []):
        for name, values in entry.items():
            output_name = "Color" if is_color_name(name) else name
            if str(name or "").strip().casefold() == "type" and isinstance(values, list) and len(values) > 1:
                output_name = "Style"
            if selected is not None and output_name.casefold() not in selected:
                continue
            # SKIP_OPTIONS 按「包含」判断（如 ships from），因为这类列名常带前后修饰词
            if any(n in name.casefold() for n in skip):
                continue
            options.append({"name": output_name, "values": list(values)})
    # 颜色必须排在第一列：styles1 的首段和每个组合的图片都按第一列取
    options.sort(key=lambda opt: 0 if is_color_name(opt["name"]) else 1)
    return options


# 组合取值一律转文本，None 转空串，避免拼接结果里出现字面 None。
def format_combo_value(value):
    return "" if value is None else str(value)


# 把商品的选项整理成「颜色优先、命名规范」的列表，供拆行与拼 styles 使用。
def get_sorted_options(product, skip_options=None):
    return analysis_options(product, skip_options=skip_options)


# 把界面上的「颜色/尺码上限」文本转成 {列名: 正整数}；非法输入直接报错，别当成没限制。
def normalize_option_limits(option_limits=None):
    limits = {}
    for name, value in (option_limits or {}).items():
        text = '' if value is None else str(value).strip()
        if not text:
            continue  # 留空表示该列不限，不参与拆行
        if not text.isdecimal() or int(text) < 1:
            raise ValueError(f'{name} 上限必须为正整数，或留空')
        limits[str(name).strip().casefold()] = int(text)
    return limits


# 按上限截断每列取值：查不到上限时切片上界是 None，等于整列保留。
def limit_option_values(options, option_limits=None):
    limits = normalize_option_limits(option_limits)
    return [dict(opt, values=list(opt.get('values', []))[:limits.get(opt['name'].strip().casefold())])
            for opt in options]


# 各列取值的笛卡尔积：一行商品对应一个组合，行数等于各列取值数相乘。
def build_option_combos(options):
    value_groups = [[format_combo_value(value) for value in option.get("values", [])] for option in options]
    if not value_groups:
        return [()]  # 完全没有选项时也要出一行，否则整件商品会被丢掉
    # 行数膨胀发生在这里：所以颜色上限必须在切块阶段（option_split）就把颜色数压住，
    # 不然 颜色 x 尺码 会把 styles1 长度和 Excel 行数一起撑爆
    return list(itertools_product(*value_groups))


# 取商品的「代表价」：一行商品只能有一个价格。
# 阶段二落库时已把 price/compare 折成 USD 并做过两价互补，这里只做包装，不再联网换算、也不统计变体众数。
def product_modal_prices(product):
    return {"price": product["price"], "compare_at_price": product["compare_at_price"],
            "currency": product.get("currency") or "USD"}


# 给图片地址插入尺寸后缀（Shopify CDN 按 文件名_宽x高.扩展名 出缩放图）。
# 600x600 是清晰度与整表体积的折中：原图动辄几 MB，链接虽不占体积但下游加载和核对都慢。
def format_image_url(url, size="600x600"):
    if not url:
        return ""
    # 先归一破折号，否则同一张图会因为 -/‑ 等写法不同被当成两张，导致去重失效
    parsed = urlparse(normalize_url_dashes(url))
    path = parsed.path
    dot_index = path.rfind(".")
    slash_index = path.rfind("/")
    # 只有「路径确实带扩展名」且「还没加过该尺寸后缀」时才插入，否则会拼出 _600x600_600x600
    if dot_index > slash_index and not path[:dot_index].endswith(f"_{size}"):
        path = f"{path[:dot_index]}_{size}{path[dot_index:]}"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


# 转义 styles 保留字符（\\ & # @），否则取值里的这些字符会被下游当成分隔符，切出的段就错位了。
# 反斜杠必须最先替换，不然会把后面几步刚加进去的反斜杠再转义一遍。
def _style_escape(value):
    return styles_codec.escape(value)
