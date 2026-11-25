"""Shared data, path and atomic-file rules for the product color tools."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps


COLOR_DIMENSION_NAMES = {"color", "colour", "colors", "colours", "颜色"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
CONTACT_SHEET_COLUMNS = 5
CONTACT_CELL_SIZE = (220, 180)
CONTACT_GAP = 2
CONTACT_LABEL_SIZE = (70, 50)


def normalise_name(value: Any) -> str:
    return re.sub(r"[\s_-]+", " ", str(value or "").strip().casefold())


def find_color_map(options: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(options, list):
        return None, "options 不是列表"
    matches = []
    for entry in options:
        if isinstance(entry, dict):
            matches.extend(values for name, values in entry.items()
                           if normalise_name(name) in COLOR_DIMENSION_NAMES)
    if not matches:
        return None, "没有 Color 维度"
    if len(matches) > 1:
        return None, "存在多个 Color 维度，未自动修改"
    if not isinstance(matches[0], dict):
        return None, "Color 维度不是颜色名到图片 URL 的映射"
    return matches[0], None


def safe_product_folder(root: Path, md5: Any) -> Path | None:
    value = str(md5 or "").strip()
    if (not value or value in {".", ".."} or Path(value).name != value or
            PureWindowsPath(value).name != value or "/" in value or "\\" in value or ":" in value):
        return None
    base = root.resolve()
    candidate = (base / value).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def clean_pasted_path(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


@contextmanager
def atomic_output(path: str | Path, mode: str = "w", encoding: str = "utf-8",
                  newline: str = ""):
    """Replace a file only after its complete new contents have been written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    options = {} if "b" in mode else {"encoding": encoding, "newline": newline}
    try:
        with tempfile.NamedTemporaryFile(mode, dir=path.parent, suffix=".tmp",
                                         delete=False, **options) as handle:
            temp_name = handle.name
            yield handle
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_json(path: str | Path, data: Any) -> None:
    with atomic_output(path) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _contact_sheet_font():
    # Only fonts known to contain Chinese glyphs get a Chinese error label.
    for name in ("msyh.ttc", "simhei.ttf", "simsun.ttc",
                 "NotoSansCJK-Regular.ttc", "Microsoft YaHei.ttf"):
        try:
            return ImageFont.truetype(name, 24), "图片读取失败"
        except OSError:
            pass
    try:
        return ImageFont.truetype("arial.ttf", 24), "LOAD ERROR"
    except OSError:
        try:
            return ImageFont.load_default(size=24), "LOAD ERROR"
        except TypeError:
            return ImageFont.load_default(), "LOAD ERROR"


def create_contact_sheets(
    images_root: str | Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[Path, int, int]:
    """Shared atomic, incremental five-column sheets; never modify originals."""
    root = Path(images_root).resolve()
    output_dir = safe_product_folder(root, "_contact_sheets")
    if output_dir is None:
        raise ValueError("拼图目录超出图片根目录")
    if not root.is_dir():
        return output_dir, 0, 0
    folders = sorted((p for p in root.iterdir() if p.is_dir()
                      and p.name.casefold() != "_contact_sheets"
                      and safe_product_folder(root, p.name) is not None),
                     key=lambda p: p.name.casefold())
    font, error_label = _contact_sheet_font()
    generated = unreadable = 0
    for position, folder in enumerate(folders, 1):
        if progress_callback:
            progress_callback(position, len(folders))
        files = sorted((p for p in folder.iterdir() if p.is_file()
                        and p.suffix.lower() in IMAGE_SUFFIXES and p.stem.isdecimal()),
                       key=lambda p: (int(p.stem), p.name.casefold()))
        if not files:
            continue
        path = output_dir / (folder.name + ".jpg")
        if not path.resolve().is_relative_to(output_dir):
            raise ValueError("拼图文件超出拼图目录")
        try:
            newest = max(folder.stat().st_mtime_ns, *(p.stat().st_mtime_ns for p in files))
            if path.is_file() and path.stat().st_mtime_ns >= newest:
                continue
        except OSError:
            # An unreadable/deleted source becomes a placeholder below, rather
            # than stopping every product's sheet generation.
            pass
        width, height = CONTACT_CELL_SIZE
        rows = (len(files) + CONTACT_SHEET_COLUMNS - 1) // CONTACT_SHEET_COLUMNS
        sheet = Image.new("RGB", (CONTACT_SHEET_COLUMNS * width + (CONTACT_SHEET_COLUMNS + 1) * CONTACT_GAP,
                                  rows * height + (rows + 1) * CONTACT_GAP), (238, 238, 238))
        draw = ImageDraw.Draw(sheet)
        for cell, original in enumerate(files):
            row, column = divmod(cell, CONTACT_SHEET_COLUMNS)
            x = CONTACT_GAP + column * (width + CONTACT_GAP)
            y = CONTACT_GAP + row * (height + CONTACT_GAP)
            try:
                if not original.resolve().is_relative_to(folder.resolve()):
                    raise ValueError("图片路径超出商品目录")
                with Image.open(original) as source:
                    rgba = ImageOps.exif_transpose(source).convert("RGBA")
                    rgba.thumbnail(CONTACT_CELL_SIZE, Image.Resampling.LANCZOS)
                tile = Image.new("RGBA", CONTACT_CELL_SIZE, "white")
                tile.alpha_composite(rgba, ((width - rgba.width) // 2, (height - rgba.height) // 2))
                sheet.paste(tile.convert("RGB"), (x, y))
            except (OSError, ValueError, SyntaxError):
                unreadable += 1
                draw.rectangle((x, y, x + width - 1, y + height - 1), fill=(255, 245, 245))
                draw.text((x + 8, y + 65), error_label, fill=(160, 0, 0), font=font)
            lw, lh = CONTACT_LABEL_SIZE
            draw.rectangle((x, y, x + lw - 1, y + lh - 1), fill="black")
            label = str(int(original.stem))
            left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
            draw.text((x + max(2, (lw - right + left) // 2) - left,
                       y + max(2, (lh - bottom + top) // 2) - top), label, fill=(255, 220, 0), font=font)
        with atomic_output(path, "wb") as handle:
            sheet.save(handle, format="JPEG", quality=90, optimize=True)
        generated += 1
    return output_dir, generated, unreadable
