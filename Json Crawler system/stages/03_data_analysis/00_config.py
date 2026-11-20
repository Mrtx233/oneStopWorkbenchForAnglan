# ======================== 配置层 ========================
# 本文件由 99_pipeline_entry 用 alias_step 登记成模块名 config，阶段内其余文件统一 import config 取常量。
# 整列剔除的选项关键字：选项名包含其中任一项即当作非款式维度，不进组合也不写进 styles。
# "ships from" 是发货地而非颜色/尺码，混进款式串会凭空放大行数并干扰阶段 04 的尺码匹配。
SKIP_OPTIONS = ["ships from"]
# styles1 单元格长度上限：Excel 单元格硬上限为 32767 字符，这里取 32000 留出余量。
# 颜色/款式太多导致拼出的 styles1 超限时，product_parser 抛 StylesTooLongError，
# 由上层跳过整个商品，避免写出被截断、后续阶段无法反解的坏行。
MAX_STYLES_LENGTH = 32000
# 十字段列名：既是本阶段写 CSV 的表头，也是阶段 04（合并/改价/导出 WooCommerce CSV）
# 按列名取值的契约，改名必须两侧同步。
CSV_FIELDS = [
    "title", "name", "price1", "price2",
    "styles1", "styles2", "styles3",
    "src_links", "link-href", "details", "md5",
]
