# 登记为模块名 analyzer：本层只做「读文件 + 组织数据」，写 CSV 与 UI 通信在 99_pipeline_entry。
import json
from math import prod as combination_count
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

import config
import option_split
import product_parser


# 勾选名归一：直接借用 option_split，保持与拆行完全一致的颜色别名口径。
def _expand_selected(selected_options):
    return option_split.expand_selected_names(selected_options)


# 逐个吐出 (来源文件, 商品字典)：统计/预览读取汇总目录，正式导出读取单个域名 JSON。
def iter_products(data_dir):
    root = Path(data_dir)
    if root.is_file():
        files = [root]
    else:
        # 阶段 02 产物目录：一个文件就是一个域名，不再往里钻，避免把备份文件也读进来
        files = sorted(root.glob('*.json'))
    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                data = json.load(fh)
            products = data if isinstance(data, list) else [data]
            for item in products:
                if not isinstance(item, dict):
                    raise ValueError('商品对象不是字典')
                # 汇总文件里商品可能包一层 {"product": {...}}，统一剥掉后下游只面对商品本体
                prod = item.get('product', item)
                if not isinstance(prod, dict):
                    raise ValueError('product 不是字典')
                # 阶段三只吃阶段二的九字段汇总记录，这里是唯一入口，因此把校验放在这一处：
                # 误投原始 Shopify JSON 时给出指名道姓的错误，而不是让下游拼出错位的 styles 串。
                if not product_parser.is_analysis_product(prod):
                    raise ValueError('不是阶段二产出的九字段汇总记录（缺 option_counts / url / price）')
                yield f, prod
        except Exception as exc:
            # 带上文件名再抛：否则整批导出时看不出是哪一个域名的 JSON 有问题
            raise ValueError(f'读取商品 JSON 失败：{f}: {exc}') from exc


# 汇总目录第一层的每个 JSON 对应一个域名，99 用文件名拼 <域名>_style.csv。
def domain_groups(data_dir):
    root = Path(data_dir)
    return [(f.stem, f) for f in sorted(root.glob('*.json'))]


# 只读统计：每列出现在多少商品里、值总数、以及「选项组合签名」的件数，供 GUI 显示分布。
def stat_options(data_dir):
    opt_count = Counter()
    opt_total = Counter()
    combos = defaultdict(int)
    for f, prod in iter_products(data_dir):
        # 统计口径与拆行一致：同样按 SKIP_OPTIONS 剔掉非款式列，否则 GUI 数字和实际行数对不上
        opts = product_parser.get_sorted_options(prod, skip_options=config.SKIP_OPTIONS)
        names = tuple(o.get('name', '') for o in opts)
        combos[names] += 1
        for o in opts:
            n = o.get('name', '')
            opt_count[n] += 1
            opt_total[n] += len(o.get('values', []))
    return opt_count, opt_total, combos


# 只生成预览所需的前 row_limit 行，组合总数通过各维度数量相乘统计。
def expand_cartesian(data_dir, selected_options, option_limits=None, row_limit=200, stop=None):
    rows, total, missing_count = [], 0, 0
    selected = list(selected_options)
    product_parser.normalize_option_limits(option_limits)
    row_limit = max(0, int(row_limit))
    for _, prod in iter_products(data_dir):
        if stop is not None and stop.is_set():
            break
        # 拆色只是把 Color 连续分段，既不改变组合总数，也不改变逐组合预览的顺序。
        # 因此直接读取完整维度，避免生成所有颜色块并反复复制商品。
        options, prices, entries = product_parser.selected_product_combinations(
            prod, selected, config.SKIP_OPTIONS, option_limits=None,
            max_entries=max(0, row_limit - len(rows)))
        total += combination_count(len(opt['values']) for opt in options)
        names = [opt['name'] for opt in options]
        have = _expand_selected(names)
        # 勾了但这件商品没有的列（例如勾 Size 而商品只有 Color）计入 missing，提醒用户会有空列
        if any(n.casefold() not in have for n in selected):
            missing_count += 1
        for entry in entries:
            values = dict(zip(names, entry['combo']))
            color_value = next((values[name] for name in names if product_parser.is_color_name(name)), '')
            rows.append({
                'handle': prod.get('handle') or unquote(urlsplit(prod.get('url', '')).path).rstrip('/').split('/')[-1],
                'title': prod.get('title', ''),
                'variant_title': ' / '.join(entry['combo']),
                'price': prices['price'],
                'compare_at_price': prices['compare_at_price'],
                'currency': prices['currency'],
                'image_url': entry['image_url'],
                'image_status': entry['image_status'],
                **{name: values.get(name, color_value if product_parser.is_color_name(name) else '') for name in selected},
            })
    return rows, total, missing_count


# 十字段行的批量入口：按域名把汇总 JSON 里的商品全部转成 CSV_FIELDS 那十列。
def build_ten_field_rows(data_dir, selected_options=None, option_limits=None,
                         color_images_only=False, failures=None, output_products=None):
    rows, invalid = [], 0
    for f, prod in iter_products(data_dir):
        url = prod['url']  # 汇总记录自带链接，仅用于失败清单里指名道姓
        try:
            rows.extend(option_split.parse_product_rows(
                {'product': prod}, selected_options=selected_options,
                option_limits=option_limits, color_images_only=color_images_only,
                output_products=output_products))
        except product_parser.InvalidProductError as exc:
            # 无效币种、价格或超长款式：记录原因并继续其它商品。
            invalid += 1
            if failures is not None:
                failures.append(f"{f.name}：{prod.get('title', '')} | {url} | {exc}")
            print(f'[跳过商品] {prod.get("title", "")} | {url} | {exc}')
    if invalid:
        print(f'[导出统计] {data_dir}：{len(rows)} 行可导出，数据或币种无效跳过 {invalid} 个')
    return rows, invalid
