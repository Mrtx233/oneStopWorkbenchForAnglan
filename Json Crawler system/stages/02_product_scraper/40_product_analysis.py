"""原始 Shopify 商品转为九字段 JSON，描述在落盘前完成统一清洗。"""

from collections import Counter
import re
from common.product_text import clean_product_title
from common.price_fallback import fill_missing_prices
from common.option_values import clean_product_option_values
from common.product_model import (
    OptionDimension, Product, canonical_option_name, is_color_name, is_size_name,
)
from url_utils import normalize_url_dashes
import network_utils

# Color / Size 的维度名判定与归一由 common/product_model.py 统一维护，
# 这里按原函数名导入，阶段内调用方式与导入路径保持不变。


# 根据商品名称识别鞋裤；英语单数按词匹配，复数兼容标题清洗后连字符被删除的写法。
ORIGINAL_SIZE_TITLE_PATTERN = re.compile(
    r'\b(?:shoe|shoes|sneaker|sneakers|boot|boots|sandal|sandals|slipper|slippers|'
    r'loafer|loafers|trainer|trainers|footwear|heels|flats|pant|pants|trouser|trousers|'
    r'jean|jeans|legging|leggings|jogger|joggers|sweatpant|sweatpants|chino|chinos|shorts)\b'
)
ORIGINAL_SIZE_TITLE_SUFFIXES = (
    'shoes', 'sneakers', 'boots', 'sandals', 'slippers', 'loafers', 'trainers',
    'footwear', 'heels', 'flats', 'pants', 'trousers', 'jeans', 'leggings',
    'joggers', 'sweatpants', 'chinos', 'shorts',
)


def effective_size_mode(title, use_standard_sizes=True):
    """标准尺码开关开启时，名称识别为鞋裤的商品仍使用网站原始尺码。"""
    if not use_standard_sizes:
        return 'original'
    # 与落盘标题使用相同清洗规则，避免首次采集和后续续跑的判定不一致。
    text = clean_product_title(title).casefold()
    chinese_match = any(keyword in text for keyword in ('鞋', '裤', '褲'))
    english_match = (ORIGINAL_SIZE_TITLE_PATTERN.search(text) is not None
                     or any(word.endswith(ORIGINAL_SIZE_TITLE_SUFFIXES)
                            for word in re.findall(r'[a-z]+', text)))
    return 'original' if chinese_match or english_match else 'standard'


def has_missing_size_details(row):
    """历史汇总有正数尺码数量但无明细时，需从源商品重新采集，不能仅凭数量还原。"""
    counts = row.get("option_counts") or {}
    if not isinstance(counts, dict) or not any(
        is_size_name(name) and isinstance(count, (int, float)) and count > 0
        for name, count in counts.items()
    ):
        return False
    return not any(
        is_size_name(name) and isinstance(values, list) and values
        for entry in row.get("options") or [] if isinstance(entry, dict)
        for name, values in entry.items()
    )


def needs_size_refresh(row, use_standard_sizes=True):
    """缺明细或尺码模式改变时补采；没有模式标记的旧记录按原先标准模式兼容。"""
    if has_missing_size_details(row):
        return True
    counts = row.get("option_counts") or {}
    mode = effective_size_mode(row.get('title', ''), use_standard_sizes)
    return (isinstance(counts, dict) and any(is_size_name(name) for name in counts)
            and row.get("size_mode", "standard") != mode)


def needs_option_refresh(row, use_standard_sizes=True):
    """补采历史缺失的其他维度明细，并保留原有尺码修复与模式切换规则。"""
    if needs_size_refresh(row, use_standard_sizes):
        return True
    counts = row.get("option_counts") or {}
    if not isinstance(counts, dict):
        return False
    detailed = {
        canonical_option_name(name).casefold()
        for entry in row.get("options") or [] if isinstance(entry, dict)
        for name, values in entry.items() if isinstance(values, (list, dict)) and values
    }
    return any(
        str(name).strip() and isinstance(count, (int, float)) and count > 0
        and canonical_option_name(name).casefold() not in detailed
        for name, count in counts.items()
    )


