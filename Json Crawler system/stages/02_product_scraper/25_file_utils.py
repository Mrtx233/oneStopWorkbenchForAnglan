# ======================== 文件读写层 ========================
# 登记为旧模块名 file_utils：从阶段 01 的域名链接 CSV（兼容旧版 JSON）读目标、把汇总 JSON 原子写盘。
import csv
import json
from common.atomic_io import replace_file
from common.product_model import Product
from url_utils import normalize_request_url
import config

LINK_HEADER = ("title", "url")  # 阶段 01 域名链接 CSV 的两列表头


def read_targets(filepath):
    # 读阶段 01 的域名链接文件，展开成 (分类标题, 商品URL, md5) 列表；按扩展名分派 CSV / 旧版 JSON
    return (read_targets_from_json(filepath) if str(filepath).lower().endswith(".json")
            else read_targets_from_csv(filepath))


def read_targets_from_csv(filepath):
    # 三列 CSV：第一列分类标题，第二列商品链接，第三列 url 的 md5；表头行按内容识别，其余行全部当作目标
    targets = []
    with open(filepath, "r", encoding=config.CSV_ENCODING, newline="") as f:
        first_row = True
        for row in csv.reader(f):
            if not row or not any(str(cell).strip() for cell in row):
                continue
            if first_row:  # 表头只可能在第一条非空行；不是表头就照常当数据
                first_row = False
                if len(row) >= 2 and row[0].strip().lower() == LINK_HEADER[0] \
                        and row[1].strip().lower() == LINK_HEADER[1]:
                    continue
            if len(row) < 2:  # 缺列无法定位商品，跳过该行
                continue
            url = normalize_request_url(row[1])  # 统一编码，兼容含表情/中文的旧链接
            if url:
                md5 = str(row[2]).strip() if len(row) >= 3 else ""  # 第三列为空或缺失则置空
                targets.append((str(row[0]).strip(), url, md5))
    return targets


def read_targets_from_json(filepath):
    # 兼容旧版域名 JSON：{分类: [链接], domain/generated_at/link_count: 元数据}；无 md5，统一置空
    targets = []
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    for key, value in raw.items():
        if key in ("domain", "generated_at", "link_count"):  # 这些是文件元数据字段，不是商品分组
            continue
        if not isinstance(value, list):  # 只有数组值才是某分类下的商品链接列表
            continue
        title = str(key).strip()  # 键名即分类标题，作为后续 fennei 字段来源
        for link in value:
            url = normalize_request_url(link)  # 兼容已有含表情的链接，统一编码供请求与去重
            if url:
                targets.append((title, url, ""))
    return targets


def save_json(data, output_path, *, keep_description_images=None, keep_description_tables=None):
    # 在最终写盘入口统一走商品对象：清洗描述与选项、补齐两价、归一链接，返回新的字典副本。
    # 复制记录，避免写入失败时改变调用方的内存基线。
    # 运行器复用已校验的 Product；外部字典仍在这里构造并校验。
    # 字典的描述策略在构造前选定，避免构造后又按另一模式重洗。
    def prepared_record(record):
        if isinstance(record, Product):
            return record.apply_policy(keep_description_images, keep_description_tables).to_dict()
        if not isinstance(record, dict):
            return record
        return Product.from_dict(
            record, keep_images=keep_description_images,
            keep_tables=keep_description_tables,
        ).to_dict()

    payload = [prepared_record(record) for record in data] if isinstance(data, list) else prepared_record(data)
    # 原子写盘：统一走 replace_file（临时文件 + os.replace），防止写盘中途崩溃损坏上一次产物。
    def _write(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)  # 保留中文原文，缩进便于人工核对

    replace_file(output_path, _write, ".json")
