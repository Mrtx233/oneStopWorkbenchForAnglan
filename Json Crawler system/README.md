# 商品采集与尺码梯度定价工作台

本目录提供可独立启动的桌面工作台，依次完成分类链接采集、商品 JSON 采集、十字段 CSV 整理、十字段表切分、WooCommerce CSV 导出及 WP 图片下载。阶段四不生成 Shopify 中间表；尺码梯度定价以采集划线价为参考，在候选窗口（默认 ±25%）内选取库价，WP 导出完成后自动检查文件内的 SKU。

## 启动与环境

在仓库根目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 "Json Crawler system/main.py"
```

也可进入本目录执行 `python3 main.py`。Windows 可将 `python3` 换成 `python`。建议 Python 3.10 或更新版本；主界面需要 Tkinter，采集需要 Chromium 系浏览器与 DrissionPage。定价只使用现有依赖，不需要额外求解器。

两个采集阶段的浏览器固定使用 `http://127.0.0.1:7897`。界面没有代理输入框，历史 `last_proxy` 和任务设置中的自定义代理不参与浏览器配置。采集前确认本地代理在该端口运行。商品币种识别和汇率查询另有 urllib HTTP 请求，不由浏览器代理参数统一控制。

浏览器可执行文件按「环境变量 `CHROME_PATH` → Chrome 常见安装路径 → Edge 常见安装路径」自动探测，命中即用；全部落空才报「找不到浏览器可执行文件路径」。如需手动指定，可在 `user_settings.json` 里加 `"browser_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"`（或设为环境变量 `CHROME_PATH`），该值优先于自动探测。

## 项目目录与执行顺序

顶部选择一个具体店铺的项目根目录，它是 `Json`、`CSV`、`原价`、`价格匹配` 的共同父目录。

默认目录按以下优先级确定：`ANGLAN_PROJECT_DIR` 环境变量 → 上次仍存在的项目 → 仓库内 `ANG_OUTPUT_XLSX` → 仓库根。默认值不会自动搜索或合并历史店铺。

| 阶段 | 输入 | 输出 |
|---|---|---|
| 01 链接采集 | 分类文本、页数、可选 XPath | `Json/<域名>.csv`、`Json/links_index.csv` |
| 02 商品采集 | `Json` 第一层域名 CSV；无同名 CSV 时兼容 JSON | `Json/Data Analysis/<域名>.json` |
| 03 数据分析 | `Json/Data Analysis/*.json` | `CSV/<域名>_style.csv`、同名商品 JSON |
| 03.1 切分 | `CSV/*_style.csv` | 均分 N 份或按 title 拆分，各含 CSV 与对应 JSON |
| 04 价格与导出 | 默认 `CSV`，或指定 CSV / 目录 | 合并表、所选价格表、WooCommerce CSV、未使用库价 CSV |
| 04.1 图片下载 | 阶段 04 的 `wp-*.csv` | `<WP 文件名>-images/`、`*-imageOK-时间戳.csv`、失败清单 |

从头处理按 01 → 02 → 03 →（03.1 切分，可选）→ 04 →（04.1 图片下载，可选）分别执行。图片下载页可扫描原价/价格匹配目录中的最新 WP 导出，也可手动选择；需要填写目标 WordPress 地址。下载成功的图片链接会替换为该站点当年当月的 uploads 路径，失败链接保留原值并生成失败 URL / SKU 清单。界面每次只运行当前阶段，单独启动某阶段不会自动补跑前置阶段。

## 阶段一：链接采集

分类文本每行一条，可用逗号分隔标题与 URL：

```text
Dresses, https://example.com/collections/dresses
Tops, https://example.com/collections/tops
```

页数留空表示不限，XPath 留空使用普通链接提取。每个域名链接文件和分类索引均为 UTF-8 BOM CSV：域名文件列头为 `title,url,md5`（第三列是纯 url 的 md5，跨分类唯一），索引列头为 `title,url`。域名文件记录商品链接，索引记录分类列表页。

续采会合并已有链接；只有对应 CSV 不存在时才读取同名历史 JSON。索引和 `.recovery-` 文件不作为商品采集输入。恢复副本用于保护读取失败或无法正常写入的文件，出现时查看日志。

链接中的非标准横杠统一归一，中文和表情路径按 UTF-8 百分号编码，合法 `%XX` 不重复编码。阶段二按去除 query / fragment 的商品 JSON URL 去重，同一商品重复归类时优先使用首次遇到的分类。

## 阶段二：商品采集与清洗

商品汇总保存九个基本字段：

```text
url, title, fennei, body_html, price, compare_at_price,
images, option_counts, options
```

