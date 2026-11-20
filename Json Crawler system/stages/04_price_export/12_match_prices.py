"""按尺码梯度定价：以采集售价为锚从库价递增取价；无尺码商品保留原价；价差受上限约束。"""
import re
from collections import Counter
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
from common import styles_codec
from common.atomic_io import replace_file
from common.step_loader import load_step

_HERE = Path(__file__).resolve().parent
_pricing = load_step(_HERE / '00_pricing_config.py')
_styles = load_step(_HERE / '80_styles_utils.py')
price_library_sorted = _pricing.price_library_sorted
to_float = _styles.to_float
parse_styles = _styles.parse_styles


def variant_size(option1_name, variant):
    values = variant['option_values']
    if str(option1_name).strip().casefold() in ('size', 'sizes'):
        value = values[0] if values else ''
    else:
        value = next((values[i + 1] for i in range(1, len(values) - 1, 2)
                      if values[i].strip().casefold() in ('size', 'sizes')), '')
    value = value.strip().upper().replace(' ', '').replace('-', '')
    aliases = {'XSMALL': 'XS', 'SMALL': 'S', 'MEDIUM': 'M', 'LARGE': 'L',
               'XLARGE': 'XL', 'XXL': '2XL', 'XXXL': '3XL', 'XXXXL': '4XL',
               'XXSMALL': 'XXS', 'XXLARGE': '2XL', 'XXXLARGE': '3XL',
               'XXXXLARGE': '4XL'}
    return aliases.get(value, value)


def size_sort_key(size):
    standard = ['XXS', 'XS', 'S', 'M', 'L', 'XL']
    if size in standard:
        return (0, standard.index(size))
    plus = re.fullmatch(r'(\d+)XL', size)
    if plus:
        return (0, 4 + int(plus.group(1)))
    if re.fullmatch(r'\d+(?:\.\d+)?', size):
        return (1, float(size))
    return (2, size)


def spread_prices(points, count):
    """档位不足时：前几个尺码各占一个档位，多余尺码复用最后一个档位（如 1 2 3 3 3）。"""
    if not points or count <= 0:
        return []
    if len(points) >= count:
        return points[:count]
    return points + [points[-1]] * (count - len(points))


def row_original(row):
    """参考价以采集划线价（原价）为准，缺失时用采集售价。

    两个调用点传入的都是 {'采集售价': …, '采集划线价': …}，而这两列在 run() 开头
    由 source_data 无条件补齐，所以这里只认这一组列名，不再回退到 price1/price2。
    """
    for name in ('采集划线价', '采集售价'):
        value = to_float(row.get(name))
        if value is not None and value > 0:
            return value
    return None


