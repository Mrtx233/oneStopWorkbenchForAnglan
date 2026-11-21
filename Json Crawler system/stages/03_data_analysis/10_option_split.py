"""只把 Color 按上限切段拆行；拆出的商品只保留自身颜色图。"""
import hashlib
import json

import config          # 00_config，取 SKIP_OPTIONS 等本阶段常量
import product_parser  # 30_product_parser，所有解析能力都从这里来

# 颜色判定直接复用 parser 的实现，避免「哪里算颜色」在两处口径不一致
is_color_name = product_parser.is_color_name
# getattr 兜底：30 是靠 exec 拼出来的模块，万一没导出该常量也不至于 import 阶段就崩
COLOR_NAMES = getattr(product_parser, "COLOR_NAMES", {"color", "colour", "colors", "colours", "颜色"})
SIZE_NAMES = getattr(product_parser, "SIZE_NAMES", {"size", "sizes", "尺寸"})


# 把用户勾选的选项名归一成小写集合，并补全颜色/尺码的各种写法。
def expand_selected_names(selected_options):
    selected = {str(name).strip().casefold() for name in (selected_options or [])}
    # 勾了任一别名就等于勾了该维度的全部写法。
    if selected & COLOR_NAMES:
        selected |= COLOR_NAMES
    if selected & SIZE_NAMES:
        selected |= SIZE_NAMES
    return selected


def select_option_names(selected_options, observed_names, include_other=False):
    """其他维度按实际明细加入，Color/Size 始终服从各自勾选，不被开关重新选中。"""
    selected = list(selected_options)
    if include_other:
        primary = COLOR_NAMES | SIZE_NAMES
        chosen = {str(name).strip().casefold() for name in selected}
        for name in observed_names:
            key = str(name).strip().casefold()
            output_name = 'Style' if key == 'type' else name
            output_key = output_name.casefold()
            if output_key and output_key not in primary and output_key not in chosen:
                selected.append(output_name)
                chosen.add(output_key)
    return selected


# 按上限把一列取值切成若干块；limit 为空表示不切，整列一块。
def chunk_values(values, limit):
    values = list(values or [])
    if not limit:
        return [values]
    # or [[]] 保证没有取值时仍返回一个空块，商品照样出一行，不至于被静默丢掉
    return [values[i:i + limit] for i in range(0, len(values), limit)] or [[]]


# 只对 Color 列按上限切块，切出几块就代表要拆成几行商品。
def option_limit_sets(options, option_limits=None):
    limits = product_parser.normalize_option_limits(option_limits)
    color = next((opt for opt in options if is_color_name(opt.get("name"))), None)
    others = [opt for opt in options if opt is not color]
    # 没有颜色列就不拆行，颜色上限只管颜色这一维
    if color is None:
        return [list(options)]
    sets = []
    for chunk in chunk_values(color.get("values"), limits.get("color") or limits.get("colour")):
        # 每块都带上完整的其它列（尺码等），只是颜色换成当前这块；名字统一成 Color 方便后续识别
        sets.append([dict(color, name="Color", values=chunk), *[dict(opt) for opt in others]])
    return sets


# 克隆商品并把颜色维裁成本块，保证这一块只描述自己那几个颜色。
def restrict_product(product, chunk):
    product = product_parser.clean_product_option_values(product)
    cloned = dict(product)
    wanted = {opt["name"]: list(opt.get("values") or []) for opt in chunk}
    color_allow = next((vals for name, vals in wanted.items() if is_color_name(name)), None)
    # 阶段 02 汇总形态：options 是 {选项名: 取值列表或 颜色→图片 映射}
    new_options = []
    for entry in product.get("options") or []:
        if not isinstance(entry, dict):
            new_options.append(entry)
            continue
        slim = {}
        for name, values in entry.items():
            allow = wanted.get(name)
            # 数据里颜色列名可能是 colour 等变体，按含义匹配而不是按块里的固定名 Color 匹配
            if allow is None and is_color_name(name):
                allow = color_allow
            if allow is None or not is_color_name(name):
                slim[name] = values
            elif isinstance(values, dict):
                # 颜色→图片映射一起裁：本块之外的颜色图不能跟着进这一行的 src_links
                slim["Color"] = {key: val for key, val in values.items() if key in allow}
            else:
                slim["Color"] = [val for val in values if val in allow]
        new_options.append(slim)
    cloned["options"] = new_options
    return product_parser.clean_product_option_values(cloned)


def color_product_md5(product, chunk):
    """由来源商品和本块颜色派生独立标识，同一颜色块重复导出保持稳定。"""
    source = str(product.get("md5") or "").strip() or product["url"]
    colors = next(opt["values"] for opt in chunk if is_color_name(opt["name"]))
    # 不使用块序号、价格或图片，避免重新排序、改价或换图改变商品身份。
    payload = json.dumps(
        ["color-product-v1", source, sorted(str(value) for value in colors)],
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


# 返回 True 表示 src_links 只留本块颜色图，丢掉所有相册补图。
def drop_gallery_images(selected_options, options, split_by_color, color_images_only):
    # 一旦按颜色拆成多行就必须丢：不丢的话每行都会带着全部主图，颜色与图对不上
    if split_by_color:
        return True
    # 未启用仅颜色图模式时，颜色图之后仍按补图数量添加相册主图
    if not color_images_only:
        return False
    has_color = any(is_color_name(opt.get("name")) for opt in options)
    if not has_color:
        return False
    # 没传勾选列表（视为全选）时，有颜色列就按勾选了颜色处理
    if selected_options is None:
        return True
    return bool(expand_selected_names(selected_options) & COLOR_NAMES)


# 十字段行的生成入口：颜色切块 → 逐块解析 → 需要时把 src_links 收成本块颜色图。
def parse_product_rows(data, selected_options=None, option_limits=None, color_images_only=False,
                       output_products=None, gallery_image_limit=4):
    product = data.get("product", data)
    # SKIP_OPTIONS 在这里生效：先把「ships from」之类的非款式列整列剔掉再参与拆行
    options = product_parser.get_sorted_options(product, skip_options=config.SKIP_OPTIONS)
    if selected_options is not None:
        selected = expand_selected_names(selected_options)
        options = [opt for opt in options if opt["name"].strip().casefold() in selected]
    rows, products = [], []
    chunks = option_limit_sets(options, option_limits)
    split_by_color = len(chunks) > 1
    drop_gallery = drop_gallery_images(selected_options, options, split_by_color, color_images_only)
    for chunk in chunks:
        sliced = restrict_product(product, chunk)
        if split_by_color:
            sliced["md5"] = color_product_md5(product, chunk)
        row = product_parser.parse_product(
            {"product": sliced}, selected_options=selected_options, option_limits=None,
            gallery_image_limit=gallery_image_limit,
        )
        # option_limits 传 None：上限已经体现在切块上，再传进去会被二次截断，块内数量就对不上
        if drop_gallery:
            # 直接从已拼好的 styles1 反解图片，比重新推断图片顺序更不容易和款式串错位
            sliced["images"] = product_parser.style_image_urls(row["styles1"])
            row["src_links"] = "#".join(sliced["images"])
        rows.append(row)
        products.append(sliced)
    # 整件商品的所有颜色块解析成功后再交给调用方，失败时不遗留半组 JSON。
    if output_products is not None:
        output_products.extend(products)
    return rows