可选字段为 `currency`、`size_mode`、`description_image_mode`、`description_table_mode` 和 `md5`。阶段二使用 `common/product_model.py` 的 `Product` / `OptionDimension` 组织数据；`Product` 构建时清洗和校验，`to_dict()` 转成可写入 JSON 的字典，续采通过 `Product.from_dict()` 读取历史记录。阶段三则以字典和函数处理汇总数据。

### 标题与分类

- `title` 保留各语言文字、数字、文字组合音标和空格；删除表情、标点及其他特殊符号，整理首尾和连续空白。例如 `🐰 Baby™ Dress!` → `Baby Dress`。删除标点不会自动插入空格，如 `T-Shirt` → `TShirt`。
- `fennei` 将 ASCII 连字符 `-` 替换为空格，并整理空白，如 `new-born--baby` → `new born baby`。
- 规则覆盖新采解析、最终保存及已有汇总续跑修复；仅修改标题和分类无需重新请求商品。

### 尺码与其他选项

Color / Colour / Colors / Colours / 颜色 归一为 `Color`，Size / Sizes / 尺寸 归一为 `Size`，忽略英文大小写和首尾空白。

“使用标准尺码”默认关闭，并记住上次选择。无论该开关状态，Size 取值都会先识别并转换 `US/UK/AUS/FR/ITY` 国家尺码前缀（如 `US 0` → `XXS`、`US 10` → `XL`、`FR 40` → `L`），同时去除括号注释，以及字母尺码后面的数字或数字区间后缀（如 `XS(US 4)`、`XS(US 4/UK 8/EU 36)` → `XS`，`L/10`、`L/10-12`、`XL/14-16` → `L`、`L`、`XL`），再执行对应尺码模式处理。开启时所有商品先清洗、保序去重，再直接按 Size 数量套用标准序列，不依据标题或原值是否能识别来决定是否替换。

例如 `M、L、One Size` → `S、M、L`，`L /UK 10、XL /UK 12` → `S、M`，`38、39、40` → `S、M、L`。

数量对应表：

| 数量 | 输出尺码 |
|---:|---|
| 1 | One Size |
| 2 | S、M |
| 3 | S、M、L |
| 4 | S、M、L、XL |
| 5 | S、M、L、XL、2XL |
| 6 | XS、S、M、L、XL、2XL |
| 7 | XS、S、M、L、XL、2XL、3XL |
| 8 | XS、S、M、L、XL、2XL、3XL、4XL |
| 9 | XXS、XS、S、M、L、XL、2XL、3XL、4XL |

其他数量（0 或超过 9）保留基础清洗后的原值。鞋裤及包含 Pants / Shorts / Trouser 等字样的套装也按数量替换，不再按标题绕过开关。

关闭标准尺码同样只跳过整组处理，括号和数字后缀清理、国家尺码转换仍生效。`size_mode` 记录 `standard` 或 `original`；开启时可从已有明细直接转换，关闭后恢复原值则需补采，成功保存后才替换旧记录。

基础转换阶段，非 US 国家码冲突时优先匹配加宽尺码，例如 `UK 20`、`AUS 20`、`FR 48`、`ITY 52` 均转为 `1X`；US 通过 `W` 区分，例如 `US 16` → `4XL`、`US 16W` → `1X`。开启标准尺码时，所有商品随后按清洗、去重后的数量替换（例如 `UK 20、UK 22` 清洗成 `1X、2X` 后，数量为 2，输出 `S、M`）。关闭标准尺码时则保留基础转换结果。未命中的值不在基础清洗中强制换算，`EU` 不是独立支持的前缀。颜色和尺码会删除反斜杠与 `&`，重复取值保序合并并同步数量。

开启标准尺码续跑阶段二时，已有 Size 明细会直接按现有数量修正并标记为 `standard`，包括旧模式为 `original` 的记录，无需重新请求网站；缺失明细时仍需补采。历史汇总若已被数量规则替换，原始尺码无法从汇总恢复；切换回原值模式时需重新采集。

### 描述与图片

默认删除描述图片和表格。开启保留图片后，仅保留 `<img>` 的 `src`，不把 `data-src` 转成 `src`。开启保留表格后保留清洗后的表格；其他清洗不受影响。描述仍清理链接、视频和脚本等容器、资源与元信息标签、HTML 注释、普通标签属性以及 BMP 以外字符。

产地与 SKU 按三条规则清理：元素内文本命中 `sku`（前后不接字母）时移除该元素；`made in` 仅在元素文本以它开头（允许前置符号与空白）且整段就是这一句时移除该元素；不在任何标签内的裸文本按行命中后删除整行。以 `Made in` 开头的整句也会从句中摘除，同段其余句子保留。清洗后没有有效内容的标签及因此变空的祖先标签会移除；保留表格时仍保留空的 `td` / `th` 单元格，以免改变表格列结构。标签之间及标签内部由排版产生的换行、Tab 和缩进空白会压缩或删除，保留有效文字与标签层级。

