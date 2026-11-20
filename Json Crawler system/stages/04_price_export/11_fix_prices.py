"""第一步：修正商品及 styles1 内的划线价，保存原价表。"""
from common.atomic_io import replace_file
from pathlib import Path

from common.step_loader import load_step

# styles1 内嵌价的解析/修正依赖 80 号工具，按路径加载（数字前缀文件不能直接 import）
_styles = load_step(Path(__file__).with_name('80_styles_utils.py'))
to_float = _styles.to_float
fix_styles = _styles.fix_styles


def run(data, raw_path, stop=None):
    # 深拷贝，避免就地改动污染上游合并表
    df = data.copy(deep=True)
    print('#' * 110)
    print('第一步：原价修正（D < C → D = C；内嵌价 p2 < p1 → p2 = p1）')
    print('#' * 110)

    cd_fixed = 0
    seg_fixed = 0
    for row_idx, row in df.iterrows():
        if stop is not None and stop.is_set():
            print('原价修正已停止，保存已处理行', flush=True)
            break
        c = to_float(row.get('price1'))   # C 列：售价
        d = to_float(row.get('price2'))   # D 列：原价（划线价）

        # 倒挂判定：两价都有且原价低于售价时，把原价抬到等于售价，避免出现"原价<售价"
        if c is not None and d is not None and d < c:
            df.at[row_idx, 'price2'] = c
            cd_fixed += 1

        # styles1 每个变体内嵌的 p1/p2 同样可能倒挂，交 fix_styles 逐段修正，返回修正条数 n
        fixed_raw, n = fix_styles(row.get('styles1'))
        if n:
            df.at[row_idx, 'styles1'] = fixed_raw
            seg_fixed += n

    print(f"\nC/D 修正行数: {cd_fixed}    styles1 内嵌修正变体数: {seg_fixed}")
    # 落盘为"原价"表：修正后但未匹配库价的中间产物（utf-8-sig 带 BOM，Excel/WPS 打开不乱码）
    replace_file(raw_path, lambda path: df.to_csv(path, index=False, encoding='utf-8-sig'), ".csv")
    print(f"已保存: {raw_path}")
    return df