def needs_description_refresh(row, keep_description_images=False, keep_description_tables=False):
    """旧清洗已经删除的图片 / 表格只能重新采集；关闭保留开关可直接清洗现有描述。"""
    return ((bool(keep_description_images)
             and row.get('description_image_mode', 'remove') != 'keep')
            or (bool(keep_description_tables)
                and row.get('description_table_mode', 'remove') != 'keep'))


# 整组尺码无法全部提取时，按清洗后的数量回退到标准序列。
SIZE_VALUES_BY_COUNT = {
    2: ("S", "M"),
    3: ("S", "M", "L"),
    4: ("S", "M", "L", "XL"),
    5: ("S", "M", "L", "XL", "2XL"),
    6: ("XS", "S", "M", "L", "XL", "2XL"),
    7: ("XS", "S", "M", "L", "XL", "2XL", "3XL"),
    8: ("XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"),
    9: ("XXS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"),  # 超过 9 个尺码时保留原值
}


# 常见独立尺码保留原写法；提取时只匹配完整词，避免从 UK、Small 等词中误取字母。
LETTER_SIZE_TOKEN = (
    r"(?:X+[ -]?(?:SMALL|LARGE)|EXTRA[ -]+(?:SMALL|LARGE)|"
    r"SMALL|MEDIUM|LARGE|(?:[2-9]|10)X[SL]|X+[SL]|[SML]|"
    r"ONE[ -]?SIZE|FREE[ -]?SIZE|ONESIZE|ONE|OS)"
)
LETTER_SIZE_PATTERN = re.compile(LETTER_SIZE_TOKEN, re.IGNORECASE)
EMBEDDED_SIZE_PATTERN = re.compile(
    r"(?<!\w)" + LETTER_SIZE_TOKEN + r"(?!\w)", re.IGNORECASE,
)
NUMERIC_SIZE_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def standardize_size_values(size_values):
    """常规尺码原样保留；复合值全部明确提取成功才采用，否则整组按数量回退。"""
    original = list(size_values)
    texts = [str(value).strip() if value is not None else "" for value in original]
    if all(LETTER_SIZE_PATTERN.fullmatch(text) or NUMERIC_SIZE_PATTERN.fullmatch(text)
           for text in texts):
        return original

    extracted = []
    for value, text in zip(original, texts):
        if LETTER_SIZE_PATTERN.fullmatch(text):
            extracted.append(value)
            continue
        matches = list(EMBEDDED_SIZE_PATTERN.finditer(text))
        # S/M 等多尺码写法有歧义，不能随意选择其中一个；数字也不能凭空推断字母码。
        if len(matches) != 1:
            return list(SIZE_VALUES_BY_COUNT.get(len(original), original))
        extracted.append(matches[0].group())
    return extracted


def skip_image_indexes(count, positions):
    # 把"跳图位置"翻译成图片下标集合（0 基）：正数按序、负数按倒数，越界的位置忽略。
    dropped = set()
    for position in positions or []:
        if position > 0:  # 第 N 张 → 下标 N-1
            if 1 <= position <= count:
                dropped.add(position - 1)
        elif position < 0:  # 倒数第 N 张 → 下标 count-N（-1 即最后一张）
            index = count + position
            if 0 <= index < count:
                dropped.add(index)
    return dropped


def filter_gallery_images(images, skip_positions, color_urls):
    # 相册图先剔除用户指定跳过的位序，再去掉已被颜色图占用的 URL，避免同一图重复出现。
    dropped = skip_image_indexes(len(images), skip_positions)
    kept = [src for index, src in enumerate(images) if index not in dropped]
    used = {url for url in (color_urls or []) if url}  # 颜色维度的图不算作普通相册图
    return [src for src in kept if src not in used]