旧记录开启保留图片或表格时需要补采，因为旧清洗已删除的内容无法从汇总恢复；从保留切换为删除时可直接重新清洗已有记录。已处于保留模式的旧图片也会清除 `src` 以外的属性。运行中改变任一开关下一轮生效。

跳图按完整相册编号：`2,3` 跳过第二、三张，`-1,-2` 跳过最后两张，留空不跳。颜色图与普通相册分开整理。

### 价格、币种与续采

两价互补：任一售价 / 划线价缺失、为空或为零时使用另一有效价格；都缺失时保存空字符串。阶段二识别币种并尝试换算 USD，失败会保留原数值和原币种。汇率表成功获取后会写入本机缓存，24 小时内的后续运行直接复用；缓存过期或损坏时才重新请求，网络失败也会限制重试频率。

商品采集结果按批次原子保存整个域名汇总：每次成功解析一个商品后检查待保存批次，达到 10 条或距上次成功保存已满 15 秒时刷盘；15 秒不是独立定时器，网络请求等长时间未返回时不会自动触发。文件完成、停止或异常收尾时会尝试强制保存未满一批的成功结果；若刷盘失败会记录保存异常，未提交的内容不会计入已提交结果。这样减少重复全量写盘，同时保留断点续采能力；完整记录跳过，缺明细或模式变化的记录补采。历史记录格式不合法或同一规范 URL 对应内容冲突时拒绝覆盖。

## 阶段三：十字段整理

默认使用 Color、Size。“其他维度参与组合”默认关闭，开启时加入有实际取值的其他维度；`ships from` 等排除项仍不参与。汇总 JSON 中 `Type` 维度若是列表且有多个取值，阶段三将其输出为 `Style`；单值 `Type` 不会被重命名。当前“其他维度”勾选侧会把 `Type` 当作 `Style` 选择，因此单值 `Type` 也不会加入组合；不要将此规则理解为所有 `Type` 都会导出为 `Style`。

Color 上限按颜色拆成多行，各行保留完整尺码。“有颜色维度时只保留颜色图”控制是否不追加相册补图；按颜色拆成多行时会自动去掉相册补图。无 Color 维度的商品可在界面设置相册补图数量，默认 4 张，填 0 表示不补；带 Color 维度时仍最多补 4 张主图。预览只生成前 200 个组合，其余通过维度取值数量计算准确总数，避免全量展开占用内存。

按颜色拆出的每行是独立商品：每个颜色分组根据来源商品标识和本组颜色生成新的 md5，同一分组重复导出保持稳定；未发生颜色拆分的商品沿用原 md5。阶段三同时保存 `CSV/<域名>_style.json`，其中各商品的 md5、颜色明细、数量和图片与 CSV 对应，供后续同步切分使用。

| 列 | 内容 |
|---|---|
| `title` / `name` | 分类 / 商品标题 |
| `price1` / `price2` | 售价 / 划线价 |
| `styles1` | 组合属性、内嵌两价与款式图 |
| `styles2` / `styles3` | 阶段三保留的空占位列；WP 导出不读取，可省略 |
| `src_links` | 颜色图及相册补图；无 Color 商品的补图数可在界面设置 |
| `link-href` | 商品链接 |
| `details` | 阶段二保存的描述 HTML |
| `md5` | 独立商品标识：未拆色时沿用来源 md5，拆色时为每个颜色分组派生新 md5 |

款式使用公共编解码器转义和解析。超过样式串长度上限的款式会跳过并写失败清单。

阶段三不联网换汇，也不会拦截所有非 USD 或未知币种记录；价格数值会直接进入不含币种列的十字段表。使用前应核对阶段二的 `currency`，不要把外币数字直接当成美元定价。当前平台导出最多保留三个选项维度，四维及以上组合的后续维度会丢失，应在阶段三控制所选维度数。

### 阶段 3.1：十字段表切分

阶段三导出完成后，可在“数据分析”页底部的「十字段表切分」区直接对当前项目 `CSV/` 下的 `*_style.csv` 做二次切分，无需启动另一程序。两种模式：

- **均分 N 份**：按 `title`（分类）分组、按所选价格列排序后，按独立商品 md5 轮询均分成 N 份，各份商品数量尽量均匀。来自同一原商品的不同颜色分组拥有不同 md5，可以进入不同文件。价格列可选 `price1` / `price2`，留空则组内保持原顺序。
- **按 title 各自成文件**：每个不同的 `title` 值独立写成一个文件。

