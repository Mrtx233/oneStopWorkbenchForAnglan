"""商品数据对象：阶段二采集结果的结构化定义、校验与规范化。

一个 Product 实例对应汇总 JSON 里的一行（一个商品）。字段与落盘契约保持一致：
- 九个必需字段：url / title / fennei / body_html / price / compare_at_price /
  images / option_counts / options
- 五个可选字段：currency / size_mode / description_image_mode / description_table_mode / md5

序列化规则与旧版字典完全兼容：可选字段为空时不写键，其余键顺序不变，
因此阶段三读取汇总 JSON 时无需改动。

清洗只有一份实现：构造（__post_init__）即完成全部幂等清洗，
构造出来的对象即是清洗后的状态，调用方无需（也不应）再跑一遍规则。
外部「保留描述图片 / 保留表格」策略由 apply_policy() 施加（只做 keep → remove 的降级重洗）。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from common.description_html import clean_body_html
from common.option_values import clean_product_option_values
from common.price_fallback import fill_missing_prices
from common.product_text import clean_category_name, clean_product_title
from url_utils import normalize_request_url

# 汇总行的九个必需字段（顺序即落盘顺序）
REQUIRED_FIELDS = (
    "url", "title", "fennei", "body_html", "price", "compare_at_price",
    "images", "option_counts", "options",
)
# 价格允许缺失，落盘前由 fill_missing_prices 互补
CORE_REQUIRED_FIELDS = tuple(name for name in REQUIRED_FIELDS
                             if name not in ("price", "compare_at_price"))
OPTIONAL_FIELDS = ("currency", "size_mode", "description_image_mode", "description_table_mode", "md5")
ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

SIZE_MODES = ("standard", "original")
DESCRIPTION_IMAGE_MODES = ("keep", "remove")
DESCRIPTION_TABLE_MODES = ("keep", "remove")

COLOR_NAMES = {"color", "colour", "colors", "colours"}
SIZE_NAMES = {"size", "sizes"}


class ProductDataError(ValueError):
    """商品记录结构不合法，无法构造商品对象。"""


def is_color_name(name) -> bool:
    # 颜色维度判定：忽略大小写与首尾空白，兼容 colour/colors/colours
    return str(name or "").strip().casefold() in COLOR_NAMES


def is_size_name(name) -> bool:
    return str(name or "").strip().casefold() in SIZE_NAMES


def canonical_option_name(name) -> str:
    # 维度名归一：数量与明细必须共用同一名称，否则会出现“有数量没明细”
    text = str(name or "").strip()
    if is_color_name(text):
        return "Color"
    if is_size_name(text):
        return "Size"
    return text


def _as_text(value) -> str:
    # 统一转字符串：None 视为空串，数字价格等原样转文本，避免 JSON 里出现字符串/数字混存
    return "" if value is None else str(value)


def _as_price(value) -> str:
    return _as_text(value).strip()


@dataclass
class OptionDimension:
    """一个选项维度：Color 是「颜色名→图片URL」映射，其余维度是取值列表。"""

    name: str
    values: Union[List, Dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        self.name = str(self.name or "").strip()
        if isinstance(self.values, dict):
            # 颜色图映射：保序、只留字符串键，空图片地址保留（下游允许无图颜色）
            self.values = {_as_text(key): _as_text(image) for key, image in self.values.items()}
        elif isinstance(self.values, str):
            # 脏数据把单个取值写成字符串时按单元素列表处理，避免被逐字符拆开
            self.values = [self.values]
        else:
            self.values = [_as_text(value) for value in (self.values or [])]

    @property
    def count(self) -> int:
        return len(self.values)

    def to_dict(self) -> Dict[str, Union[List, Dict[str, str]]]:
        return {self.name: self.values if isinstance(self.values, dict) else list(self.values)}

    @classmethod
    def from_entry(cls, entry) -> "OptionDimension":
        # 单个 options 条目：正常是 {"Color": {...}} 这种单键字典
        if not isinstance(entry, dict) or not entry:
            raise ProductDataError(f"选项条目必须是单键字典：{entry!r}")
        name = next(iter(entry))
        return cls(name=name, values=entry[name])


def dimensions_from_options(options) -> List[OptionDimension]:
    # 把 options 列表还原成维度对象；旧数据里一个条目带多个键时按顺序拆开
    dimensions: List[OptionDimension] = []
    for entry in options or []:
        if not isinstance(entry, dict):
            continue
        for name, values in entry.items():
            dimensions.append(OptionDimension(name=name, values=values))
    return dimensions


@dataclass
class Product:
    """一个商品的完整采集结果。"""

    url: str
    title: str
    fennei: str
    body_html: str
    price: str
    compare_at_price: str
    images: List[str] = field(default_factory=list)
    options: List[OptionDimension] = field(default_factory=list)
    option_counts: Dict[str, int] = field(default_factory=dict)
    currency: str = ""
    size_mode: str = ""
    description_image_mode: str = "remove"
    description_table_mode: str = "remove"
    md5: str = ""

    def __post_init__(self):
        # ---- ① 类型地基：先把字段收成「字符串 / 维度对象 / 整数表」，后续规则只面对干净类型 ----
        self.url = _as_text(self.url)
        self.title = clean_product_title(self.title)
        self.fennei = clean_category_name(self.fennei)
        self.body_html = _as_text(self.body_html)
        self.price = _as_price(self.price)
        self.compare_at_price = _as_price(self.compare_at_price)
        self.images = [_as_text(src) for src in (self.images or [])]
        self.options = [
            dimension if isinstance(dimension, OptionDimension) else OptionDimension.from_entry(dimension)
            for dimension in (self.options or [])
        ]
        self.option_counts = self._normalize_counts(self.option_counts)
        self.currency = _as_text(self.currency).strip().upper()
        self.size_mode = _as_text(self.size_mode).strip()
        self.description_image_mode = _as_text(self.description_image_mode).strip() or "remove"
        self.description_table_mode = _as_text(self.description_table_mode).strip() or "remove"
        self.md5 = _as_text(self.md5).strip()

        # ---- ② 幂等清洗：选项取值 → 描述 HTML → 两价互补 → 链接编码 ----
        # 这一步是「清洗唯一实现」的主体：任何入口构造出来的对象都已是清洗后的状态，
        # 调用方不需要（也不允许）再跑一遍同样的规则。
        cleaned = clean_product_option_values(self.to_dict())
        self.options = dimensions_from_options(cleaned.get("options") or [])
        self.option_counts = self._normalize_counts(cleaned.get("option_counts") or {})
        self.images = [src for src in self.images if src]
        self.body_html = clean_body_html(
            cleaned.get("body_html"),
            keep_images=self.description_image_mode == "keep",
            keep_tables=self.description_table_mode == "keep",
        )
        self.price, self.compare_at_price = fill_missing_prices(
            cleaned.get("price"), cleaned.get("compare_at_price"))
        self.url = normalize_request_url(cleaned.get("url"))

        # ---- ③ 校验：清洗后再判定，避免把「清洗后为空」当成合法输入 ----
        if not self.url:
            raise ProductDataError("商品 url 不能为空")
        if self.size_mode and self.size_mode not in SIZE_MODES:
            raise ProductDataError(f"未知尺码模式：{self.size_mode}")
        if self.description_image_mode not in DESCRIPTION_IMAGE_MODES:
            raise ProductDataError(f"未知描述图片模式：{self.description_image_mode}")
        if self.description_table_mode not in DESCRIPTION_TABLE_MODES:
            raise ProductDataError(f"未知描述表格模式：{self.description_table_mode}")
        if not self.option_counts:
            self.option_counts = self.derived_option_counts()

    @staticmethod
    def _normalize_counts(counts) -> Dict[str, int]:
        # 数量表统一成 {维度名: 正整数}；无法转成整数的脏值直接丢弃
        normalized: Dict[str, int] = {}
        if not isinstance(counts, dict):
            return normalized
        for name, count in counts.items():
            try:
                normalized[str(name)] = int(count)
            except (TypeError, ValueError):
                continue
        return normalized

    def derived_option_counts(self) -> Dict[str, int]:
        # 由选项明细反推数量，供缺 option_counts 的旧数据兜底
        return {dimension.name: dimension.count for dimension in self.options}

    # ---- 序列化 ----
    def to_dict(self) -> Dict[str, object]:
        # 与旧版字典逐键一致：可选字段为空时不写键
        row: Dict[str, object] = {
            "url": self.url,
            "title": self.title,
            "fennei": self.fennei,
            "body_html": self.body_html,
            "price": self.price,
            "compare_at_price": self.compare_at_price,
            "images": list(self.images),
            "option_counts": dict(self.option_counts),
            "options": [dimension.to_dict() for dimension in self.options],
        }
        if self.currency:
            row["currency"] = self.currency
        if self.size_mode:
            row["size_mode"] = self.size_mode
        row["description_image_mode"] = self.description_image_mode
        if self.description_table_mode != "remove":
            row["description_table_mode"] = self.description_table_mode
        if self.md5:
            row["md5"] = self.md5
        return row

    @classmethod
    def from_dict(cls, data, strict: bool = False, *, keep_images: Optional[bool] = None,
                  keep_tables: Optional[bool] = None) -> "Product":
        """从汇总 JSON 的一行还原商品对象。

        strict=True 时执行与续采校验等价的检查：必需键齐全、无未知键、
        url 为非空字符串、币种为字符串、两个模式字段取值合法。
        外部策略只允许 keep → remove；在构造前选定模式，描述只清洗一次。
        """
        if not isinstance(data, dict):
            raise ProductDataError(f"商品记录必须是字典：{type(data).__name__}")
        if strict:
            missing = [name for name in CORE_REQUIRED_FIELDS if name not in data]
            if missing:
                raise ProductDataError(f"缺少必需字段：{', '.join(missing)}")
            unknown = [name for name in data if name not in ALLOWED_FIELDS]
            if unknown:
                raise ProductDataError(f"存在未知字段：{', '.join(unknown)}")
            if not isinstance(data.get("url"), str) or not data["url"]:
                raise ProductDataError("url 必须是非空字符串")
            if not isinstance(data.get("currency", ""), str):
                raise ProductDataError("currency 必须是字符串")
            if data.get("size_mode", "standard") not in SIZE_MODES:
                raise ProductDataError(f"未知尺码模式：{data.get('size_mode')}")
            if data.get("description_image_mode", "remove") not in DESCRIPTION_IMAGE_MODES:
                raise ProductDataError(
                    f"未知描述图片模式：{data.get('description_image_mode')}")
            if data.get("description_table_mode", "remove") not in DESCRIPTION_TABLE_MODES:
                raise ProductDataError(
                    f"未知描述表格模式：{data.get('description_table_mode')}")
        image_mode = _as_text(data.get("description_image_mode", "remove")).strip() or "remove"
        table_mode = _as_text(data.get("description_table_mode", "remove")).strip() or "remove"
        # 仅对合法的 keep 模式施加降级，非法模式仍由构造校验报错。
        if keep_images is not None and not keep_images and image_mode == "keep":
            image_mode = "remove"
        if keep_tables is not None and not keep_tables and table_mode == "keep":
            table_mode = "remove"
        return cls(
            url=data.get("url", ""),
            title=data.get("title", ""),
            fennei=data.get("fennei", ""),
            body_html=data.get("body_html", ""),
            price=data.get("price", ""),
            compare_at_price=data.get("compare_at_price", ""),
            images=data.get("images") or [],
            options=dimensions_from_options(data.get("options")),
            option_counts=data.get("option_counts") or {},
            currency=data.get("currency", ""),
            size_mode=data.get("size_mode", ""),
            description_image_mode=image_mode,
            description_table_mode=table_mode,
            md5=data.get("md5", ""),
        )

    # ---- 规范化 ----
    def apply_policy(self, keep_images: Optional[bool] = None,
                     keep_tables: Optional[bool] = None) -> "Product":
        """施加外部「保留描述图片 / 保留表格」设置；只做 keep → remove 的降级，不可反向恢复。"""
        data = None
        if keep_images is not None:
            keep = bool(keep_images)
            if keep != (self.description_image_mode == "keep") and not keep:
                # keep → remove：按删除规则重洗描述，并把模式标记改回 remove
                if data is None:
                    data = self.to_dict()
                data["description_image_mode"] = "remove"
        if keep_tables is not None:
            keep = bool(keep_tables)
            if keep != (self.description_table_mode == "keep") and not keep:
                # keep → remove：按删除规则重洗描述，并把模式标记改回 remove
                if data is None:
                    data = self.to_dict()
                data["description_table_mode"] = "remove"
        if data is None:
            return self
        # 新对象按更新后的模式完成一次清洗，保持原对象不变。
        return Product.from_dict(data)
