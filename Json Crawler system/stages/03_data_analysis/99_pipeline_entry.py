"""阶段 03 入口：汇总统计、组合预览、每域名十字段 CSV。"""
import csv
import json
from pathlib import Path
from common.atomic_io import replace_file

from common.step_loader import alias_step

HERE = Path(__file__).resolve().parent


def run(settings, stop, emit):
    # 登记顺序 = 依赖顺序：先 config，再 product_parser / option_split，
    # 最后 analyzer（它 import 前面几个）；顺序错了步骤里的 import config 会找不到模块。
    config = alias_step('config', HERE / '00_config.py')
    # 30 会把 31/32 两段 exec 合并成一个模块，返回值即模块引用
    product_parser = alias_step('product_parser', HERE / '30_product_parser.py')
    option_split = alias_step('option_split', HERE / '10_option_split.py')
    analyzer = alias_step('analyzer', HERE / '40_analyzer.py')

    source = Path(settings['project']) / 'Json' / 'Data Analysis'
    groups = analyzer.domain_groups(source)
    if not groups:
        raise ValueError('Data Analysis 目录没有汇总 JSON，请先运行阶段二')
    # 默认按 Color + Size 拆行，与界面上的勾选项一致
    selected = settings.get('options', ['Color', 'Size'])
    # 上限在这里先校验：输入非法要在工作台刚启动时就报错，而不是跑到一半
    limits = product_parser.normalize_option_limits(settings.get('option_limits'))
    color_images_only = bool(settings.get('color_images_only'))
    gallery_image_limit = settings.get('gallery_image_limit', 4)
    if isinstance(gallery_image_limit, bool):
        raise ValueError('无颜色补图数必须是 0 或更大的整数')
    if isinstance(gallery_image_limit, int):
        pass
    elif isinstance(gallery_image_limit, str) and gallery_image_limit.strip().isdecimal():
        gallery_image_limit = int(gallery_image_limit.strip())
    else:
        raise ValueError('无颜色补图数必须是 0 或更大的整数')
    if gallery_image_limit < 0:
        raise ValueError('无颜色补图数必须是 0 或更大的整数')
    if limits:
        print(f'属性上限（每行最多 N 个，多余拆行）：{limits}', flush=True)
    if color_images_only:
        print('拆色不补相册：src_links 只保留本件颜色图', flush=True)
    # 汇总 JSON 已由阶段二统一为 USD，本阶段可完全离线导出。
    counts, totals, combos = analyzer.stat_options(source)
    selected = option_split.select_option_names(
        selected, (name for name, total in totals.items() if total > 0),
        include_other=bool(settings.get('include_other_options', False)),
    )
    if settings.get('include_other_options', False):
        print(f'其他维度参与组合，本轮选项：{selected}', flush=True)
    emit('stats', options=dict(counts), totals=dict(totals), products=sum(combos.values()))
    if settings.get('action') == 'preview':
        # 只生成前 200 个组合，其余按维度数量计算总数，不展开也不落盘。
        rows, total, missing = analyzer.expand_cartesian(
            source, selected, option_limits=limits, row_limit=200, stop=stop)
        if not stop.is_set():
            emit('preview', rows=rows, total=total, missing=missing)
        return
    output = Path(settings['project']) / 'CSV'
    output.mkdir(parents=True, exist_ok=True)
    exported = 0
    failures = []
    for index, (domain, path) in enumerate(groups, 1):
        if stop.is_set():
            return  # 一个域名一个文件，停止时最多丢当前这个，已写出的表都是完整的
        try:
            products = []
            rows, skipped = analyzer.build_ten_field_rows(
                path, selected_options=selected, option_limits=limits,
                color_images_only=color_images_only, failures=failures,
                output_products=products, gallery_image_limit=gallery_image_limit)
            if not rows:
                print(f'跳过空文件：{path}', flush=True)
                continue
            target = output / f'{domain}_style.csv'
            json_target = target.with_suffix('.json')
            # 与 CSV 一行一商品对应，保存拆色后的新 md5 和本块颜色，供阶段 3.1 同步切分。
            def _write_products(tmp_path):
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(products, f, ensure_ascii=False, indent=2)
            replace_file(json_target, _write_products, '.json')
            # 原子写盘统一走 replace_file：先写同目录临时文件再 os.replace，
            # 中途被杀或断电不会留下半截 CSV，也不会覆盖成空文件。
            # utf-8-sig 带 BOM，Excel/WPS 双击打开中文不乱码；csv.writer 自动处理含逗号/换行的字段。
            def _write(tmp_path):
                with open(tmp_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(config.CSV_FIELDS)
                    for row in rows:
                        writer.writerow([row.get(c, '') for c in config.CSV_FIELDS])
            replace_file(target, _write, '.csv')
            exported += 1
            emit('progress', current=index, total=len(groups), text=f'{domain}：{len(rows)} 行，跳过 {skipped} 个')
            emit('artifact', path=str(target), text='十字段表')
            emit('artifact', path=str(json_target), text='十字段表对应商品 JSON')
        except Exception as exc:
            # 单个域名失败不中断整轮：记下原因，最后汇总成一个清单文件给使用者核对
            failures.append(f'{domain}：{exc}')
            print(f'导出失败，跳过 {domain}：{exc}', flush=True)
    if failures:
        fail_path = output / '_stage03_failures.txt'
        replace_file(fail_path, lambda path: Path(path).write_text('\n'.join(failures), encoding='utf-8'), '.txt')
        emit('artifact', path=str(fail_path), text='阶段三失败清单')
    else:
        (output / '_stage03_failures.txt').unlink(missing_ok=True)
    if not exported:
        raise ValueError('没有可导出的商品')

    return 'partial' if failures else 'success'