两种模式都会**同步切分对应 JSON**：按每份 CSV 的 md5 集合，优先从配套的 `CSV/<域名>_style.json` 筛出对应商品对象，写成与 CSV 对应的 `.json`。历史 CSV 没有配套 JSON 时，兼容读取 `Json/Data Analysis/<域名>.json`。若找不到对应 JSON 则跳过 JSON 同步（不影响 CSV 切分）；存在 JSON 但缺少对应 md5 时会报告失败，提示重新运行阶段三。已有的拆色表需重新运行阶段三，以生成独立商品 md5 和配套 JSON。

取消「覆盖同名输出」后，任一同名 CSV 或 JSON 已存在时，两者一起使用 `_新`、`_新2`、`_新3` 等后缀，直到两个目标名都未被占用。JSON 沿用本次 CSV 的名称；写入时发现目标又被占用会报错，保留已有文件。

切分产物目录结构（均分模式为例）：

```text
CSV/
├── <域名>_style_1/
│   ├── csv/<域名>_style_1.csv
│   └── json/<域名>_style_1.json
├── <域名>_style_2/
│   ├── csv/<域名>_style_2.csv
│   └── json/<域名>_style_2.json
└── ...
```

按 title 模式则为 `<域名>_style_按title拆分/<分类名>/`，其下同样分 `csv/` 与 `json/`。

## 阶段四：尺码梯度定价

输入留空读取当前项目 `CSV`，也可选择单个 `.csv` 或目录。目录递归收集子目录里的 `.csv`（兼容切分后「每份一个文件夹，内分 csv/」的嵌套结构），排除 `原价/`、`价格匹配/`、`json/` 子目录、合并表本身、规范名表、隐藏文件和 `~$` 锁文件，其余表按列名合并；不要混入无关表格。

### 定价规则

匹配参考价以采集划线价（原价）为准，缺失时用采集售价。价格库含 **232 档，范围 8.99～599**。两个参数：同款总价差上限（默认 30%）、候选窗口（默认 `0.75～1.25`，即候选库价 = 参考价 × [下界, 上界]）。库价全局去重不重复。

1. 采集售价低于 8.99 的商品不参与匹配：按采集售价从低到高排序，循环取 8.99～19.99 库价依次赋值，同一商品全部变体（含颜色）同价，赋的新价作为商品原价（Regular price）、不设划线折扣（Sale price 空），状态为 `低价`。
2. 候选库价 = 落在 `[参考价 × 下界, 参考价 × 上界]` 且**未被其他商品使用**的档位（整数分），全局唯一不重复。
3. 有尺码商品按尺码递增取窗口内未用库价（梯度）；售价取最低档、划线价取最高档。同颜色不同尺码可不同价，不同颜色同尺码共价；档位不足时前几个尺码各占一档、剩余尺码复用最后一个档位。
4. 无尺码商品取窗口内最小的未用库价（单一价，不递增），状态为 `原价`。
5. 窗口内没有未用库价时保持原价：`Regular price` = 参考价、`Sale price` 空，状态为 `未匹配`。

例如商品划线价 40、尺码 S/M/L，窗口 `[0.75, 1.25]` 即候选 `[30, 50]`，取窗口内未用的最小库价起按尺码递增（如 `31.52 / 31.95 / 31.99`），售价取最低、划线价取最高。

库价全局去重后，同一库价不会被两个不同商品使用；候选窗口内库价被抢占完时，后续商品保持原价不匹配。参考价低于 8.99 的商品已由低价预处理拦截；高于最高库价的窗口候选为空，同样保持原价。价差限制只约束本商品新售价之间的比例。

匹配表保留 `采集售价、采集划线价、采集款式、定价参考价、定价状态`。每个商品行独立处理，拆色行不按原链接合并。无有效参考价或不可解析款式保留输入行，状态为 `未匹配`。

### 两个流程开关

| 原价表 | 价格匹配 | 本轮执行 |
|---|---|---|
| 开 | 开 | 合并、原价修正、梯度匹配、两套平台导出 |
| 开 | 关 | 合并、原价修正、原价平台导出 |
| 关 | 开 | 合并、梯度匹配、匹配平台导出 |
| 关 | 关 | 合并、直接转换平台格式 |

原价修正只将低于售价的划线价抬至售价，包含内嵌变体价。使用历史匹配表运行原价流程时，当前实现不会从保存的采集字段恢复原价；要导出采集原价，请选择原始十字段输入。

### 平台价格与核对

