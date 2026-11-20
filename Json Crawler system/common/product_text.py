"""商品标题与分类名称的统一清洗，解析、续采和最终落盘共用。"""
import re
import unicodedata


def clean_product_title(value):
    """保留各语言文字、数字和文字组合音标，删除表情、标点及其他符号。"""
    text = str(value or '')
    # 键帽表情包含普通数字，须整体删除，避免去掉装饰后残留数字。
    text = re.sub(r'[0-9#*]\ufe0f?\u20e3', '', text)
    kept = []
    for char in text:
        code = ord(char)
        # 变体选择符属于组合标记，但不属于标题文字。
        if 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF:
            continue
        category = unicodedata.category(char)
        if char.isspace():
            kept.append(' ')
        elif category[0] in ('L', 'N') or category in ('Mn', 'Mc'):
            kept.append(char)
    return ' '.join(''.join(kept).split())


def clean_category_name(value):
    """分类名中的 ASCII 连字符换为空格，并整理首尾及连续空白。"""
    return ' '.join(str(value or '').replace('-', ' ').split())
