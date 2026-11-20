# 本文件是 product_parser 的后半段：没有自己的 import，config / styles_codec /
# format_image_url / clean_product_option_values / analysis_options / _style_escape 等名字
# 全部来自 31_parser_part1，由 30_product_parser 把两段 exec 进同一命名空间后才成立，
# 所以本文件绝不能单独 import。


# 算出「这件商品要写哪些组合」，并带上代表价与每个组合的颜色图。
def selected_product_combinations(product, selected_options=None, skip_options=None, option_limits=None):
    product = clean_product_option_values(product)
    return _selected_product_combinations(product, selected_options, skip_options, option_limits)


def _selected_product_combinations(product, selected_options=None, skip_options=None, option_limits=None):
    """内部入口：维度和值、颜色图片映射使用同一份已清洗数据。"""
    # 颜色 -> 图片 的映射阶段 02 已经配好，直接取用，不再回查 variant/image_id
    options = _analysis_options(product, selected_options, skip_options)
    options = limit_option_values(options, option_limits)
    colors = next((values for entry in product.get("options", [])
                   for key, values in entry.items() if is_color_name(key)), {})
    color_index = next((i for i, opt in enumerate(options) if is_color_name(opt["name"])), None)
    entries = []
    for combo in build_option_combos(options):
        image = colors.get(combo[color_index], "") if color_index is not None else ""
        image = format_image_url(image)
        # image_status 供预览统计：hit=匹到颜色图，unlinked=有颜色列但缺图，no_opt=商品本身没有颜色列
        entries.append({"combo": combo, "image_url": image,
                        "image_status": "hit" if image else ("unlinked" if color_index is not None else "no_opt")})
    return options, product_modal_prices(product), entries


# 基类是 ValueError：上层按异常类型跳过商品，不会打断整批导出。
class InvalidProductError(ValueError):
    """商品数据超出可写入范围，应跳过该商品。"""


# 触发点见 parse_product 里的 config.MAX_STYLES_LENGTH 判断，属于「数据太大」而不是「数据坏了」。
class StylesTooLongError(InvalidProductError):
    """styles1 超过单元格长度上限，可跳过该商品。"""


# 从已经拼好的 styles1 反解出款式图列表：option_split 在「只留本块颜色图」时用它，
# 比重新推断图片顺序更不容易和款式串错位。
def style_image_urls(styles):
    seen = []
    seen_set = set()
    parts = styles_codec.split(str(styles or ""), "#")
    segments = parts[1:] if len(parts) > 1 else []  # 首段是属性名，不是组合片段，跳过
    for seg in segments:
        # 找第一个未转义的 @，属性里的 @ 和 URL 内的 @ 都原样保留。
        opt_text, sep, image = styles_codec.partition_image(seg)
        # 必须同时有 $（说明带价格段）才算真正的组合片段，纯文本段不能当图
        if not sep or opt_text.rfind("$") == -1 or not image or image in seen_set:
            continue
        seen.append(image)
        seen_set.add(image)
    return seen


# 汇总形态的 src_links：颜色图全留，再从全部图里补最多 4 张不重复主图（这就是「后面四张」的出处）。
def _build_src_links(images, style_images):
    """合并已完成尺寸格式化的图集和款式图。"""
    style_images = list(dict.fromkeys(src for src in style_images if src))
    style_set = set(style_images)
    # 4 张是人工核对与页面展示够用量的折中；已在颜色图里出现过的不重复计入这 4 张
    main_images = [src for src in images if src and src not in style_set][:4]
    return "#".join(style_images + main_images)


# 十字段行的生成入口：一行 = 一个（被切块后的）商品，列顺序见 config.CSV_FIELDS。
# 标题与链接直接取自汇总记录自身的 fennei / url，不需要调用方再传一份。
def parse_product(data, selected_options=None, option_limits=None):
    product = clean_product_option_values(data.get("product", data))
    options, prices, entries = _selected_product_combinations(
        product, selected_options, skip_options=config.SKIP_OPTIONS, option_limits=option_limits)
    segments = []
    for entry in entries:
        parts = []
        for index, value in enumerate(entry["combo"]):
            if index:
                # 首列取值不写属性名（整串最前面已经写过），其余列都要「名+值」成对
                parts.append(_style_escape(options[index]["name"]))
            parts.append(_style_escape(value))
        segment = f"{'&'.join(parts)}${prices['price']}${prices['compare_at_price']}"
        if entry["image_url"]:
            segment += f"@{entry['image_url']}"
        segments.append(segment)
    styles = "#".join(segments)
    if options:
        styles = f"{_style_escape(options[0]['name'])}#{styles}"
    # 上限在这里把关：超限就抛，让 analyzer 跳过该商品，而不是截断出反解不了的串
    if len(styles) > config.MAX_STYLES_LENGTH:
        raise StylesTooLongError(f"styles1 长度 {len(styles)} 超过上限 {config.MAX_STYLES_LENGTH}")
    # 十字段来源：title 用分类名（fennei）、name 用商品标题；styles2/styles3 固定留空给后续流程；
    # 汇总文件的 body_html 已在阶段 02 清洗过，所以直接传给 details
    return {
        "title": product["fennei"], "name": product["title"],
        "price1": prices["price"], "price2": prices["compare_at_price"],
        "styles1": styles, "styles2": "", "styles3": "",
        "src_links": _build_src_links([format_image_url(src) for src in product["images"]],
                                      [entry["image_url"] for entry in entries]),
        "link-href": normalize_url_dashes(product["url"]), "details": product["body_html"],
        "md5": product.get("md5", ""),
    }
