"""商品解析层。由 31/32 两段组合进本模块，对外仍是 product_parser。"""
from pathlib import Path

# 31/32 是同一个原始文件因过大而切出的两段代码片段：两段里的变量互相引用
# （part2 用 part1 的 re / format_combo_value / _style_escape 等，part1 用 part2 的 InvalidProductError），
# 所以它们都不能单独 import，必须 exec 进同一个命名空间 _ns 才认得彼此。
_HERE = Path(__file__).resolve().parent
# 手工给命名空间补 __name__/__file__，让片段里的相对定位与调试输出表现得像真模块
_ns = {"__name__": "product_parser", "__file__": str(_HERE / "30_product_parser.py")}
for _name in ("31_parser_part1.py", "32_parser_part2.py"):
    _path = _HERE / _name
    # 顺序不能换：先 part1 定义基础函数，part2 才能在其之上拼出 parse_product
    exec(compile(_path.read_text(encoding="utf-8"), str(_path), "exec"), _ns)
# 合并后的命名空间搬进本模块 globals，对外（option_split / analyzer）就是完整的 product_parser
for _key, _value in _ns.items():
    if _key not in {"__builtins__"}:
        globals()[_key] = _value
# 清掉这些加载用临时名，避免它们污染 dir(product_parser) 和后续属性判断
del _HERE, _ns, _name, _path, _key, _value
