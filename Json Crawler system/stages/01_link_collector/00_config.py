# ======================== 配置层 ========================
#
# 职责: 集中管理全部常量与任务输入结构。
# 依赖: 标准库与公共代理常量。
# ========================================================

from dataclasses import dataclass, field
from typing import List, Optional
from app.constants import PROXY_SERVER

# ---- 重试与延迟：应对慢站/偶发失败 ----
MAX_RETRIES = 3                     # 分类首页抓不到商品时的最大重试次数
RETRY_DELAY = 2.0                   # 每次首页重试前等待秒数，给页面/网络恢复时间
PAGE_SETTLE_WAIT = 0.35             # 页面加载后、抽链接前的稳定等待秒数（等 DOM 渲染完成）
CONTEXT_LOST_RETRY_DELAY = 0.8      # 页面上下文丢失后，重试翻页前的等待秒数
JS_CONTEXT_LOST_DELAY = 0.6         # JS 执行遇上下文丢失时的重试间隔
JS_OTHER_ERROR_DELAY = 0.3          # JS 执行遇其他错误时的重试间隔
JS_DEFAULT_RETRIES = 2              # 单次 JS 调用的默认重试次数
# ---- 浏览器参数 ----
PORT_RANGE = (9222, 9322)               # Chrome 调试端口随机区间，避开占用并支持多任务并发
BROWSER_START_RETRIES = 3               # 启动失败时换随机端口重试的次数
DISABLE_IMAGES = True                   # 禁加载图片：列表页提速省流量（只要链接不要图）
USE_INCOGNITO = True                    # 无痕模式：避免缓存/登录态干扰采集结果
# ---- 落盘相关命名 ----
LINK_INDEX_FILENAME = "links_index.csv"     # 分类→分类URL 的两列索引（域名由 URL 反推，记录采过哪些分类）
LEGACY_LINK_INDEX_FILENAME = "links_index.json"  # 旧版索引：仅用于首次迁移读取，新版本不再写入
RECOVERY_MARK = "recovery"                  # 原文件读取/写入失败时另存副本的命名标记
DOMAIN_FILE_EXT = ".csv"                    # 域名链接文件扩展名（三列：分类、商品链接、url 的 md5）
LEGACY_DOMAIN_FILE_EXT = ".json"            # 旧版域名链接文件：仅用于首次迁移读取，新版本不再写入
CSV_ENCODING = "utf-8-sig"                  # 统一 CSV 编码：UTF-8 带 BOM，Excel / WPS 打开中文不乱码


@dataclass
class CategoryItem:  # 单个待采分类：标题（作 JSON 分组键）+ 列表页 URL
    title: str
    url: str


@dataclass
class CollectConfig:  # 一次采集任务的全部输入，供 CollectorRunner 消费
    categories: List[CategoryItem] = field(default_factory=list)
    output_dir: str = ""
    max_pages: int = 0                    # 0 表示不限制页数
    xpath: str = ""                       # 非空则走 XPath 定位模式，否则走 HTML 正则模式
    proxy: Optional[str] = PROXY_SERVER
    port_range: tuple = PORT_RANGE
    disable_images: bool = DISABLE_IMAGES
    browser_path: Optional[str] = None        # 浏览器可执行文件路径；留空自动探测 Chrome/Edge

    def summary(self) -> str:  # 生成任务参数概览，采集开始时打印到日志便于核对
        lines = [
            f"共 {len(self.categories)} 个分类",
            f"最大页数: {self.max_pages if self.max_pages else '不限制'}",
        ]
        if self.xpath:
            lines.append(f"XPath: {self.xpath}")
        lines.append(f"保存目录: {self.output_dir}")
        lines.append("采集模式: 纯分页")
        return "\n".join(lines)