WooCommerce 有有效折扣（划线价高于售价）时输出 `Sale price` 和 `Regular price`；没有折扣时只输出 `Regular price`、`Sale price` 留空。variable 父商品不带价，价格在子变体上。

SKU 由商品 md5 确定性派生（子变体 5-5-5、父级 SKU+8位数字），跨次导出稳定不变。调整参数需要重跑阶段四，重复导入时应自行核对商品身份。

每个 WooCommerce CSV 导出后会单独检查该文件内的非空 SKU 是否重复，以及 `variation` 的 `Parent` 是否能在同文件的 `variable` / `simple` 商品 SKU 中找到。日志输出统计和有限条数的明细；检查只报告，不自动修复，也不会因发现重复或孤立变体而判定导出失败。此检查不跨文件，也不查询线上店铺。

匹配时只输出定价日志、匹配表、未使用库价 CSV 及 WooCommerce 文件；不再生成商品定价明细 CSV、价格库覆盖明细 CSV、定价汇总 JSON。历史报告不会自动删除。

日志记录逐商品状态和原因、匹配数量及使用库价数量。

## 输出位置

目录输入为项目 `CSV`、两个流程均开启时：

```text
<项目>/
├── Json/
│   ├── <域名>.csv
│   ├── links_index.csv
│   └── Data Analysis/<域名>.json
├── CSV/
│   ├── <域名>_style.csv
│   ├── <项目名>_合并.csv
│   └── （切分产物，可选）<域名>_style_N/ 或 <域名>_style_按title拆分/
├── 原价/
│   ├── <项目名>_合并_原价.csv
│   └── wp-<项目名>_合并_原价.csv
└── 价格匹配/
    ├── <项目名>_合并_价格匹配.csv
    ├── wp-<项目名>_合并_价格匹配.csv
    └── <项目名>_合并_未匹配到的价格.csv
```

单文件按输入文件 stem 命名，不额外保存合并副本。名为 `CSV` 的输入目录以父目录为输出基准，其他目录以自身为基准；合并表始终写到输入目录内（即 `CSV/` 下）。未勾选流程不新建对应目录；两个都关闭时平台文件与合并表同目录。阶段三/四的十字段表、合并表、原价表、匹配表均为 CSV（utf-8-sig 带 BOM），可直接用 Excel / WPS 打开。

## 状态、设置与维护

| 状态 | worker 退出码 | 含义 |
|---|---:|---|
| success | 0 | 阶段正常完成 |
| partial | 3 | 有有效结果，但存在失败项 |
| failed | 1 | 异常或没有可用结果 |
| stopped | 2 | 请求停止 |

失败清单位于 `Json/_stage01_failures.txt`、`Json/Data Analysis/_stage02_failures.txt`、`CSV/_stage03_failures.txt`。完整成功会清理相应旧清单。成功不代表全部库价覆盖或所有商品完成匹配，查看日志及匹配表状态。

关键数据使用同目录临时文件加原子替换；整个流程不是事务，后续失败时前面产物可能已经更新。运行中修改参数下一轮生效；停止等待当前处理与保存结束，强制结束可能丢失尚未保存的内容。

`user_settings.json` 会记住项目、标准尺码、描述图片、描述表格、其他维度开关及浏览器路径。价差和流程开关不自动记忆。它位于本目录；不要将多个工作台实例同时指向同一项目写入。

代码入口为 `main.py → ui → controller.py → worker.py`。阶段入口统一为 `run(settings, stop, emit)`，数字前缀文件通过 `common/step_loader.py` 加载。公共模块负责模型、文本 / 描述清洗、选项取值、原子写入和款式编码。

## 代码文件作用详解

以下按目录列出全部 Python 源文件的职责。数字前缀文件（`00_`/`10_`/…/`99_`）只能通过 `common/step_loader.py` 按路径加载，阶段内通过 `alias_step` 把它们挂到 `config` / `logger` 等旧模块名上再 `import`。

### 顶层入口与调度

- `main.py` — 启动入口。创建 Tk 根窗口、实例化 `CrawlerApp` 并进入 `mainloop()`；被 import 时不弹窗，方便单测与复用。
- `controller.py` — GUI 无关的串行调度器。后台线程按顺序为每个阶段起 `worker.py` 子进程，转发其事件行到 `queue.Queue`；提供软停止（touch 停止文件）与硬停止（terminate → kill）三步强退；用临时目录存放各阶段停止文件，任务结束整体清理。
- `worker.py` — 子进程入口（`python -u worker.py <阶段号> <停止文件>`）。从 stdin 读一行 settings，按 `STAGES` 映射加载对应阶段目录的 `99_pipeline_entry.run()`，起监听线程轮询停止文件；把结果映射成退出码（0 成功 / 3 部分失败 / 2 停止 / 1 失败）。
- `url_utils.py` — 兼容转发层：把 `normalize_url_dashes` / `normalize_request_url` 转给 `app.url_utils`，供阶段脚本用裸名 `from url_utils import ...` 调用。改逻辑请改 `app/` 那份。
- `user_settings.json` — 本机设置（非代码文件）：记住上次项目目录与各功能开关。

