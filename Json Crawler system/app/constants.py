"""跨进程共享的常量：界面文案、事件协议与代理参数。"""
# 这里只放「多个进程/多个阶段必须取同一个值」的常量，且本模块不 import 任何项目内模块，
# 因此 GUI 进程与四个阶段子进程都能安全加载（不会因为引入 Tk 或 pandas 而变重）。

# 阶段号 → 页面标题；键与 worker.STAGES 及 controller 传入的 stage 编号一致，改动需同步两处
# 5 是阶段三的切分后置动作（十字段表切分），不在侧栏导航中，仅用于事件文案。
NAMES = {1: '链接采集', 2: '商品采集', 3: '数据分析', 4: '价格与导出', 5: '切分'}
# 阶段/任务状态文案：waiting 初始、running 进行中、success/failed/stopped 单次结果，
# partial 表示容错模式跑完但部分阶段失败（见 controller._run 的收尾逻辑）
STATUS = {
    'waiting': '待运行', 'running': '运行中', 'success': '已完成',
    'failed': '失败', 'stopped': '已停止', 'partial': '已完成（部分失败）',
}
# 子进程 stdout 事件行前缀：worker.emit 写出、controller._run 逐行识别，是两者之间唯一的协议约定。
# 只有这一份定义，两侧都从这里 import，不再各自硬编码字面值。
PREFIX = '@@CRAWLER_EVENT@@'

# 两个采集阶段统一使用固定的本地代理。
PROXY_SERVER = 'http://127.0.0.1:7897'
