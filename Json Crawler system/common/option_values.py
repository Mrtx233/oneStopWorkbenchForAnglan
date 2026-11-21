"""清洗颜色和尺码取值，并移除字母尺码后的括号/数字区间后缀。"""
import re


def _dimension(name):
    text = str(name or '').strip().casefold()
    if text in {'color', 'colour', 'colors', 'colours', '颜色'}:
        return 'Color'
    if text in {'size', 'sizes', '尺寸'}:
        return 'Size'
    return None


def clean_option_value(value):
    # 数字尺码等非字符串原样保留，只删除明确要求过滤的两种字符。
    return value.replace('\\', '').replace('&', '') if isinstance(value, str) else value


def _country_size_to_standard(value):
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r'(US|UK|AUS|FR|ITY)\s*(\d+)(W)?', value.strip(), re.IGNORECASE)
    if not match:
        return value
    country, number, wide = match.groups()
    country = country.upper()
    number = int(number)
    if wide:
        wide_maps = {
            'US': {16: '1X', 18: '2X', 20: '2X', 22: '3X', 24: '3X', 26: '4X'},
            'UK': {20: '1X', 22: '2X', 24: '2X', 26: '3X', 28: '3X', 30: '4X'},
            'AUS': {20: '1X', 22: '2X', 24: '2X', 26: '3X', 28: '3X', 30: '4X'},
            'FR': {48: '1X', 50: '2X', 52: '2X', 54: '3X', 56: '3X', 58: '4X'},
            'ITY': {52: '1X', 54: '2X', 56: '2X', 58: '3X', 60: '3X', 62: '4X'},
        }
        return wide_maps.get(country, {}).get(number, value)
    maps = {
        'US': {0: 'XXS', 2: 'XS', 4: 'S', 6: 'M', 8: 'L', 10: 'XL', 12: '2XL', 14: '3XL', 16: '4XL'},
        'UK': {4: 'XXS', 6: 'XS', 8: 'S', 10: 'M', 12: 'L', 14: 'XL', 16: '2XL', 18: '3XL', 20: '1X', 22: '2X', 24: '2X', 26: '3X', 28: '3X', 30: '4X'},
        'AUS': {4: 'XXS', 6: 'XS', 8: 'S', 10: 'M', 12: 'L', 14: 'XL', 16: '2XL', 18: '3XL', 20: '1X', 22: '2X', 24: '2X', 26: '3X', 28: '3X', 30: '4X'},
        'FR': {32: 'XXS', 34: 'XS', 36: 'S', 38: 'M', 40: 'L', 42: 'XL', 44: '2XL', 46: '3XL', 48: '1X', 50: '2X', 52: '2X', 54: '3X', 56: '3X', 58: '4X'},
        'ITY': {36: 'XXS', 38: 'XS', 40: 'S', 42: 'M', 44: 'L', 46: 'XL', 48: '2XL', 50: '3XL', 52: '1X', 54: '2X', 56: '2X', 58: '3X', 60: '3X', 62: '4X'},
    }
    return maps.get(country, {}).get(number, value)


def _clean_size_value(value):
    """保留统一尺码主体，移除括号/数字区间后缀并转换国家尺码。"""
    if not isinstance(value, str):
        return value
    text = value.split('(', 1)[0].split('（', 1)[0].strip()
    if '/' in text:
        prefix, suffix = text.split('/', 1)
        prefix = prefix.strip()
        numeric_suffix = suffix.split('/', 1)[0]
        suffix_parts = numeric_suffix.replace('–', '-').replace('—', '-').replace(' ', '').split('-')
        letter_sizes = (
            {'S', 'M', 'L', 'OS', 'ONESIZE', 'ONE SIZE', 'FREE SIZE'}
            | {'X' * count + 'S' for count in range(1, 6)}
            | {'X' * count + 'L' for count in range(1, 6)}
            | {f'{count}XL' for count in range(2, 11)}
        )
        if (prefix.upper() in letter_sizes and len(suffix_parts) in (1, 2)
                and all(part.isdigit() for part in suffix_parts)):
            text = prefix
    return _country_size_to_standard(text)


def _clean_values(values, *, size=False):
    cleaned = []
    for value in values:
        value = clean_option_value(value)
        if size:
            value = _clean_size_value(value)
        if isinstance(value, str) and not value.strip():
            continue
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def clean_product_option_values(product):
    """复制商品后清理目标维度，兼容汇总和原始 Shopify 结构，不改变调用方数据。"""
    result = dict(product)
    options = product.get('options')
    if not isinstance(options, list):
        return result
    analysis = 'option_counts' in product
    cleaned_options = []
    dimensions = {}
    variant_fields = []
    for index, entry in enumerate(options, 1):
        if not isinstance(entry, dict):
            cleaned_options.append(entry)
            continue
        prepared = dict(entry)
        if analysis:
            for name, values in entry.items():
                dimension = _dimension(name)
                if dimension is None:
                    continue
                if isinstance(values, dict):
                    mapping = {}
                    for value, image in values.items():
                        value = clean_option_value(value)
                        if dimension == 'Size':
                            value = _clean_size_value(value)
                        if isinstance(value, str) and not value.strip():
                            continue
                        # 清洗后同名颜色合并，保留首个非空图片地址。
                        if value not in mapping or not mapping[value]:
                            mapping[value] = image
                    prepared[name] = mapping
                elif isinstance(values, list):
                    prepared[name] = _clean_values(values, size=dimension == 'Size')
                else:
                    continue
                dimensions[dimension] = len(prepared[name])
        elif _dimension(entry.get('name')) is not None:
            dimension = _dimension(entry.get('name'))
            if isinstance(entry.get('values'), list):
                prepared['values'] = _clean_values(entry['values'], size=dimension == 'Size')
            variant_fields.append((f"option{entry.get('position') or index}", dimension))
        cleaned_options.append(prepared)
    result['options'] = cleaned_options
    if analysis and isinstance(product.get('option_counts'), dict):
        counts = dict(product['option_counts'])
        for name in counts:
            dimension = _dimension(name)
            if dimension in dimensions:
                counts[name] = dimensions[dimension]
        result['option_counts'] = counts
    elif variant_fields and isinstance(product.get('variants'), list):
        variant_dimensions = dict(variant_fields)
        result['variants'] = [
            {key: (_clean_size_value(value) if variant_dimensions[key] == 'Size'
                   else clean_option_value(value)) if key in variant_dimensions else value
             for key, value in variant.items()}
            if isinstance(variant, dict) else variant
            for variant in product['variants']
        ]
    return result
