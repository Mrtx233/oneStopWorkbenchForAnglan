# ======================== 阶段 02 配置 ========================
# 本模块被 99 入口登记为旧模块名 config，供 scraper_runner 等按 `import config` 使用。
DELAY = 0.5                # 相邻商品之间的采集间隔（秒），给店铺留冷却时间、降低被风控概率
TRANSIENT_RETRY_DELAY = 10 # 瞬时失败（非 200 或空数据）时重试一次前的等待秒数，避开偶发网络抖动
JSON_SUBDIR = "Json"       # 项目内的 JSON 根目录名（阶段 01 产物与阶段 02 产物都放这里）
JSON_ANALYSIS_DIR = "Data Analysis"  # 阶段 02 汇总 JSON 的输出子目录名
CSV_ENCODING = "utf-8-sig"               # 读取阶段 01 域名 CSV 的编码：UTF-8 带 BOM
