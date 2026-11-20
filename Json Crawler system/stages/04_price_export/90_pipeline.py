"""阶段 04 顺序编排；具体处理逻辑位于各前缀步骤文件。"""
from pathlib import Path

from common.step_loader import load_step
from common.stop import stopped

HERE = Path(__file__).resolve().parent


class StopRequested(Exception):
    """用户请求停止，已完成步骤的产物保留。"""


def run(input_file, on_step=None, stop=None, rules=None,
        make_raw=True, match=True):
    # 按数字前缀路径逐个加载步骤（前缀文件不能直接 import）
    merge = load_step(HERE / '10_merge.py')
    fix_prices = load_step(HERE / '11_fix_prices.py')
    export_wp = load_step(HERE / '14_export_wp.py')

    # 步骤表按勾选拼出来：没勾的流程不进表，既不执行也不占进度条
    names = ['合并十字段表']
    if make_raw:
        names.append('原价修正')
    if match:
        names += ['按尺码匹配价格', '导出未匹配价格']
    names += ['导出 WooCommerce']
    total = len(names)
    state = {'index': 0}

    def checkpoint(name):
        # 步骤边界检查点：已请求停止则抛 StopRequested，交由入口按"停止"处理而非报错
        if stopped(stop):
            print(f'已停止，跳过：{name}', flush=True)
            raise StopRequested(name)

    def begin(name):
        # 进入某一步：先把进度报给工作台，再检查停止
        state['index'] += 1
        if on_step is not None:
            on_step(state['index'], total, name)
        checkpoint(name)

    # 10 →(11)→(12→13)→14；括号内步骤由勾选决定是否执行
    begin('合并十字段表')
    data, paths = merge.run(input_file, stop=stop)

    # 原价表：修正倒挂（D<C→D=C；内嵌价 p2<p1→p2=p1），修正结果另存一份，合并表本身不动
    corrected = data
    if make_raw:
        begin('原价修正')
        corrected = fix_prices.run(data, paths.raw, stop=stop)

    if match:
        begin('按尺码匹配价格')
        match_prices = load_step(HERE / '12_match_prices.py')
        unused_prices = load_step(HERE / '13_unused_prices.py')
        # 匹配产出 used_prices，是下一步「导出未匹配价格」的输入
        _, used_prices = match_prices.run(
            corrected, paths.matched, stop=stop, rules=rules, source_data=data,
        )
        begin('导出未匹配价格')
        unused_prices.run(used_prices, paths.unused)

    # 导出输入：勾了哪个流程就只导哪张表；两个都没勾则直接导合并表
    sources = []
    if make_raw:
        sources.append(paths.raw)
    if match:
        sources.append(paths.matched)
    if not sources:
        sources.append(paths.merged)

    begin('导出 WooCommerce')
    # WP 直接由 style 表（原价表/匹配表）转，产物链 CSV → WP，不再经过 Shopify CSV
    wp = export_wp.run(sources)
    return {
        'paths': paths,
        'wp': wp,
        'make_raw': make_raw,
        'match': match,
    }