def cents(value):
    return int((Decimal(str(value)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _library():
    values = set()
    for raw in price_library_sorted:
        value = to_float(raw)
        if value is None or value <= 0 or cents(value) <= 0:
            raise ValueError(f'价格库包含无效金额：{raw}')
        values.add(cents(value))
    values = sorted(values)
    if not values:
        raise ValueError('价格库没有有效的正数价格')
    return values


def _variants(raw):
    """标准变体、无选项内嵌价格和空款式；有内容但无法解析时不抹掉属性。"""
    if pd.isna(raw) or str(raw).strip() == '':
        return '', [{'option_values': [], 'price1': None, 'price2': None, 'image': '', 'raw': ''}]
    text = str(raw).strip()
    if text.startswith('$'):
        text = '#' + text
    return parse_styles(text)


def run(data, output_path, stop=None, rules=None, source_data=None):
    rules = rules or _pricing.resolve_rules()
    max_ratio = rules.max_ratio
    lower = rules.window_lower
    upper = rules.window_upper
    df = data.copy(deep=True).reset_index(drop=True)
    source = (source_data if source_data is not None else data).reset_index(drop=True)
    if len(source) != len(df):
        raise ValueError('原始价格与匹配数据行数不一致')
    for column in ('price1', 'price2'):
        df[column] = df[column].astype(object)
    df['styles1'] = df['styles1'].astype(object)
    # 保留采集依据供复跑使用。
    for saved, column in (('采集售价', 'price1'), ('采集划线价', 'price2'), ('采集款式', 'styles1')):
        df[saved] = source[saved] if saved in source else source[column]
    df['定价参考价'] = None
    df['定价状态'] = '未匹配'
    library = _library()
    print(f'尺码梯度定价：以划线价为参考，候选窗口 = 划线价 × [{lower}, {upper}]；'
          f'最高价 ≤ 最低价 × {max_ratio}；库价全局去重不重复', flush=True)
    counts = Counter()
    used_prices = set()

    def log_result(idx, row, status, reason):
        counts[status] += 1
        print(f'定价行 {idx + 2} | {row.get("name", "")} | {status} | {reason}', flush=True)

    # 低价预处理：采集售价低于 8.99 的商品不参与匹配，按售价从低到高循环取 8.99～19.99 库价，
    # 同一商品全部变体（含颜色）同价。赋的新价作为商品原价（Regular），不设划线折扣（Sale 空）。
    low_library = [price for price in library if 899 <= price <= 1999]
    if not low_library:
        raise ValueError('价格库没有 8.99～19.99 范围内的可用价格')
    low_rows = []
    for idx, row in df.iterrows():
        sale = to_float(row['采集售价'])
        if sale is not None and Decimal(str(sale)) < Decimal('8.99'):
            low_rows.append((sale, idx))
    low_done = set()
    for rank, (_, idx) in enumerate(sorted(low_rows)):
        if stop is not None and stop.is_set():
            break
        row = df.loc[idx]
        price = low_library[rank % len(low_library)] / 100
        name, variants = _variants(df.at[idx, 'styles1'])
        if not variants:
            log_result(idx, row, '未匹配', '低价商品款式无法解析，请修正数据')
            continue
        segments = [styles_codec.escape(name)]
        for variant in variants:
            segments.append(styles_codec.encode_segment(
                variant['option_values'], f'{price:.2f}', '', variant['image']))
        df.at[idx, 'styles1'] = '#'.join(segments)
        df.at[idx, 'price1'] = price
        df.at[idx, 'price2'] = ''
        df.at[idx, '定价状态'] = '低价'
        low_done.add(idx)
        used_prices.add(cents(price))
        log_result(idx, row, '低价', f'采集售价低于 8.99，按售价升序赋值 {price:.2f} 为原价，无划线折扣')

    # ── 统一窗口匹配 ──────────────────────────────────────────────────
    # 候选范围 = 划线价 × [窗口下界, 窗口上界]，剔除已用库价（含低价预处理占用的），
    # 按尺码从未用最小库价递增取价；库价全局唯一不重复。
    # 匹配顺序：按参考价（原价）从大到小，原价高的商品先匹配、先占用重叠区间的库价。
    # 参考价缺失的行排在最后（用 None 兜底，内部再按原逻辑判「未匹配」）。
    def _ref_of(i):
        return row_original({'采集售价': df.at[i, '采集售价'], '采集划线价': df.at[i, '采集划线价']})

    ordered_indices = sorted(
        (idx for idx in df.index if idx not in low_done),
        key=lambda i: (_ref_of(i) is None, -(_ref_of(i) or 0)),
    )
    for idx in ordered_indices:
        if stop is not None and stop.is_set():
            break
        row = df.loc[idx]
        reference = row_original({'采集售价': row['采集售价'], '采集划线价': row['采集划线价']})
        name, variants = _variants(row.get('styles1'))
        df.at[idx, '定价参考价'] = reference
        if reference is None:
            log_result(idx, row, '未匹配', '采集售价和划线价均无有效正数')
            continue
        sale_orig = to_float(row['采集售价'])
        compare_orig = to_float(row['采集划线价'])
        if (sale_orig is not None and compare_orig is not None and
                compare_orig > 0 and sale_orig < compare_orig * 0.5):
            # 保持原样：商品仍以采集售价销售，该售价也算「已被使用」
            used_prices.add(cents(sale_orig))
            log_result(idx, row, '未匹配', '售价低于划线价五折，保持原样不匹配')
            continue
        if not variants:
            log_result(idx, row, '未匹配', '款式格式无法解析，请修正数据')
            continue
        sizes = sorted({variant_size(name, v) for v in variants}, key=size_sort_key)
        has_size = any(str(size).strip() for size in sizes)
        # 候选库价：落在 [参考价 × 下界, 参考价 × 上界] 且未被其他商品使用的档位（整数分）
        lower_cents = int((Decimal(str(reference)) * lower * 100).to_integral_value(rounding=ROUND_HALF_UP))
        upper_cents = int((Decimal(str(reference)) * upper * 100).to_integral_value(rounding=ROUND_HALF_UP))
        candidates = [p for p in library
                      if lower_cents <= p <= upper_cents and p not in used_prices]
        # 同款总价差上限：候选集整体须满足 最高 ≤ 最低 × max_ratio，超出的高端档位剔除。
        # 锚定最低价而非最高价，与下面「从窗口低端取档」的既有策略一致；
        # resolve_rules 保证 spread ≥ 0 即 max_ratio ≥ 1，故 candidates[0] 自身必然保留，
        # 收窄不会把候选清空，「窗口内无未用库价」的判定仍只由全局去重触发。
        if candidates:
            cap_cents = int((Decimal(candidates[0]) * max_ratio).to_integral_value(rounding=ROUND_DOWN))
            trimmed = [p for p in candidates if p <= cap_cents]
            # 只有收窄后剩余档位不多于尺码数时才影响选档：候选比尺码多时，
            # 下面取的是窗口最低端那一段，剔掉高端对本行结果没有任何影响，不值得记日志。
            if len(trimmed) != len(candidates) and len(trimmed) <= len(sizes):
                print(f'定价行 {idx + 2} | 价差上限 {rules.spread_percent}%：候选 {len(candidates)} 档'
                      f'收窄为 {len(trimmed)} 档（剔除 > {cap_cents / 100:.2f}），档数因此减少', flush=True)
            candidates = trimmed
        if not has_size:
            # 无尺码：取窗口内最小的未用库价（单一价，不递增）
            if not candidates:
                # 窗口内没有未用库价，保持原价
                df.at[idx, 'price1'] = reference
                df.at[idx, 'price2'] = reference
                segments = [styles_codec.escape(name)]
                for variant in variants:
                    segments.append(styles_codec.encode_segment(
                        variant['option_values'], f'{reference:.2f}', '', variant['image']))
                df.at[idx, 'styles1'] = '#'.join(segments)
                df.at[idx, '定价状态'] = '未匹配'
                log_result(idx, row, '未匹配',
                           f'无尺码，窗口内无未用库价，保持 Regular={reference:.2f}、Sale 空')
                continue
            price = candidates[0] / 100
            df.at[idx, 'price1'] = price
            df.at[idx, 'price2'] = price
            segments = [styles_codec.escape(name)]
            for variant in variants:
                segments.append(styles_codec.encode_segment(
                    variant['option_values'], f'{price:.2f}', f'{price:.2f}', variant['image']))
            df.at[idx, 'styles1'] = '#'.join(segments)
            df.at[idx, '定价状态'] = '原价'
            used_prices.add(cents(price))
            log_result(idx, row, '原价',
                       f'无尺码，划线价 {reference:.2f} 窗口内取未用库价 {price:.2f}')
            continue
        # 有尺码：窗口内的未用库价按尺码递增取（梯度），不足时复用最后一个档位
        if not candidates:
            # 窗口内没有未用库价，保持原价（Regular=参考价，Sale 空）
            df.at[idx, 'price1'] = reference
            df.at[idx, 'price2'] = reference
            segments = [styles_codec.escape(name)]
            for variant in variants:
                segments.append(styles_codec.encode_segment(
                    variant['option_values'], f'{reference:.2f}', '', variant['image']))
            df.at[idx, 'styles1'] = '#'.join(segments)
            df.at[idx, '定价状态'] = '未匹配'
            log_result(idx, row, '未匹配',
                       f'窗口内无未用库价，保持 Regular={reference:.2f}、Sale 空')
            continue
        points = [p / 100 for p in candidates]
        # 候选库价多于尺码时，跳过最小的一个档位、从第二个开始取（整体右移一位）；
        # 尺码数不少于候选数时保持原样，从第一个库价开始取。
        if len(points) > len(sizes):
            points = points[1:len(sizes) + 1]
        elif len(sizes) > len(points):
            points = spread_prices(points, len(sizes))
        size_prices = dict(zip(sizes, points))
        low_v, high_v = points[0], points[-1]
        df.at[idx, 'price1'] = low_v
        df.at[idx, 'price2'] = high_v
        segments = [styles_codec.escape(name)]
        for variant in variants:
            sale = size_prices[variant_size(name, variant)]
            segments.append(styles_codec.encode_segment(
                variant['option_values'], f'{sale:.2f}', f'{high_v:.2f}', variant['image']))
        df.at[idx, 'styles1'] = '#'.join(segments)
        df.at[idx, '定价状态'] = '已匹配'
        used_prices.update(cents(p) for p in points)
        log_result(idx, row, '已匹配',
                   f'{len(sizes)} 个尺码 / {len(set(points))} 档；售价 {low_v:.2f}～{high_v:.2f}；'
                   f'同款价差 {(high_v / low_v - 1) * 100:.2f}%')
    replace_file(output_path, lambda path: df.to_csv(path, index=False, encoding='utf-8-sig'), '.csv')
    print(f'尺码梯度定价完成：已处理 {sum(counts.values())}/{len(df)} 条；'
          f'低价 {counts["低价"]}，已匹配 {counts["已匹配"]}，保留原价 {counts["原价"]}，'
          f'未匹配 {counts["未匹配"]}；分配库价 {len(used_prices)}/{len(library)}；'
          f'已保存 {output_path}', flush=True)
    # 返回给下游（13 未用价、16 导出核对）的 used_prices 用「元」的 float，与其 _cents 口径一致。
    return df, {p / 100 for p in used_prices}
