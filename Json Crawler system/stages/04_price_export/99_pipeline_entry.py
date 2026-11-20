"""阶段四接口：十字段表 → 合并、尺码定价、WooCommerce 导出。"""
from pathlib import Path

from common.step_loader import load_step

HERE = Path(__file__).resolve().parent


def run(settings, stop, emit):
    # 输入优先取工作台指定路径，否则默认项目下的 CSV 目录
    source = Path(settings.get('price_input') or (Path(settings['project']) / 'CSV'))
    if not source.exists():
        raise ValueError(f'价格处理输入不存在：{source}')
    if stop.is_set():
        return
    # 两个流程开关：未勾选的流程整段不跑，也就不会落对应的产物文件
    make_raw = bool(settings.get('make_raw_prices', False))
    match = bool(settings.get('match_prices', True))
    # 加载配置与编排步骤（数字前缀文件需按路径加载）
    pricing = load_step(HERE / '00_pricing_config.py')
    pipeline = load_step(HERE / '90_pipeline.py')
    # 解析工作台传入的价差上限与候选窗口，尺码梯度匹配使用这些参数
    rules = pricing.resolve_rules(settings.get('price_spread_percent'),
                                  settings.get('window_lower'),
                                  settings.get('window_upper'))
    print(f'尺码梯度定价：同款总价差 ≤ {rules.spread_percent}%，'
          f'候选窗口 [{rules.window_lower}, {rules.window_upper}]', flush=True)
    flows = [name for name, on in (('原价表', make_raw), ('价格匹配', match)) if on]
    print(f'本轮流程：合并表 + {" + ".join(flows) if flows else "直接导出"} + WooCommerce', flush=True)
    try:
        result = pipeline.run(
            source,
            # on_step 回调把步骤进度转成 progress 事件发回工作台
            on_step=lambda current, total, text: emit('progress', current=current, total=total, text=text),
            stop=stop,
            rules=rules,
            make_raw=make_raw,
            match=match,
        )
    except pipeline.StopRequested:
        # 步骤边界停止：以 stopped 状态回报，已完成产物保留，不视为错误
        emit('result', status='stopped', message='价格处理已在当前步骤边界停止，已完成产物已保留')
        return
    # 归位输出基准目录：文件输入取父级、CSV 目录再上跳一级
    base = source.parent if source.is_file() else source
    if base.name.lower() == 'csv':
        base = base.parent
    # 只上报本轮真正产出的目录；两个流程都没勾时改报合并表
    for name, on in (('原价', make_raw), ('价格匹配', match)):
        if on:
            emit('artifact', path=str(base / name), text=name)
    if not (make_raw or match):
        emit('artifact', path=str(result['paths'].merged), text='合并表')