### app/（跨进程共享的常量与工具，不依赖 Tk / pandas）

- `constants.py` — 跨进程共享常量：阶段号→名称映射（`NAMES` / `PAGE_NAMES`）、状态文案（`STATUS`）、事件行前缀（`PREFIX = '@@CRAWLER_EVENT@@'`）、固定代理（`PROXY_SERVER = 'http://127.0.0.1:7897'`）。
- `project_paths.py` — 推断默认项目目录，优先级：`ANGLAN_PROJECT_DIR` 环境变量 → 上次仍存在的项目 → 仓库 `ANG_OUTPUT_XLSX` → 仓库根。
- `url_utils.py` — URL 处理：`normalize_url_dashes`（各种 Unicode 破折号及其百分号编码统一成 `-`）、`normalize_request_url`（路径/查询/锚点按 UTF-8 百分号编码，保留已有转义与分隔符）。
- `user_settings.py` — 读写本机 `user_settings.json`（`load_user_settings` / `save_user_settings`），读失败回退空字典、写失败静默忽略，绝不让 GUI 因配置文件崩溃。
- `__init__.py` — 包说明（app 包不依赖 tkinter，阶段子进程可安全 import）。

### common/（公共模型、清洗、编解码与原子写）

- `product_model.py` — 核心数据对象。`Product` / `OptionDimension` dataclass；定义九个必需字段 + 五个可选字段；`__post_init__` 完成全部幂等清洗；提供 `to_dict` / `from_dict`（含 strict 校验）、`apply_policy`（keep→remove 降级重洗）、颜色/尺码维度名归一（`canonical_option_name` 等）。
- `option_values.py` — 颜色/尺码取值清洗：删除 `\` 与 `&`、保序去重；尺码基础清洗 `_clean_size_value`（去括号/数字区间后缀、`L/10`→`L`、国家尺码转换 US/UK/AUS/FR/ITY、加宽码 1X~4X、One Size 统一）；`clean_product_option_values` 兼容汇总与原始 Shopify 两种结构。
- `description_html.py` — 商品描述 HTML 清洗：手写 `HTMLParser` 删除链接/视频/脚本/表格等容器与 SKU、`Made in` 句，剥离标签属性、丢弃非 BMP 字符；`keep_images` 仅保留 `<img src>`、`keep_tables` 保留表格结构与 colspan/rowspan。
- `product_text.py` — 标题与分类名清洗：`clean_product_title`（去表情/标点/符号，保留各语言文字数字）、`clean_category_name`（连字符换空格）。
- `price_fallback.py` — 售价/划线价互补：`fill_missing_prices`，任一缺失/为零时用另一价格填，都缺失则空串。
- `styles_codec.py` — 款式串对称编解码：`escape`/`unescape`（转义 `\&#@`）、`split`（只切未转义分隔符）、`encode_segment`/`decode_segment`（`值&名值$售价$划线价@图` 段）、`partition_image`（拆出图片）。
- `atomic_io.py` — `replace_file`：同目录临时文件 + `os.replace` 原子替换，防止中途崩溃留下半截 JSON/CSV。
- `step_loader.py` — 按路径加载数字前缀模块：`load_step`（合成模块名带父目录，避免各阶段同名文件互顶）、`alias_step`（把前缀文件挂到 `config` 等旧名）。
- `browser.py` — 统一浏览器工厂 `create_browser`（随机端口 + 无痕 + 固定代理 + 重试），`find_browser_path` 按 CHROME_PATH→Chrome→Edge 探测；DrissionPage 缺失时降级不崩。
- `stop.py` — `stopped(stop)` 停止信号判空检查。
- `__init__.py` — 空包标记。

### ui/（Tkinter 界面，四个 mixin 拼成 CrawlerApp）

