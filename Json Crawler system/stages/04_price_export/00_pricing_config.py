"""价格库与价差上限；只修改这里即可调整定价配置。"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# 价格库：尺码梯度定价的取值池。
price_library = [
    8.99, 9.01, 9.31, 9.33, 9.37, 9.63, 9.71, 9.72, 9.84, 9.86, 9.95, 9.99,
    10.03, 10.05, 10.11, 10.13, 10.15, 10.35, 10.36, 10.38, 10.54, 10.63, 10.64, 10.66,
    10.71, 10.78, 10.83, 10.94, 10.95, 10.99, 11.22, 11.36, 11.48, 11.65, 11.87, 11.95,
    11.99, 12.22, 12.25, 12.36, 12.41, 12.87, 12.92, 12.95, 12.99, 13.02, 13.13, 13.14,
    13.47, 13.69, 13.95, 13.99, 14.25, 14.32, 14.62, 14.83, 14.91, 14.95, 14.99, 15.31,
    15.52, 15.78, 15.95, 15.99, 16.34, 16.53, 16.66, 16.77, 16.95, 16.99, 17.11, 17.34,
    17.57, 17.95, 17.99, 18.62, 18.81, 18.84, 18.95, 18.99, 19.04, 19.25, 19.95, 19.99,
    20.14, 20.19, 20.34, 20.68, 20.74, 20.95, 20.99, 21.3, 21.47, 21.74, 21.95, 21.99,
    22.31, 22.34, 22.81, 22.95, 22.99, 23.14, 23.32, 23.95, 23.99, 24.22, 24.46, 24.63,
    24.95, 24.99, 25.37, 25.95, 25.99, 26.18, 26.34, 26.95, 26.99, 27.31, 27.54, 27.95,
    27.99, 28.11, 28.95, 28.99, 29, 29.31, 29.95, 29.99, 30.54, 30.95, 30.99, 31.26,
    31.52, 31.95, 31.99, 32.14, 32.24, 32.95, 32.99, 33.62, 33.84, 33.95, 33.99, 34.18,
    34.62, 34.95, 34.99, 35, 35.14, 35.33, 35.95, 35.99, 36.47, 36.95, 36.99, 37.21,
    37.95, 37.99, 38.14, 38.52, 38.95, 38.99, 39, 39.54, 39.95, 39.99, 40.02, 40.15,
    40.95, 40.99, 41.32, 41.95, 41.99, 42.51, 42.95, 42.99, 43.16, 43.95, 43.99, 44.82,
    44.95, 44.99, 45.17, 45.95, 45.99, 46.57, 47.82, 48.36, 49, 49.31, 50.03, 50.13,
    50.81, 55, 59, 60, 65, 69, 75, 79, 85, 89, 90, 95, 99, 105, 109, 115, 119,
    125, 129, 135, 145, 155, 169, 179, 189, 199, 209, 219, 229, 239, 259, 299,
    319, 349, 369, 399, 459, 499, 519, 599,
]
# 升序副本：匹配时按距离原价就近取价，需要有序池
price_library_sorted = sorted(price_library)

DEFAULT_SPREAD_PERCENT = 30

# 候选窗口：以采集划线价（原价）为参考价，候选库价范围 = 参考价 × [下界, 上界]。
# 默认 ±25%（0.75～1.25），与 02价格排序 的全局去重窗口一致。
DEFAULT_WINDOW_LOWER = Decimal('0.75')
DEFAULT_WINDOW_UPPER = Decimal('1.25')


@dataclass(frozen=True)
class PriceRules:
    spread_percent: Decimal
    window_lower: Decimal
    window_upper: Decimal

    @property
    def max_ratio(self):
        return Decimal('1') + self.spread_percent / 100


def resolve_rules(spread_percent=None, window_lower=None, window_upper=None):
    """工作台与脚本共用校验。

    spread_percent：同款最高价/最低价 ≤ 1 + 百分比/100（默认 30）。
    window_lower / window_upper：候选窗口系数，候选库价 = 参考价 × [lower, upper]（默认 0.75～1.25）。
    """
    try:
        spread = Decimal(str(DEFAULT_SPREAD_PERCENT if spread_percent is None else spread_percent))
    except (InvalidOperation, ValueError):
        raise ValueError('同款总价差必须是 0～100 的百分比') from None
    if not spread.is_finite() or not 0 <= spread <= 100:
        raise ValueError('同款总价差必须是 0～100 的百分比')
    try:
        lower = Decimal(str(DEFAULT_WINDOW_LOWER if window_lower is None else window_lower))
        upper = Decimal(str(DEFAULT_WINDOW_UPPER if window_upper is None else window_upper))
    except (InvalidOperation, ValueError):
        raise ValueError('候选窗口必须是小数（如 0.75 和 1.25）') from None
    if not (lower.is_finite() and upper.is_finite()) or not 0 < lower <= upper:
        raise ValueError('候选窗口必须满足 0 < 下界 ≤ 上界（如 0.75 ~ 1.25）')
    return PriceRules(spread, lower, upper)
