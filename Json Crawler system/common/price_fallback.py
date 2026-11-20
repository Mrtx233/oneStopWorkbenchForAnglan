"""商品售价与划线价缺失时互补，不改变已有的两个价格。"""

from decimal import Decimal, InvalidOperation


def _is_missing_price(value):
    if value is None or isinstance(value, str) and not value.strip():
        return True
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def fill_missing_prices(price, compare):
    """None、空白及数字/字符串零价格算缺失；两者都缺失则均为空串。"""
    price_missing = _is_missing_price(price)
    compare_missing = _is_missing_price(compare)
    if price_missing and compare_missing:
        return '', ''
    if price_missing:
        return compare, compare
    if compare_missing:
        return price, price
    return price, compare
