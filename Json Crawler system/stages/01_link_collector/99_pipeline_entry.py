"""阶段 01 入口：分类列表 → 域名链接 CSV。"""
from pathlib import Path
from common.atomic_io import replace_file

from common.step_loader import alias_step

HERE = Path(__file__).resolve().parent  # 本阶段目录，供按绝对路径加载各数字前缀步骤文件


def run(settings, stop, emit):
    # 工作台/worker 调用入口：把带前缀的步骤文件登记成旧模块名（config/logger/...），阶段内代码即可 import config
    config = alias_step('config', HERE / '00_config.py')
    alias_step('logger', HERE / '80_logger.py')
    alias_step('browser_utils', HERE / '20_browser.py')
    alias_step('file_utils', HERE / '40_file_utils.py')
    collector = alias_step('collector', HERE / '30_collector.py')  # 最后加载：其 import 依赖上面别名已就绪

    # 解析用户粘贴的分类文本（每行 URL，可带标题）
    categories = collector.parse_categories(settings['categories'])
    if not categories:
        raise ValueError('请填写至少一个有效分类 URL')
    output_dir = Path(settings['project']) / 'Json'  # 阶段 01 产物目录：项目/Json/<域名>.csv
    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = config.CollectConfig(
        categories=categories, output_dir=str(output_dir),
        max_pages=int(settings.get('max_pages', 0)), xpath=settings.get('xpath', ''),  # max_pages=0 不限量；xpath 非空走 XPath 模式
        proxy=config.PROXY_SERVER,  # 两个采集阶段固定使用本地 7897 代理
        browser_path=settings.get('browser_path') or None,  # 浏览器路径：留空自动探测 Chrome/Edge
    )
    # 回调把采集内部事件转成工作台事件：progress 更新进度/计数（emit 会加 @@CRAWLER_EVENT@@ 前缀）
    runner = collector.CollectorRunner(
        cfg, stop, on_progress=lambda current, total, title: emit(
            'progress', current=current, total=total, text=title),
        on_count=lambda count: emit('progress', text=f'已采集 {count} 条链接'),
    )
    runner.run()  # 阻塞执行整个采集（子进程内运行；print 已被 logger 转发到 GUI）
    if stop.is_set():
        return  # 被停止：runner.run 已在 finally 落盘已采部分，这里不再上报产物/报错
    # run() 的 finally 必定赋好 last_report，SaveReport 又是字段齐全的 dataclass，直接取属性即可
    report = runner.last_report
    runner.errors.extend(report.errors)
    if report.recovery_files:
        runner.errors.append("部分链接另存 recovery 文件，需恢复后再运行商品采集")
    if runner.errors:  # 有分类/保存警告：写失败清单文件并逐条 print 到日志
        fail_path = output_dir / '_stage01_failures.txt'
        replace_file(fail_path, lambda path: Path(path).write_text('\n'.join(str(item) for item in runner.errors), encoding='utf-8'), '.txt')
        emit('artifact', path=str(fail_path), text='阶段一失败清单')
        for item in runner.errors:
            print(f'分类或保存警告：{item}', flush=True)  # flush 保证子进程日志即时转发到 GUI
    else:
        (output_dir / '_stage01_failures.txt').unlink(missing_ok=True)
    if report.recovery_files:  # 提示因原文件损坏而另存的 recovery 文件
        print(f'已另存 recovery 文件：{report.recovery_files}', flush=True)
    if report.written_rows <= 0:  # 完全没采到也没写成：按失败抛出，让工作台显示错误
        raise RuntimeError('没有写成任何链接，请查看日志后重试')
    emit('artifact', path=str(Path(cfg.output_dir)), text=report.describe())  # 上报产物目录与可读摘要

    return 'partial' if runner.errors else 'success'
