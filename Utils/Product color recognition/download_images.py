# -*- coding: utf-8 -*-
"""
下载 json 中所有商品的图片（通用脚本，适用于任意网站抓取的同类 json）。

用法一（命令行参数）:
    python download_images.py [json路径] [输出目录]

用法二（交互式输入）:
    python download_images.py
    运行后提示输入 json 路径；输出目录可直接回车使用默认值。

默认:
    json路径  = 必须通过参数或交互输入指定
    输出目录  = json 文件所在目录下的 images/ 子目录

目录/命名规则:
    - 每个商品一个文件夹，文件夹名 = 商品的 md5
    - 文件夹内图片按 json 中 images 数组的原始顺序排序命名(000.jpg/001.png ...)
    - 统一转为 jpg 或 png：png/gif 保留为 .png，其余(jpg/webp/avif等)统一转 .jpg
    - 损坏图片和非图片响应重试后记录到 failed.txt，不作为成功图片保存
    - 单色商品(以 options 中实际颜色数量为准)不下载图片，但会把第一张
      图片的 URL 填入 options 中 Color 选项的空值并写回 json

其它特性:
    - 多线程并发下载，失败自动重试
    - Referer 按图片 URL 的域名自动生成，适配任意网站
    - 增量：已存在的文件跳过
    - 记录下载清单 manifest.csv 和失败列表 failed.txt
- 下载结束后为每个商品图片文件夹生成一张带序号的五列拼图，保存至 _contact_sheets/<md5>.jpg
"""
import os
import argparse
import json
import csv
import io
import concurrent.futures
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from product_data import atomic_json, atomic_output, clean_pasted_path, find_color_map, safe_product_folder

# ---------------- 配置 ----------------
MAX_WORKERS = 8          # 并发线程数
RETRY = 3                # 失败重试次数
TIMEOUT = 30             # 单张超时(秒)
CONTACT_SHEET_COLUMNS = 5
CONTACT_CELL_SIZE = (220, 180)
CONTACT_GAP = 2
CONTACT_LABEL_SIZE = (70, 50)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")


def make_headers(url):
    """根据图片 URL 动态生成请求头，Referer 自动取该图片所在网站的域名。"""
    p = urlparse(url)
    referer = f"{p.scheme}://{p.netloc}/"
    return {
        "User-Agent": USER_AGENT,
        "Referer": referer,
    }


def _contact_sheet_font():
    try:
        return ImageFont.truetype("arial.ttf", 24)
    except OSError:
        try:
            return ImageFont.load_default(size=24)
        except TypeError:
            return ImageFont.load_default()


