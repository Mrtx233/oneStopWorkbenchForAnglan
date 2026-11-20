"""阶段 02 入口：域名链接 CSV → 域名商品汇总 JSON。"""
from pathlib import Path
from common.atomic_io import replace_file

from common.step_loader import alias_step

HERE = Path(__file__).resolve().parent

INDEX_NAMES = ('links_index.csv', 'links_index.json')  # 阶段一的索引文件，不是商品链接输入


def collect_input_files(json_dir):
    # 扫描域名链接 CSV；旧版 .json 仅在无同名 .csv 时作为输入，恢复中间态与索引一律排除
    files = []
    if not json_dir.is_dir():
        return files
    for path in json_dir.iterdir():
        suffix = path.suffix.lower()
        if suffix not in ('.csv', '.json') or not path.is_file():
            continue
        if path.name in INDEX_NAMES or '.recovery-' in path.name:
            continue
        if suffix == '.json' and (json_dir / (path.stem + '.csv')).exists():
            continue  # 已迁移为 CSV 的域名不再重复读旧 JSON
        files.append(path)
    return sorted(files)


def run(settings, stop, emit):
    # 先把数字前缀步骤登记成旧模块名，步骤内 `import config` 等才可用；须按依赖顺序加载。
    alias_step('config', HERE / '00_config.py')
    alias_step('logger', HERE / '80_logger.py')
    alias_step('browser_utils', HERE / '20_browser.py')
    alias_step('file_utils', HERE / '25_file_utils.py')
    alias_step('network_utils', HERE / '30_network.py')
    alias_step('product_analysis', HERE / '40_product_analysis.py')
    scraper_runner = alias_step('scraper_runner', HERE / '50_scraper_runner.py')

    project = Path(settings['project'])
    json_dir = project / 'Json'
    files = collect_input_files(json_dir)
    if not files:
        raise ValueError('Json 目录没有域名链接文件，请先运行阶段一')
    failures = []  # 收集失败文件，最后单独落一份失败清单
    analysis = project / 'Json' / 'Data Analysis'
    analysis.mkdir(parents=True, exist_ok=True)  # 汇总产物目录，不存在则创建

    def status(index, text, state):
        # 状态回调：失败项计入清单，同时把进度事件回写给工作台。
        if state == 'failed':
            failures.append(f'{files[index].name}：{text}')
        emit('progress', text=f'{files[index].name}：{text}')

    # 交给运行器执行：传入文件路径列表、项目根、停止事件、回调与跳图位置
    run_error = None
    try:
        results = scraper_runner.ScraperRunner(
            [{'path': str(p)} for p in files], str(project), stop,
            on_file_status=status,
            on_progress=lambda current, total, text: emit('progress', current=current, total=total, text=text),
            skip_positions=settings.get('skip_image_positions') or [],  # 用户在 UI 配置的跳图位置
            use_standard_sizes=settings.get('use_standard_sizes', False),
            keep_description_images=settings.get('keep_description_images', False),
            keep_description_tables=settings.get('keep_description_tables', False),
            browser_path=settings.get('browser_path') or None,  # 浏览器路径：留空自动探测 Chrome/Edge
        ).run()
    except Exception as exc:
        run_error = exc
        results = []
        failures.append(str(exc))
    if stop.is_set():  # 被中断则不再产出失败清单/产物事件
        return
    if failures:
        # 有失败：写出失败清单文件并作为产物上报，便于人工复查而不阻断成功数据
        fail_path = analysis / '_stage02_failures.txt'
        replace_file(fail_path, lambda path: Path(path).write_text('\n'.join(failures), encoding='utf-8'), '.txt')
        emit('artifact', path=str(fail_path), text='阶段二失败清单')
        print('\n'.join(failures), flush=True)
    else:
        (analysis / '_stage02_failures.txt').unlink(missing_ok=True)
    # 统计成功产物（排除失败清单本身）；一个都没有则终止后续阶段
    if run_error is not None:
        raise run_error
    if not results:
        raise RuntimeError('本轮输入没有成功采集或续采的商品，请查看失败清单')
    emit('artifact', path=str(analysis), text=f'商品汇总 JSON（{len(results)} 条有效商品）')
    return 'partial' if failures else 'success'
