# ======================== 网络与 URL 层 ========================
# 登记为旧模块名 network_utils：构造 Shopify .json 链接、按 JSON URL 去重、抓包取 JSON、识别币种与汇率换算。
import json
import math
import ssl
import time
import urllib.request
from urllib.parse import urlparse, urlunparse
from url_utils import normalize_request_url, normalize_url_dashes

try:
    import certifi  # 有 certifi 时用其 CA 根证书校验 HTTPS，规避本机证书链缺失
except ImportError:
    certifi = None

_exchange_rates_cache = {}   # 币种→汇率缓存，进程内只请求一次 er-api，避免每个商品重复拉取
_shop_currency_cache = {}    # 店铺 origin→币种缓存，同一店铺只识别一次币种


def to_shopify_json_url(url):
    # 把商品页 URL 转成 Shopify 的 products/*.json 形式：去掉末尾斜杠后补 .json。
    parsed = urlparse(normalize_request_url(url))
    path = parsed.path.rstrip("/")  # 先剥掉尾部斜杠，避免出现 //.json
    if not path.endswith(".json"):  # 已是 .json 则不重复追加
        path = f"{path}.json"
    # 丢弃 query/fragment，只保留 scheme+netloc+path，作为去重与抓包的规范键
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def group_targets_by_json_url(targets):
    # 按规范化后的 JSON URL 去重：同一商品的多个链接只保留一个，返回分组与跳过数。
    json_url_groups = {}
    duplicate_product_count = 0
    for title, url, md5 in targets:
        original_url = normalize_request_url(url)
        if not original_url:  # 归一化后为空的脏链接直接丢弃
            continue
        json_url = to_shopify_json_url(original_url)
        if json_url in json_url_groups:  # 相同 JSON URL 视为同一商品，累加重复计数后跳过
            duplicate_product_count += 1
            continue
        title_text = str(title).strip() if title is not None else ""
        json_url_groups[json_url] = {
            "title": title_text,  # 分类标题，后续作为 fennei
            "md5": str(md5 or "").strip(),  # 阶段 01 生成的 url 的 md5，透传进商品记录
            # original_url 剥掉 query/fragment，存成干净的规范商品页地址
            "original_url": urlunparse(
                urlparse(original_url)._replace(query="", fragment="")
            ),
        }
    return json_url_groups, duplicate_product_count


def fetch_json(tab, json_url, stop_event=None):
    # 用浏览器监听网络包取回 JSON：Shopify 直接 GET .json 可能被拦，故抓真实响应。
    request_url = normalize_request_url(json_url)
    tab.listen.start(request_url)  # 监听和访问共用编码后的 URL，匹配浏览器实际请求
    try:
        tab.get(request_url)
    except Exception as exc:
        print(f"  商品请求异常：{request_url}（{exc}）")
        raise
    packet = None
    deadline = time.monotonic() + 30  # 最长等 30 秒，防止响应迟迟不来时永久阻塞
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():  # 支持中途停止
            return 0, None
        remaining = deadline - time.monotonic()
        # 小步轮询等待（0.05~1.0 秒），既能及时响应停止又能留出取包时间
        packet = tab.listen.wait(timeout=min(1.0, max(0.05, remaining)))
        if packet:
            break
    status = packet.response.status if packet else 0  # 没抓到包按 0（视为失败）处理
    if not packet:
        print(f"  未监听到商品 JSON 响应（status=0）：{request_url}")
    elif status != 200:
        print(f"  商品 JSON HTTP {status}：请求={request_url}；响应={getattr(packet, 'url', request_url)}")
    if status == 200:
        if stop_event is not None and stop_event.is_set():
            return 0, None
        # 优先取渲染后的纯文本，再退回 textContent，从中解析 JSON
        text = tab.run_js("return document.body.innerText")
        if not text:
            text = tab.run_js("return document.body.textContent")
        try:
            return status, json.loads(text)
        except json.JSONDecodeError:
            # 浏览器把 JSON 包在 <pre> 里展示时，改从 pre 节点取文本再解析
            pre_text = tab.run_js("return document.querySelector('pre')?.innerText || ''")
            if pre_text:
                try:
                    return status, json.loads(pre_text)
                except json.JSONDecodeError:
                    pass
            print(f"  商品 JSON HTTP 200，但响应内容无法解析：{request_url}")
            return status, None  # 两处都解析失败，返回 200 但空数据
    return status, None


