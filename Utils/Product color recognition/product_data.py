"""Shared data, path and atomic-file rules for the product color tools."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
from typing import Any


COLOR_DIMENSION_NAMES = {"color", "colour", "colors", "colours", "颜色"}


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