def parse_product_object(data, *, url, title, fennei, skip_positions=None, currency="", use_standard_sizes=True,
                  keep_description_images=False, keep_description_tables=False, md5=""):
    # 把原始 Shopify 商品字典解析成九字段汇总行（外加可选 currency / size_mode / md5）。
    product = clean_product_option_values(data["product"])
    variants = product.get("variants") or []
    images = product.get("images") or []
    raw_options = product.get("options") or []
    size_mode = effective_size_mode(title, use_standard_sizes)

    def mode(field):
        # 取该字段在所有变体里的众数：价格通常一致，取众数比取首个更稳健。
        counts = Counter("" if v.get(field) is None else v[field] for v in variants)
        return counts.most_common(1)[0][0] if counts else ""

    price = mode("price")            # 售价：变体价格众数
    compare = mode("compare_at_price")  # 原价：变体对比价众数
    price, compare = fill_missing_prices(price, compare)  # 任一价格缺失时，用另一价格补齐
    # 币种优先级：商品 JSON 自带 > 传入参数 > 店铺 cart.js 兜底识别
    currency = network_utils.extract_currency(data) or str(currency or "").strip().upper()
    if not currency:
        currency = network_utils.detect_shop_currency_http(url)
    price, compare, currency = network_utils.prices_to_usd(price, compare, currency)  # 尽力换 USD，失败回退原币种
    images = sorted(images, key=lambda image: image.get("position") or 0)  # 按 position 排序，恢复展示顺序（缺失按 0）
    # 建立 图片ID→归一化URL 映射，供颜色选项按 image_id 反查其颜色图
    images_by_id = {image["id"]: normalize_url_dashes(image["src"]) for image in images
                    if image.get("id") is not None and image.get("src")}
    by_name = {canonical_option_name(option["name"]): option.get("values") or []
               for option in raw_options}  # 归一化后的选项名→取值列表
    dimensions = []  # 选项维度对象：Color → {颜色: 图片}，Size 与其他 → 取值列表
    color_urls = []  # 收集颜色图 URL，稍后从相册中排除
    color_option = next((option for option in raw_options if is_color_name(option.get("name"))), None)
    if color_option is not None:
        # 定位颜色选项在 options 里的序位，拼出变体上的 optionN 字段名
        color_index = next(
            (index for index, option in enumerate(raw_options, 1) if option is color_option),
            1,
        )
        color_field = f"option{color_option.get('position') or color_index}"
        colors = {}
        for color in color_option.get("values") or []:
            # 每个颜色取首个能对上 image_id 的变体图作为该颜色的代表图，找不到留空
            colors[color] = next(
                (images_by_id[v["image_id"]] for v in variants
                 if v.get(color_field) == color and v.get("image_id") in images_by_id),
                "",
            )
        color_urls = list(colors.values())
        dimensions.append(OptionDimension("Color", colors))  # Color 维度：颜色名→图片 URL
    if "Size" in by_name:
        size_values = by_name["Size"]
        # 普通商品先保留常规尺码或整组提取，失败才按数量回退；鞋裤仍保留原值。
        values = standardize_size_values(size_values) if size_mode == 'standard' else size_values
        dimensions.append(OptionDimension("Size", list(values)))
    # 数量以外也保留其他选项的真实取值，阶段三通过开关决定是否参与组合。
    dimensions.extend(OptionDimension(name, list(values)) for name, values in by_name.items()
                      if name and name not in ("Color", "Size") and values)
    gallery = [normalize_url_dashes(image["src"]) for image in images if image.get("src")]  # 全部相册图 URL
    # 汇总行的所有字段统一由 Product 对象承载：这里只负责从原始商品算出取值，
    # 字段校验、类型统一、可选键省略与序列化都交给 common/product_model.py。
    return Product(
        url=url,                                     # 商品页地址（对象内统一编码，保留表情路径）
        title=title,                                 # 商品标题（取自 Shopify product.title）
        fennei=fennei,                               # 分类标题（来自阶段 01 的分组键）
        body_html=product.get("body_html"),
        price=price,                                 # 已尽力换算为 USD 的售价
        compare_at_price=compare,                    # 划线价（任一价格缺失时，两价互补）
        images=filter_gallery_images(gallery, skip_positions, color_urls),  # 去掉跳图位与颜色图后的相册
        options=dimensions,                          # Color/Size 与其他维度的完整取值
        option_counts={name: len(values) for name, values in by_name.items()},
        currency=currency,
        size_mode=size_mode if "Size" in by_name else "",
        description_image_mode="keep" if keep_description_images else "remove",
        description_table_mode="keep" if keep_description_tables else "remove",
        md5=md5,                                    # 阶段 01 透传的 url 的 md5（可选）
    )


def parse_product(data, **kwargs):
    """保留字典返回接口；运行器直接复用 parse_product_object 的已清洗对象。"""
    return parse_product_object(data, **kwargs).to_dict()
