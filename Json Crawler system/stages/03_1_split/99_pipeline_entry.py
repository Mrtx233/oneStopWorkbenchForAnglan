"""阶段 03 切分入口：对阶段三产出的十字段表 CSV 做两种切分，并同步切分对应 JSON。

输入自动取自当前项目的 CSV/ 目录下的 <域名>_style.csv，
无需用户手动选择文件。切分模式由 settings['split_mode'] 决定：
  - parts：按 title 分组、按价格排序后，按「商品块(md5)」轮询均分成 N 份（settings['split_parts']）
  - each ：每个不同的 title 值独立写成一个文件

切分 CSV 后，按各份 CSV 的 md5 集合从 Json/Data Analysis/<域名>.json 筛出对应商品对象，
写成与切分 CSV 同名同目录的 .json（同一 md5 不跨文件，故每个商品只归入一份）。

复用工作台事件协议：progress 上报进度、artifact 上报产物、result 上报结果。
"""
from pathlib import Path

from common.step_loader import alias_step

HERE = Path(__file__).resolve().parent


def _collect_style_csvs(csv_dir):
    """扫描 CSV 目录第一层的 <域名>_style.csv，排除合并表、隐藏文件与锁文件。"""
    if not csv_dir.is_dir():
        return []
    files = []
    for path in csv_dir.iterdir():
        name = path.name
        if path.suffix.lower() != '.csv' or not path.is_file():
            continue
        if name.startswith('~$') or name.startswith('.'):
            continue
        if not name.endswith('_style.csv'):
            continue
        files.append(path)
    return sorted(files)


def _domain_from_style_csv(csv_path):
    """从 <域名>_style.csv 反推域名（去掉 _style 后缀）。"""
    stem = csv_path.stem
    if stem.endswith('_style'):
        return stem[:-len('_style')]
    return stem


def run(settings, stop, emit):
    config = alias_step('config', HERE / '00_config.py')
    splitter = alias_step('splitter', HERE / '20_split.py')

    project = Path(settings['project'])
    csv_dir = project / 'CSV'
    analysis_dir = project / 'Json' / 'Data Analysis'
    files = _collect_style_csvs(csv_dir)
    if not files:
        raise ValueError('CSV 目录没有可切分的 _style.csv，请先运行阶段三')

    mode = settings.get('split_mode', config.MODE_SPLIT_PARTS)
    parts = settings.get('split_parts', config.DEFAULT_PARTS)
    price_col = settings.get('split_price_col') or config.DEFAULT_PRICE_COL
    overwrite = bool(settings.get('split_overwrite', True))

    if mode not in (config.MODE_SPLIT_PARTS, config.MODE_SPLIT_EACH):
        raise ValueError(f'未知切分模式：{mode}')

    if mode == config.MODE_SPLIT_PARTS:
        try:
            parts = max(1, int(parts))
        except (TypeError, ValueError):
            raise ValueError('拆分份数必须是正整数') from None
        price_label = price_col if price_col else '（空，保持原序）'
        print(f'切分模式：按 title 均分 {parts} 份，价格列 {price_label}', flush=True)
    else:
        print('切分模式：按 title 各自成文件', flush=True)

    results = []
    failures = []
    for index, path in enumerate(files, 1):
        if stop.is_set():
            return
        emit('progress', current=index, total=len(files), text=f'切分 {path.name}')
        try:
            if mode == config.MODE_SPLIT_PARTS:
                stat = splitter.split_by_title(path, parts, price_col=price_col, overwrite=overwrite)
            else:
                stat = splitter.split_by_title_each(path, overwrite=overwrite)
            if stat is None:
                failures.append(f'{path.name}：文件为空或缺少 title 列')
                continue
            results.append(stat)
            for out in stat['outputs']:
                emit('artifact', path=str(out), text='切分产物')

            # 同步切分对应 JSON：按各份 CSV 的 md5 集合筛商品对象。
            domain = _domain_from_style_csv(path)
            json_path = analysis_dir / f'{domain}.json'
            products = splitter.load_json_products(json_path)
            if products is None:
                print(f'[提示] 未找到对应 JSON，跳过 JSON 同步切分：{json_path}', flush=True)
                continue
            json_written = splitter.split_json_by_md5(
                products, stat.get('md5_sets', {}),
                json_targets=stat.get('json_targets'), overwrite=overwrite)
            for jp, count in json_written:
                emit('artifact', path=str(jp), text=f'JSON 切分产物（{count} 个商品）')
        except Exception as exc:
            failures.append(f'{path.name}：{exc}')
            print(f'切分失败，跳过 {path.name}：{exc}', flush=True)

    if not results:
        raise RuntimeError('没有成功切分任何文件')

    total_out = sum(len(stat['outputs']) for stat in results)
    print(f'切分完成：{len(results)} 个文件，共产出 {total_out} 个 CSV（含同步 JSON）', flush=True)
    if failures:
        print('失败清单：', flush=True)
        for item in failures:
            print(f'  {item}', flush=True)

    return 'partial' if failures else 'success'