def create_contact_sheets(images_dir):
    """为 images 目录下每个商品文件夹生成五列编号拼图。

    输出到 images/_contact_sheets/<md5>.jpg，不修改或移动原图。
    """
    if not os.path.isdir(images_dir):
        return None, 0, 0

    contact_dir = os.path.join(images_dir, "_contact_sheets")
    os.makedirs(contact_dir, exist_ok=True)
    folders = sorted(
        (name for name in os.listdir(images_dir)
         if name.casefold() != "_contact_sheets"
         and os.path.isdir(os.path.join(images_dir, name))),
        key=str.casefold,
    )
    font = _contact_sheet_font()
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    generated = 0
    unreadable = 0
    total = len(folders)

    for folder_index, folder_name in enumerate(folders, start=1):
        if folder_index == 1 or folder_index % 10 == 0 or folder_index == total:
            print(f"\r拼图进度: {folder_index}/{total}", end="", flush=True)

        folder_path = os.path.join(images_dir, folder_name)
        image_names = []
        for filename in os.listdir(folder_path):
            stem, extension = os.path.splitext(filename)
            if extension.lower() in IMAGE_SUFFIXES and stem.isdecimal():
                image_names.append(filename)
        image_names.sort(key=lambda name: (int(os.path.splitext(name)[0]), name.casefold()))
        if not image_names:
            continue

        cell_width, cell_height = CONTACT_CELL_SIZE
        rows = (len(image_names) + CONTACT_SHEET_COLUMNS - 1) // CONTACT_SHEET_COLUMNS
        sheet_width = CONTACT_SHEET_COLUMNS * cell_width + (CONTACT_SHEET_COLUMNS + 1) * CONTACT_GAP
        sheet_height = rows * cell_height + (rows + 1) * CONTACT_GAP
        sheet = Image.new("RGB", (sheet_width, sheet_height), (238, 238, 238))
        draw = ImageDraw.Draw(sheet)

        for cell_index, filename in enumerate(image_names):
            stem = os.path.splitext(filename)[0]
            image_number = int(stem)
            column = cell_index % CONTACT_SHEET_COLUMNS
            row = cell_index // CONTACT_SHEET_COLUMNS
            x = CONTACT_GAP + column * (cell_width + CONTACT_GAP)
            y = CONTACT_GAP + row * (cell_height + CONTACT_GAP)
            image_path = os.path.join(folder_path, filename)
            try:
                with Image.open(image_path) as source:
                    thumbnail = source.convert("RGB")
                    thumbnail.thumbnail(CONTACT_CELL_SIZE, resampling)
                tile = Image.new("RGB", CONTACT_CELL_SIZE, (255, 255, 255))
                tile_x = (cell_width - thumbnail.width) // 2
                tile_y = (cell_height - thumbnail.height) // 2
                tile.paste(thumbnail, (tile_x, tile_y))
                sheet.paste(tile, (x, y))
            except Exception:
                unreadable += 1
                draw.rectangle((x, y, x + cell_width - 1, y + cell_height - 1),
                               fill=(255, 245, 245))
                draw.text((x + 8, y + 65), "LOAD ERROR", fill=(160, 0, 0), font=font)

            label_width, label_height = CONTACT_LABEL_SIZE
            draw.rectangle((x, y, x + label_width - 1, y + label_height - 1), fill=(0, 0, 0))
            label = str(image_number)
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
            text_x = x + max(2, (label_width - text_width) // 2) - bbox[0]
            text_y = y + max(2, (label_height - text_height) // 2) - bbox[1]
            draw.text((text_x, text_y), label, fill=(255, 220, 0), font=font)

        output_path = os.path.join(contact_dir, f"{folder_name}.jpg")
        sheet.save(output_path, format="JPEG", quality=90, optimize=True)
        generated += 1

    if total:
        print()
    return contact_dir, generated, unreadable

def _product_colors(item):
    if not isinstance(item, dict):
        raise ValueError("商品数据不是对象")
    colors, error = find_color_map(item.get("options", []))
    if error == "没有 Color 维度":
        return {}
    if error:
        raise ValueError(error)
    return colors


def is_single_color(item):
    """以实际 Color 映射为准，避免缺失或过期的 option_counts 导致误填。"""
    return len(_product_colors(item)) <= 1


def fill_single_color_urls(data):
    """把单色商品 options 中 Color 选项的空值替换为第一张图片 URL，返回修改数量。

    兼容 Color/Colour/颜色等维度名；只处理确有一个颜色的商品。
    就地修改 data，不返回新对象。
    """
    changed = 0
    for item in data:
        colors = _product_colors(item)
        if len(colors) != 1:
            continue
        imgs = item.get("images", [])
        if not isinstance(imgs, list) or not imgs or not isinstance(imgs[0], str) or not imgs[0].strip():
            continue
        first = imgs[0]
        for name in colors:
            if colors[name] in ("", None):
                colors[name] = first
                changed += 1
    return changed


def build_tasks(data, images_root=None):
    """遍历 JSON，生成 (url, 保存路径, 商品url, 标题, md5) 任务列表。跳过单色商品。"""
    tasks = []
    skipped = 0
    if not isinstance(data, list):
        raise ValueError("商品 JSON 顶层必须是数组")
    root = Path(images_root or ".").resolve()
    folders = {}
    destinations = set()
    for product_index, item in enumerate(data, start=1):
        try:
            colors = _product_colors(item)
        except ValueError as exc:
            raise ValueError(f"第 {product_index} 个商品：{exc}") from exc
        imgs = item.get("images", [])
        if not isinstance(imgs, list) or any(url is not None and not isinstance(url, str) for url in imgs):
            raise ValueError(f"第 {product_index} 个商品：images 必须是图片 URL 数组")
        if len(colors) <= 1:
            skipped += 1
            continue
        md5 = str(item.get("md5") or "").strip()
        folder = safe_product_folder(root, md5)
        if folder is None:
            raise ValueError(f"第 {product_index} 个商品：md5 为空或图片文件夹路径无效")
        folder_key = os.path.normcase(str(folder))
        if folder_key in folders and folders[folder_key] != imgs:
            raise ValueError(f"第 {product_index} 个商品：重复 md5 {md5} 对应不同图片，无法安全编号")
        folders[folder_key] = imgs
        for i, url in enumerate(imgs):
            if not url or not url.strip():
                continue
            # 目标扩展名：png/gif -> .png，其余 -> .jpg
            # 先按 URL 后缀粗判（去掉 ?v= 查询参数），实际转换在下载后按真实格式处理
            ext = ".jpg"
            path = urlparse(url).path.lower()
            if path.endswith(".png") or path.endswith(".gif"):
                ext = ".png"
            fname = f"{i:03d}{ext}"
            dst = os.path.join(md5, fname)
            key = os.path.normcase(dst)
            if key in destinations:
                continue
            destinations.add(key)
            tasks.append((url, dst, item.get("url", ""), item.get("title", ""), md5))
    return tasks, skipped


def _detect_ext(img_bytes, url):
    """根据实际图片格式返回 .png 或 .jpg。"""
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            fmt = im.format
        if fmt == "PNG":
            return ".png"
        if fmt == "GIF":
            return ".png"
        # JPEG / WEBP / 其它 统一转 jpg
        return ".jpg"
    except Exception:
        # 无法识别，退回 URL 后缀粗判（去掉 ?v= 查询参数）
        path = urlparse(url).path.lower()
        if path.endswith(".png") or path.endswith(".gif"):
            return ".png"
        return ".jpg"


def download(url, dst, retry=RETRY):
    """下载并转换单张图片，返回 (成功与否, 最终文件名, 错误信息)。"""
    error = "未进行下载"
    for attempt in range(retry):
        try:
            req = Request(url, headers=make_headers(url))
            with urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()

            if not raw:
                raise ValueError("empty body")

            # 根据真实格式决定最终扩展名
            ext = _detect_ext(raw, url)
            final_path = Path(dst).with_suffix(ext)
            with Image.open(io.BytesIO(raw)) as source:
                im = ImageOps.exif_transpose(source).convert("RGBA")
                if ext == ".jpg":
                    background = Image.new("RGBA", im.size, "white")
                    background.alpha_composite(im)
                    im = background.convert("RGB")
                with atomic_output(final_path, "wb") as handle:
                    im.save(handle, "PNG" if ext == ".png" else "JPEG", quality=95)
            # Avoid ambiguous duplicate indices after a source format changes.
            for other in final_path.parent.glob(final_path.stem + ".*"):
                if other != final_path and other.suffix.lower() in IMAGE_SUFFIXES:
                    other.unlink()
            return True, final_path.name, ""
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
    return False, "", error


def _existing_image(prefix):
    candidates = [p for p in Path(prefix).parent.glob(Path(prefix).name + ".*")
                  if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    if len(candidates) != 1:
        return None
    try:
        with Image.open(candidates[0]) as image:
            image.load()
        return candidates[0]
    except (OSError, ValueError, SyntaxError):
        return None


def _process(json_path, out_dir):
    with open(json_path, encoding="utf-8-sig") as f:
        data = json.load(f)
    # Validate the complete input before changing even one single-color value.
    tasks, skipped = build_tasks(data, out_dir)

    # 单色商品：把第一张图片 URL 填入 Color 选项的空值，并写回 json
    filled = fill_single_color_urls(data)
    if filled:
        atomic_json(json_path, data)
        print(f"已为 {filled} 个单色颜色选项填入第一张图片 URL，并写回 {json_path}")

    print(f"共 {len(data)} 个商品（跳过单色或无颜色 {skipped} 个），多色商品 {len(data) - skipped} 个，"
          f"需下载图片 {len(tasks)} 张，输出目录: {out_dir}")

    manifest = os.path.join(out_dir, "manifest.csv")
    failed_file = os.path.join(out_dir, "failed.txt")

    # 增量：跳过已存在的文件（同 md5 下按序号找到已存在文件）
    # 必须能够完整解码且序号唯一；半截文件或重复后缀会重新下载。
    todo = []
    successes = {}
    for url, dst, prod, title, md5 in tasks:
        prefix = os.path.join(out_dir, os.path.splitext(dst)[0])
        found = _existing_image(prefix)
        if found is not None:
            successes[dst] = found.name
            continue
        todo.append((url, dst, prod, title, md5))
    print(f"其中 {len(tasks) - len(todo)} 张已存在，本次需下载 {len(todo)} 张")

    failed = []
    if todo:
        done = 0
        total = len(todo)

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(download, u, os.path.join(out_dir, d)): (u, d, p, t, m)
                    for u, d, p, t, m in todo}
            for fut in concurrent.futures.as_completed(futs):
                u, d, p, t, m = futs[fut]
                ok, fname, err = fut.result()
                done += 1
                if ok:
                    successes[d] = fname
                else:
                    failed.append((u, d, err))
                if done % 100 == 0 or done == total:
                    print(f"进度: {done}/{total}")

        print(f"完成。本次成功 {len(todo) - len(failed)} 张, 失败 {len(failed)} 张。")
    else:
        print("没有需要下载的图片，将使用已有图片生成拼图。")

    # Include verified cached files, and clear stale failures after a successful rerun.
    with atomic_output(manifest, encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["product_url", "title", "image_url", "local_path"])
        writer.writerows([p, t, u, os.path.join(m, successes[d])]
                         for u, d, p, t, m in tasks if d in successes)
    with atomic_output(failed_file) as f:
        for u, d, err in failed:
            f.write(f"{u}\t{d}\t{err}\n")
    print(f"清单: {manifest}")
    if failed:
        print(f"失败列表: {failed_file}")

    contact_dir, contact_count, unreadable_count = create_contact_sheets(out_dir)
    if contact_dir is None:
        print("未找到图片输出目录，跳过拼图。")
    else:
        print(f"拼图完成：{contact_count} 张，目录: {contact_dir}")
        if unreadable_count:
            print(f"其中 {unreadable_count} 张原图读取失败，拼图内已标记。")
    return 1 if failed or unreadable_count else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="下载商品多色图片，补齐单色链接并生成编号拼图")
    parser.add_argument("json_file", nargs="?", help="商品 JSON 文件")
    parser.add_argument("output_dir", nargs="?", help="图片目录，默认 JSON 同目录下的 images")
    args = parser.parse_args(argv)
    try:
        json_value = args.json_file
        output_value = args.output_dir
        if json_value is None:
            json_value = clean_pasted_path(input("请粘贴商品 JSON 文件路径："))
            if not json_value:
                print("未提供 JSON 文件路径，已退出。")
                return 2
            output_value = clean_pasted_path(input("请输入图片输出目录（回车使用 JSON 同目录下的 images）："))
        json_path = Path(clean_pasted_path(json_value)).expanduser().resolve()
        out_dir = (Path(clean_pasted_path(output_value)).expanduser().resolve()
                   if output_value else json_path.parent / "images")
        if not json_path.is_file():
            parser.error(f"JSON 文件不存在：{json_path}")
        if out_dir.exists() and not out_dir.is_dir():
            parser.error(f"图片输出路径不是文件夹：{out_dir}")
        return _process(json_path, out_dir)
    except (EOFError, KeyboardInterrupt):
        print("输入或下载已取消；已完整保存的图片可在下次运行时复用。")
        return 130
    except (OSError, ValueError, SyntaxError) as exc:
        print(f"处理失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# 你是商品数据处理助手。我会给你两个路径，请按下面的流程完成“图片颜色识别 → 回填 JSON 的 Color 字段”。
#
# ## 输入
# 1. 商品 JSON：<粘贴 JSON 路径>
# 2. 图片目录：<粘贴 images 路径>
#
# ## 已知约定（不要质疑，直接按此理解）
# - 图片目录下每个子文件夹名 = 该商品的 md5（对应 JSON 里的 md5 字段）
# - 子文件夹内文件按 JSON 中 images 数组的原始顺序命名：000.jpg / 001.png / 002.jpg …
#   （即 003.jpg ↔ images[3]，扩展名可能是 jpg 或 png）
# - 多色商品的 options 里 Color 的 value 是空字符串，需要我来填；单色商品可能已填好，不要改动
#
# ## 执行步骤
#
# ### 第 1 步：体检，先出结论再动手
# - 统计商品总数、有 Color 选项的商品数、Color 值全空/部分空/已填满的商品数
# - 核对：每个待处理商品的 md5 文件夹是否存在、文件夹内图片数是否等于 images 数组长度
# - 若某商品图片数 < 颜色数，或文件夹缺失，**不要猜**，单独列为“数据异常”清单
#
# ### 第 2 步：只处理“多色且 Color 为空”的商品
# 单色商品（Color 只有 1 个键）和无 Color 选项的商品，原样保留，一个字段都不改。
#
# ### 第 3 步：逐商品生成编号拼图
# - 每个商品把它的所有图片拼成一张图：每行 5 张，每张 300×400，图片左上角画黑底黄字的序号（从 0 开始，与文件名序号一致）
# - 拼图只用于识别，不要覆盖原图
#
# ### 第 4 步：颜色识别
# - 每张拼图调用一次视觉识别，提问里**必须列出该商品的全部颜色选项名**，并明确“只能从这些颜色里选”
# - 要求输出格式：`0=颜色名 1=颜色名 …`，数量必须与图片数一致
# - 允许同一颜色对应多张图（同款多角度）
# - 遇到两种颜色极其接近（如 Light Blue / Blue、Sage Green / Green、Dusty Pink / Pink），按色相深浅和图案区分，并在结果里标注“低置信”
#
# ### 第 5 步：回填 JSON
# 对每个商品：
# - 每个颜色取**序号最小的那张命中图**作为该颜色的主图，写进 `options[0].Color[颜色名]`
# - 写入的值是**原 images 数组里对应的 URL**（不是本地路径），保持原样带 `?v=` 参数
# - 该 URL 从 `images` 数组中**删除**（避免颜色和 images 重复）
# - 剩余图片（同色多角度、细节图、街拍图）**按原顺序保留**在 `images` 里
# - 其他字段（url / title / fennei / body_html / price / compare_at_price / option_counts / currency / size_mode / description_image_mode / description_table_mode / md5）**一律不得改动**
# - 颜色名必须与 options 中原始键名**完全一致**（含大小写、空格、`{'name': 'color', 'value': 'Red'}` 这种脏键名要原样保留）
#
# ### 第 6 步：校验（必须全部通过才交付）
# - 每个商品：颜色链接数 + images 剩余数 = 原 images 总数（图片守恒，不能丢也不能重复）
# - 同一 URL 不能同时出现在 Color 和 images 里
# - 颜色值为空的项 = 0（除第 7 步列出的例外）
# - 所有写入的 URL 都必须来自该商品原 images 数组
# - 非 images/options 字段逐字段比对，差异 = 0
#
# ### 第 7 步：无法匹配的不要硬凑
# 如果某个颜色选项在图片里确实找不到（比如选项写 Khaki 但 7 张图里没有卡其色）：
# - 该颜色**留空**
# - 在最终报告里单独列出：商品 md5、商品名、缺哪个颜色、各图片实际颜色对照表
# - 绝不为了凑满而错配
#
# ## 输出
# 1. 新的 JSON 文件，命名 `<原文件名>_filled.json`，与原文件同目录（无写权限时先写到我的工作区并告知）
# 2. 一份处理报告，包含：
#    - 体检结果（各类型商品数量）
#    - 处理结果（已填满商品数、颜色链接总数）
#    - 校验结果（第 6 步每项的具体数字）
#    - 待人工清单（缺色的商品 + 原因 + 图片颜色对照表）
#    - 低置信判断（同色系难分的商品，说明我为什么这么定）