- `app.py` — `CrawlerApp` 类体（多继承 `CrawlerBuild` / `CrawlerPages` / `CrawlerDialogs` / `CrawlerRuntime`，本身为空）。
- `build.py` — 界面骨架与 ttk 样式：窗口配置、`Controller` 实例、全部 StringVar/BooleanVar 绑定、`_styles`（圆角按钮/复选/单选/输入框/进度条等）、写监听触发 `on_setting_changed`。
- `pages.py` — 五个页面布局：链接采集、商品采集、数据分析（含切分区与预览表格）、价格与导出、图片下载；底部状态栏/进度条/停止按钮。
- `dialogs.py` — 路径选择与参数快照：`settings()` 做全量校验并拍成 dict（含跳图位置解析、定价规则校验）、`persist_settings`、目录浏览、`refresh_files`/`refresh_wp_csv`。
- `runtime.py` — 任务启停与日志：`start`（校验→提交 controller→冻结 UI）、`stop`、`poll`（100ms 事件泵，唯一改控件处）、日志窗口管理与 `close`（三态关闭保护）。
- `glass.py` — 控件素材：`rounded_image`（纯 Python 生成 PNG 圆角素材）、`indicator_image`（复选/单选图标）、`NavItem`（侧栏导航项）。
- `theme.py` — 石墨灰 + 暖金色板与字体候选（`choose_font`）。
- `__init__.py` — 空包标记。

### stages/01_link_collector（分类链接采集）

- `00_config.py` — 常量与 `CollectConfig`：重试/延迟参数、端口区间、索引与域名文件命名、CSV 编码。
- `20_browser.py` — 阶段内浏览器封装：`create_browser`（委托 common.browser）、`run_js_with_retry`（带重试与停止检查）、`get_outer_html`、`evaluate_xpath`。
- `30_collector.py` — 采集核心：`parse_categories`、`build_page_url`（Shopify `?page=N` 分页）、`extract_product_links`（HTML 正则三路交叉）、`extract_links_by_xpath`、`CollectorRunner`（逐分类分页 + 两级去重 + 首页重试）。
- `40_file_utils.py` — 落盘：读旧域名 CSV/JSON、`update_link_index`、`save_results`（按域名分桶合并写三列 CSV）、损坏文件另存 recovery。
- `80_logger.py` — 阶段内日志出口（写真实 stdout，经 worker 回传）。
- `99_pipeline_entry.py` — 阶段入口 `run`：解析分类、建 `CollectorRunner`、跑采集、写失败清单、上报产物。

### stages/02_product_scraper（商品 JSON 采集与九字段清洗）

- `00_config.py` — 常量：商品间隔 `DELAY`、瞬时失败重试等待、`JSON_SUBDIR`/`JSON_ANALYSIS_DIR`、CSV 编码。
- `20_browser.py` — `create_browser` 封装（委托 common.browser）。
- `25_file_utils.py` — 文件读写：`read_targets`（读三列 CSV 或旧版 JSON 得 (分类,URL,md5)）、`save_json`（原子写汇总 JSON，统一走 Product 对象）。
- `30_network.py` — 网络与 URL：`to_shopify_json_url`、`group_targets_by_json_url`、`fetch_json`（监听网络包取 JSON，30 秒超时）、币种识别 `extract_currency`/`detect_shop_currency_http`、汇率 `fetch_exchange_rates`/`prices_to_usd`（24 小时缓存）。
- `40_product_analysis.py` — 商品解析：`parse_product_object`（原始 Shopify 商品 → 九字段）、尺码标准序列 `standardize_size_values`、跳图 `skip_image_indexes`/`filter_gallery_images`、补采判定 `needs_*_refresh`。
- `50_scraper_runner.py` — 采集运行器 `ScraperRunner`：逐域名读目标、去重、断点续传、抓包解析、失败重试一次、批量原子刷盘（10 条或 15 秒）。
- `80_logger.py` — 阶段内日志（`log_exc`）。
- `99_pipeline_entry.py` — 阶段入口：收集输入文件、实例化运行器、写失败清单、上报产物。

### stages/03_data_analysis（十字段 CSV 整理）

- `00_config.py` — 常量：`SKIP_OPTIONS`（如 ships from 不参与组合）、`MAX_STYLES_LENGTH`（32000）、`CSV_FIELDS`（十一列表头契约）。
- `10_option_split.py` — 拆行：颜色按上限切块 `chunk_values`/`option_limit_sets`、`restrict_product`（颜色块裁图）、`color_product_md5`（拆色派生 md5）、`parse_product_rows`（逐块解析）。
- `30_product_parser.py` — 组合器：用 `exec` 把 `31`/`32` 两段拼进同一命名空间，对外仍是 `product_parser`。
- `31_parser_part1.py` — 解析前半段：`is_analysis_product`、颜色/尺码别名、`analysis_options`、`build_option_combos`（笛卡尔积）、`format_image_url`（插入 600x600 尺寸后缀）、`_style_escape`。
- `32_parser_part2.py` — 解析后半段：`_selected_product_combinations`、`parse_product`（拼十字段行）、`style_image_urls`、`_build_src_links`、`InvalidProductError`/`StylesTooLongError`。
- `40_analyzer.py` — 组织层：`iter_products`（校验九字段记录）、`domain_groups`、`stat_options`、`expand_cartesian`（预览）、`build_ten_field_rows`（批量导出）。
- `99_pipeline_entry.py` — 阶段入口：登记模块、统计/预览/导出分支、逐域名写 CSV + 配套 JSON、写失败清单。