def shop_origin(url):
    # 从任意商品 URL 提取店铺根（scheme+netloc），用于拼 /cart.js 识别币种。
    parsed = urlparse(normalize_url_dashes(url) or url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def extract_currency(data):
    # 从 JSON 数据里尽力抠出 ISO 三位币种码：先看顶层字段，再看各变体的币种字段。
    if not isinstance(data, dict):
        return ""
    product = data.get("product", data)  # cart.js 是顶层，商品 JSON 包在 product 下，兼容两者
    for key in ("currency", "presentment_currency"):
        value = str(product.get(key) or data.get(key) or "").strip().upper()
        if len(value) == 3 and value.isalpha():  # 只要合法的三位字母币种码
            return value
    for variant in product.get("variants") or []:  # 顶层没有则遍历变体找价格币种
        for key in ("price_currency", "compare_at_price_currency", "currency"):
            value = str(variant.get(key) or "").strip().upper()
            if len(value) == 3 and value.isalpha():
                return value
    return ""


def detect_shop_currency_http(url):
    # 用 urllib 直连 /cart.js 识别店铺币种（浏览器方式失败时的兜底），带 origin 级缓存。
    origin = shop_origin(url)
    if not origin:
        return ""
    if origin in _shop_currency_cache:  # 命中缓存则不再请求
        return _shop_currency_cache[origin]
    currency = ""
    try:
        req = urllib.request.Request(f"{origin}/cart.js", headers={"User-Agent": "Mozilla/5.0"})
        context = ssl.create_default_context()
        if certifi is not None:
            context.load_verify_locations(cafile=certifi.where())  # 用 certifi 证书链校验
        with urllib.request.urlopen(req, timeout=10, context=context) as response:
            currency = extract_currency(json.loads(response.read().decode()))
    except Exception as exc:
        print(f"  识别币种失败: {origin} ({exc})")
    _shop_currency_cache[origin] = currency  # 无论成功与否都缓存，避免同店反复尝试
    if currency:
        print(f"  店铺币种: {currency} ({origin})")
    else:
        print(f"  未识别店铺币种，价格按原样保存 ({origin})")  # 识别不到则价格保留原币种
    return currency


def fetch_exchange_rates():
    # 拉取一次以 USD 为基准的汇率表并缓存，供价格换算复用；失败返回空表触发回退。
    if _exchange_rates_cache:  # 已有缓存直接返回，进程内只请求一次
        return _exchange_rates_cache
    try:
        req = urllib.request.Request("https://open.er-api.com/v6/latest/USD", headers={"User-Agent": "Mozilla/5.0"})
        context = ssl.create_default_context()
        if certifi is not None:
            context.load_verify_locations(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=10, context=context) as response:
            data = json.loads(response.read().decode())
        rates = data.get("rates") or {}
        if rates:
            _exchange_rates_cache.update(rates)  # 填入缓存，后续换算不再联网
            print(f"[汇率] 已获取 {len(rates)} 种货币")
    except Exception as exc:
        print(f"[汇率] 获取失败: {exc}")  # 取汇率失败：后续换算将保留原币种
    return _exchange_rates_cache


def convert_price_to_usd(price_str, currency, rates=None):
    # 单个价格串换算成 USD；任一步不满足就原样返回（回退，不臆造换算）。
    if not price_str or not currency:  # 无价格或无币种，无从换算，保持原值
        return price_str
    currency = str(currency).upper().strip()
    if currency == "USD":  # 本身就是美元，直接返回
        return price_str
    if rates is None:
        rates = fetch_exchange_rates()
    rate = (rates or {}).get(currency)
    if not rate:  # 汇率表缺失或该币种无汇率，回退保留原价格与原币种
        return price_str
    try:
        amount = float(str(price_str).strip())  # 价格必须能转成数字
    except (ValueError, TypeError):
        return price_str  # 非数字价格不动，交由原样保存
    return f"{amount / float(rate):.2f}"  # er-api 以 USD 为基准，故除以该币种汇率得美元，保留两位


def prices_to_usd(price, compare, currency):
    # 对售价与原价一起做 USD 换算，返回 (售价, 原价, 币种)；无法换算时币种回退为原值。
    currency = str(currency or "").strip().upper()
    if not currency or currency == "USD":
        return price, compare, "USD" if currency == "USD" else currency
    rates = fetch_exchange_rates()
    try:
        rate = float(rates.get(currency, 0))
        amounts = [float(value) for value in (price, compare) if value not in (None, "")]
        valid = (rate > 0 and math.isfinite(rate)
                 and all(amount >= 0 and math.isfinite(amount) for amount in amounts))
    except (TypeError, ValueError):
        valid = False
    if not valid:  # 汇率不可用或不认识该币种：价格原样、币种保留原值
        return price, compare, currency
    return (
        convert_price_to_usd(price, currency, rates),
        convert_price_to_usd(compare, currency, rates),
        "USD",  # 换算成功才把币种标记为 USD，供下游与阶段 03 判断
    )
