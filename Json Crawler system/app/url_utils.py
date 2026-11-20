"""URL 横杠修复与 Unicode 请求编码，保留路径、地区前缀和参数结构。"""
# 采集到的链接里常混进各种 Unicode 破折号及其百分号编码形式，
# 导致同一商品被判成两条链接；将这些横杠变体统一成 "-"。
import re
from urllib.parse import quote, urlsplit, urlunsplit

# 收录需要归一的破折号/连字符变体（U+2010 起至全角 U+FF0D 等一批 Unicode 字符），新增变体只改这里
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2043\u2212\u2e3a\u2e3b\ufe58\ufe63\uff0d"
# 把上面每个字符映射为 ASCII "-" 的转换表：一次 translate 完成全部替换，比逐个 replace 快
# 且不受替换顺序影响。
_DASH_TRANSLATION = str.maketrans({char: "-" for char in _DASHES})
# 再覆盖已被 URL 编码的破折号（如 %E2%80%93）：逐字符 quote 出其 UTF-8 百分号形式后用 | 拼成
# 候选式；IGNORECASE 是因为百分号转义有时写成小写（%e2）。
_ENCODED_DASHES = re.compile(
    "|".join(re.escape(quote(char, safe="")) for char in _DASHES), re.IGNORECASE,
)


def normalize_url_dashes(url):
    """把 URL 中常见非标准横杠及其 UTF-8 百分号编码统一为 ASCII -。"""
    # str(url or "") 容忍 None 与意外类型；strip 去掉复制粘贴带进来的首尾空白
    value = str(url or "").strip().translate(_DASH_TRANSLATION)
    # 第二步再处理已被百分号编码的破折号；两步都是字符级替换，
    # 不动路径分隔符与查询串，所以路径分段、地区前缀、参数结构保持原样。
    return _ENCODED_DASHES.sub("-", value)


def normalize_request_url(url):
    """编码 URL 的路径、查询和锚点，保留已有转义及路径/参数分隔符。"""
    value = normalize_url_dashes(url)
    if not value:
        return value
    parsed = urlsplit(value)

    def encode(component, safe):
        # 只保留合法 %XX，独立百分号编码为 %25；不 unquote，避免把 %2F 等变成分隔符。
        component = re.sub(r'%(?![0-9a-fA-F]{2})', '%25', component)
        encoded = quote(component, safe=safe + '%', encoding='utf-8')
        return re.sub(r'%[0-9a-fA-F]{2}', lambda match: match.group(0).upper(), encoded)

    return urlunsplit((
        parsed.scheme, parsed.netloc,
        encode(parsed.path, "/:@!$&'()*+,;="),
        encode(parsed.query, "/?:@!$&'()*+,;="),
        encode(parsed.fragment, "/?:@!$&'()*+,;="),
    ))
