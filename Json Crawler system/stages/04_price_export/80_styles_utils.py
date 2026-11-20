"""styles1 解码与价格修正，读写共用转义规则。"""
import math
import pandas as pd
from common import styles_codec


def to_float(value):
    try:
        amount = float(value)
        return amount if math.isfinite(amount) else None
    except (ValueError, TypeError):
        return None


def parse_styles(raw):
    if pd.isna(raw) or str(raw).strip() == '':
        return None, []
    segments = styles_codec.split(str(raw), '#')
    option1_name = styles_codec.unescape(segments[0])
    variants = []
    for segment in segments[1:]:
        values, sale, compare, image = styles_codec.decode_segment(segment)
        p1, p2 = to_float(sale), to_float(compare)
        if p1 is not None and p2 is not None and p2 < p1:
            p2 = p1
        variants.append({'option_values': values, 'price1': p1, 'price2': p2,
                         'image': image, 'raw': segment})
    return option1_name, variants


def fix_styles(raw):
    if pd.isna(raw) or str(raw).strip() == '':
        return raw, 0
    segments = styles_codec.split(str(raw), '#')
    fixed, count = [segments[0]], 0
    for segment in segments[1:]:
        values, sale, compare, image = styles_codec.decode_segment(segment)
        p1, p2 = to_float(sale), to_float(compare)
        if p1 is not None and p2 is not None and p2 < p1:
            fixed.append(styles_codec.encode_segment(values, p1, p1, image))
            count += 1
        else:
            fixed.append(segment)
    return '#'.join(fixed), count