### stages/03_1_split（十字段表切分，stage 5）

- `00_config.py` — 常量：分组列/价格列/默认份数、`MD5_COL`、两种模式常量、目录后缀。
- `20_split.py` — 切分算法：`split_by_title`（按 title 分组、价格排序、按 md5 商品块轮询均分 N 份）、`split_by_title_each`（每个 title 一个文件）、`split_json_by_md5`（同步切分配套 JSON）、编码检测与文件名清洗。
- `99_pipeline_entry.py` — 阶段入口：收集 `*_style.csv`、按模式分发、同步切分 JSON、上报产物。

### stages/04_price_export（尺码梯度定价与 WooCommerce 导出）

- `00_pricing_config.py` — 定价配置：232 档价格库、`DEFAULT_SPREAD_PERCENT`（30）、候选窗口（0.75~1.25）、`PriceRules` 与 `resolve_rules` 校验。
- `10_merge.py` — 合并：`OutputPaths`、递归收集十字段表（排除原价/价格匹配/json、切分产物优先）、`_ensure_link_md5` 补算 md5、写合并表。
- `11_fix_prices.py` — 原价修正：修正倒挂（D<C→D=C）、styles1 内嵌价修正（p2<p1→p2=p1），写原价表。
- `12_match_prices.py` — 梯度定价核心：低价预处理、窗口内全局去重的库价匹配、尺码递增梯度取价、`variant_size`/`size_sort_key`/`spread_prices`、逐商品日志。
- `13_unused_prices.py` — 未使用库价：库价与已用价做差集，导出 CSV。
- `14_export_wp.py` — WP 导出：SKU 派生（父级 SKU+8 位、子变体 5-5-5）、变体展开、WP 商品树聚合、`check_wp_skus`（SKU 查重与孤立变体检查）。
- `80_styles_utils.py` — styles1 工具：`parse_styles`（解码）、`fix_styles`（内嵌价修正）、`to_float`。
- `90_pipeline.py` — 编排：按流程开关拼步骤表、`begin` 步骤边界停止检查、串起 merge→fix→match→unused→export。
- `99_pipeline_entry.py` — 阶段接口：解析价差/窗口参数、调 `pipeline.run`、上报产物目录。

### stages/04_1_image_downloader（WP 图片下载，stage 6）

- `20_downloader.py` — 下载核心：`split_urls`/`split_image_values`、`_image_data`（PIL 校验并统一转 JPEG）、`run_download`（并发下载、去重、原子写新 CSV、失败清单）。
- `99_pipeline_entry.py` — 阶段入口：校验 CSV 与 WP 地址、并发数、调 `run_download`。

### tests/

- `test_stage_04_1_image_downloader.py` — 图片下载器单测：URL 过滤去重、成功改写/失败保留、failed_skus 清单（用 mock 替代 requests 与 PIL）。

阶段目录与职责：

- `stages/01_link_collector`：分类链接采集。
- `stages/02_product_scraper`：商品 JSON 采集与九字段清洗。
- `stages/03_data_analysis`：十字段 CSV 整理。
- `stages/03_1_split`：十字段表切分（均分 N 份 / 按 title 拆分，含 JSON 同步），运行时以 stage 5 拉起，UI 入口在阶段三页面。
- `stages/04_price_export`：尺码梯度定价与 WooCommerce 导出。
- `stages/04_1_image_downloader`：独立下载 WP CSV 的 Images 列并生成替换链接后的新 CSV（worker stage 6；不依赖独立图片下载器脚本）。

阶段四关键文件为：

- `00_pricing_config.py`：232 档价格库、候选窗口与价差参数。
- `10_merge.py`：递归收集十字段表并合并（兼容切分嵌套目录）。
- `12_match_prices.py`：窗口内全局去重的梯度定价与逐商品日志。
- `13_unused_prices.py`：未使用库价 CSV。
- `14_export_wp.py`：style 表直接转 WooCommerce（含变体展开、SKU 派生、WP 商品树聚合）。
- `90_pipeline.py`：按流程开关编排。

阶段三提示没有汇总 JSON 时，应核对项目根及阶段二产物；已有 CSV 可以直接运行阶段四。CSV 文件被 Excel / WPS 占用导致替换失败时，关闭文件后重试。界面完成和离线样本检查不替代源站采集及平台实际导入验证。
