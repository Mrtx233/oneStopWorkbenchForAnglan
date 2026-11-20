"""主工作台应用类。"""
from .build import CrawlerBuild
from .pages import CrawlerPages
from .dialogs import CrawlerDialogs
from .runtime import CrawlerRuntime


# CrawlerApp 用多继承把四个 mixin 拼成完整工作台：
#   CrawlerBuild 搭骨架与 ttk 样式、持有 tkinter 变量与 controller；
#   CrawlerPages 填充各阶段页面控件；CrawlerDialogs 处理路径选择与参数快照校验；
#   CrawlerRuntime 负责启停、进度条、日志与事件轮询。类体本身为空，行为全在 mixin。
class CrawlerApp(CrawlerBuild, CrawlerPages, CrawlerDialogs, CrawlerRuntime):
    pass
