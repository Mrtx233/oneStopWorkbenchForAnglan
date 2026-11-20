"""第三步：输出本轮未使用的价格库金额。"""
from common.atomic_io import replace_file
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd

from common.step_loader import load_step

# 价格库全量来自 00 配置，用于做差集求未用价
_pricing = load_step(Path(__file__).with_name('00_pricing_config.py'))
price_library_sorted = _pricing.price_library_sorted


def _cents(value):
    # 统一折成整数分再比较：库价是 float/int 字面量，已用价是除法结果，
    # 直接 == 会踩 float 精度（如 33.84 == 33.8400000001 误判），口径与 12_match_prices.cents 一致。
    return int((Decimal(str(value)) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def run(used_prices, unused_path):
    # 库中剔除本轮已占用价 = 剩余可用价，导出供人工核对/复用
    used_cents = {_cents(p) for p in used_prices}
    unused_prices = [p for p in price_library_sorted if _cents(p) not in used_cents]
    # utf-8-sig 带 BOM，保证 Excel 打开中文表头不乱码
    replace_file(unused_path, lambda path: pd.DataFrame({'未匹配价格': unused_prices}).to_csv(path, index=False, encoding='utf-8-sig'), '.csv')

    print('\n' + '#' * 110)
    print(f"第三步：未匹配到的价格（价格库 {len(price_library_sorted)} 个，用到 {len(used_prices)} 个，未用 {len(unused_prices)} 个）")
    print('#' * 110)
    print(f"已保存: {unused_path}")
    return unused_path
