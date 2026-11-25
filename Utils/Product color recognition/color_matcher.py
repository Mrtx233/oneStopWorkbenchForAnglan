#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品图片本地颜色识别、人工复核与手动标注平台。

用法:
    python "Utils/Product color recognition/color_matcher.py" products.json images
    python "Utils/Product color recognition/color_matcher.py"

图片路径按 download_images.py 的规则解析：<图片目录>/<md5>/<images索引:03d>.(jpg|png)。
启动后在浏览器中逐商品查看拼图，可先运行本地识别，再确认或手动调整。
自动成功结果写入输出 JSON，未成功结果仅保存候选和原因，人工操作优先。
原始 JSON 保留不变；识别来源和复核状态保存在兼容旧版的进度文件中。
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
import copy
import hashlib
import json
import mimetypes
from pathlib import Path
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from typing import Any

from local_color_recognition import extract_features, recognize_product
from product_data import (
    IMAGE_SUFFIXES, CONTACT_SHEET_COLUMNS, CONTACT_CELL_SIZE, CONTACT_GAP,
    CONTACT_LABEL_SIZE, create_contact_sheets,
    atomic_json as _atomic_json,
    clean_pasted_path as _clean_pasted_path,
    find_color_map as _find_color_map,
    safe_product_folder as _safe_product_folder,
)


def _image_for_index(folder: Path, index: int) -> tuple[Path | None, str | None]:
    if type(index) is not int or index < 0:
        return None, "图片序号无效"
    stem = f"{index:03d}"
    matches = [path for path in folder.glob(stem + ".*")
               if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    if len(matches) == 1:
        resolved = matches[0].resolve()
        if not resolved.is_relative_to(folder.resolve()):
            return None, "图片路径超出商品目录"
        return resolved, None
    if not matches:
        return None, "找不到该序号图片"
    return None, "同一序号存在多个图片文件，无法确定使用哪一个"


MANUAL_LABEL_PLATFORM_HTML = (
    Path(__file__).resolve().parent / "ui" / "index.html"
).read_text(encoding="utf-8")


class ManualLabelPlatform:
    """原始索引始终引用输入 JSON；识别来源和复核状态只写入进度侧车文件。"""

    FEATURE_CACHE_LIMIT = 256

    def __init__(self, json_path: Path, images_root: Path, output_path: Path):
        self.json_path = json_path.resolve()
        self.images_root = images_root.resolve()
        self.output_path = output_path.resolve()
        self.progress_path = self.output_path.with_name(self.output_path.stem + '_progress.json')
        if self.json_path in {self.output_path, self.progress_path}:
            raise ValueError('输出文件或进度文件不能覆盖原 JSON')
        source_bytes = self.json_path.read_bytes()
        self.source_hash = hashlib.sha256(source_bytes).hexdigest()
        self.source_data = json.loads(source_bytes.decode('utf-8-sig'))
        if not isinstance(self.source_data, list):
            raise ValueError('商品 JSON 顶层必须是数组')
        self.assignments: dict[int, dict[str, int]] = {}
        self.origins: dict[int, dict[str, str]] = {}
        self.detections: dict[int, dict[str, dict[str, Any]]] = {}
        self.cleared: set[tuple[int, str]] = set()
        self.reviewed: set[tuple[int, str]] = set()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.feature_cache: OrderedDict[tuple[str, int, int], dict[str, Any]] = OrderedDict()
        self.job = {'running': False, 'stopping': False, 'stopped': False,
                    'total': 0, 'completed': 0, 'current': '', 'error': '', 'elapsed': 0}
        self._load_progress()

    def _product_colors(self, item: Any) -> tuple[dict[str, Any], str | None]:
        if not isinstance(item, dict):
            return {}, '商品数据不是对象'
        colors, error = _find_color_map(item.get('options'))
        return colors or {}, error

    def _load_progress(self) -> None:
        if not self.progress_path.is_file():
            if self.output_path.exists():
                raise ValueError('已有输出 JSON 但缺少进度文件；请恢复原进度文件或用 --output 指定新文件')
            return
        saved = json.loads(self.progress_path.read_text(encoding='utf-8-sig'))
        if not isinstance(saved, dict) or saved.get('source_sha256') != self.source_hash:
            raise ValueError('进度文件与输入 JSON 不匹配，请选择当初的原始 JSON，或用 --output 指定新文件')
        if saved.get('output_sha256') and self.output_path.exists():
            if hashlib.sha256(self.output_path.read_bytes()).hexdigest() != saved['output_sha256']:
                raise ValueError('输出 JSON 与进度文件不一致，请恢复配套文件或用 --output 指定新文件')
        for product_id, colors in saved.get('assignments', {}).items():
            try:
                index = int(product_id)
            except (ValueError, TypeError):
                continue
            if not 0 <= index < len(self.source_data) or not isinstance(colors, dict):
                continue
            item = self.source_data[index]
            color_map, error = self._product_colors(item)
            images = item.get('images', []) if isinstance(item, dict) else []
            if error or not isinstance(images, list):
                continue
            for name, image_index in colors.items():
                if name not in color_map or type(image_index) is not int or not 0 <= image_index < len(images):
                    continue
                if not isinstance(images[image_index], str) or not images[image_index].strip():
                    continue
                self.assignments.setdefault(index, {})[name] = image_index
                origin = saved.get('origins', {}).get(str(index), {}).get(name, 'manual')
                # 旧版进度全为手工操作，不能把它们误标为自动识别。
                self.origins.setdefault(index, {})[name] = 'auto' if origin == 'auto' else 'manual'
        for key, target in (('cleared', self.cleared), ('reviewed', self.reviewed)):
            for entry in saved.get(key, []):
                if not isinstance(entry, list) or len(entry) != 2 or type(entry[0]) is not int:
                    continue
                index, name = entry
                if 0 <= index < len(self.source_data) and isinstance(name, str):
                    color_map, _ = self._product_colors(self.source_data[index])
                    if name in color_map:
                        target.add((index, name))
        for product_id, colors in saved.get('detections', {}).items():
            try:
                index = int(product_id)
            except (TypeError, ValueError):
                continue
            if not 0 <= index < len(self.source_data) or not isinstance(colors, dict):
                continue
            color_map, _ = self._product_colors(self.source_data[index])
            for name, info in colors.items():
                if name in color_map and isinstance(info, dict):
                    self.detections.setdefault(index, {})[name] = info
        for index, name in self.cleared:
            self.assignments.get(index, {}).pop(name, None)
            self.origins.get(index, {}).pop(name, None)

    def _progress_payload(self, output_hash: str | None = None) -> dict[str, Any]:
        return {
            'version': 2, 'source_sha256': self.source_hash,
            **({'output_sha256': output_hash} if output_hash else {}),
            'assignments': {str(index): values for index, values in self.assignments.items()},
            'origins': {str(index): values for index, values in self.origins.items()},
            'detections': {str(index): values for index, values in self.detections.items()},
            'cleared': [list(pair) for pair in sorted(self.cleared)],
            'reviewed': [list(pair) for pair in sorted(self.reviewed)],
        }

    def _color_state(self, product_id: int, name: str) -> dict[str, Any]:
        item = self.source_data[product_id]
        colors, _ = self._product_colors(item)
        images = item.get('images', []) if isinstance(item.get('images'), list) else []
        original_url = colors[name] if isinstance(colors[name], str) else ''
        index = self.assignments.get(product_id, {}).get(name)
        origin = self.origins.get(product_id, {}).get(name, 'manual')
        detection = self.detections.get(product_id, {}).get(name, {})
        url = original_url
        status = 'existing' if url.strip() else 'pending'
        if index is not None:
            url = images[index]
            if origin == 'auto':
                status = 'auto_confirmed' if (product_id, name) in self.reviewed else 'auto_success'
            else:
                status = 'manual_done'
        else:
            index = next((i for i, value in enumerate(images) if value == original_url and original_url.strip()), None)
        if (product_id, name) in self.cleared:
            url, index, status = '', None, 'manual_pending'
        elif not url.strip() and detection:
            status = 'auto_failed'
        labels = {'existing': '原有链接', 'pending': '尚未识别', 'auto_success': '自动识别成功 · 待确认',
                  'auto_confirmed': '自动识别 · 人工已确认', 'manual_done': '人工已调整' if detection else '人工已标注',
                  'manual_pending': '人工已清除 · 待标注', 'auto_failed': '识别未成功 · 待人工复核'}
        return {'name': name, 'url': url, 'assigned_index': index, 'status': status,
                'status_label': labels[status], 'needs_review': status in {'pending', 'auto_failed', 'manual_pending', 'auto_success'},
                'detection': detection}

    def _cells(self, folder: Path, images: list[Any]) -> list[dict[str, Any]]:
        if not folder.is_dir():
            return []
        files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES and p.stem.isdecimal()),
                       key=lambda p: (int(p.stem), p.name.casefold()))
        width, height = CONTACT_CELL_SIZE
        sheet_width = CONTACT_SHEET_COLUMNS * width + (CONTACT_SHEET_COLUMNS + 1) * CONTACT_GAP
        rows = (len(files) + CONTACT_SHEET_COLUMNS - 1) // CONTACT_SHEET_COLUMNS
        sheet_height = rows * height + (rows + 1) * CONTACT_GAP
        cells = []
        for position, path in enumerate(files):
            image_index = int(path.stem)
            if image_index >= len(images) or not isinstance(images[image_index], str) or not images[image_index].strip():
                continue
            row, column = divmod(position, CONTACT_SHEET_COLUMNS)
            cells.append({'image_index': image_index,
                          'left': (CONTACT_GAP + column * (width + CONTACT_GAP)) / sheet_width * 100,
                          'top': (CONTACT_GAP + row * (height + CONTACT_GAP)) / sheet_height * 100,
                          'width': width / sheet_width * 100, 'height': height / sheet_height * 100})
        return cells

    def state(self) -> dict[str, Any]:
        with self.lock:
            products = []
            totals = Counter()
            for product_id, item in enumerate(self.source_data):
                if not isinstance(item, dict):
                    continue
                colors_map, error = self._product_colors(item)
                colors = [self._color_state(product_id, name) for name in colors_map]
                counts = Counter(color['status'] for color in colors)
                totals.update(counts)
                md5 = str(item.get('md5') or '')
                images = item.get('images') if isinstance(item.get('images'), list) else []
                folder = _safe_product_folder(self.images_root, md5)
                cells = self._cells(folder, images) if folder else []
                sheet_error = ''
                try:
                    self.sheet_path(product_id)
                    sheet_url = '/api/sheet?id=' + str(product_id)
                except (OSError, ValueError):
                    sheet_url = None
                if not folder or not folder.is_dir():
                    sheet_error = 'MD5 图片文件夹不存在；请先运行 download_images.py。'
                elif not cells:
                    sheet_error = '此商品没有可用的编号图片。'
                elif not sheet_url:
                    sheet_error = '拼图不存在；重启平台会生成。'
                products.append({'id': product_id, 'md5': md5, 'title': str(item.get('title') or ''), 'colors': colors,
                                 'pending': sum(not c['url'].strip() for c in colors), 'counts': dict(counts),
                                 'review_count': sum(c['needs_review'] for c in colors),
                                 'image_count': len(images), 'cells': cells, 'sheet_url': sheet_url,
                                 'sheet_error': sheet_error, 'error': error})
            return {'products': products, 'output': str(self.output_path), 'totals': dict(totals), 'job': dict(self.job)}

    def _build_output(self) -> list[Any]:
        result = copy.deepcopy(self.source_data)
        changed_ids = set(self.assignments) | {index for index, _ in self.cleared}
        for product_id in changed_ids:
            item = result[product_id]
            colors, error = self._product_colors(item)
            if error:
                continue
            original = self.source_data[product_id]
            original_colors, _ = self._product_colors(original)
            images = original.get('images', [])
            if not isinstance(images, list):
                raise ValueError('images 必须是数组，拒绝生成可能丢图的输出')
            for name in colors:
                if (product_id, name) in self.cleared:
                    colors[name] = ''
                elif name in self.assignments.get(product_id, {}):
                    colors[name] = images[self.assignments[product_id][name]]
            # Treat original Color links overlapping images as references to the
            # same inventory. Preserve repeated source entries (one allocation
            # consumes one occurrence), and return Color-only URLs in key order.
            inventory = list(images)
            available = Counter(url for url in images if isinstance(url, str))
            original_links = Counter()
            for value in original_colors.values():
                if isinstance(value, str) and value.strip():
                    original_links[value] += 1
                    if original_links[value] > available[value]:
                        inventory.append(value)
            remaining = list(inventory)
            for value in colors.values():
                if isinstance(value, str) and value.strip():
                    if value not in remaining:
                        raise ValueError('颜色分配违反图片守恒，拒绝保存')
                    remaining.remove(value)
            item['images'] = remaining
        return result

    def save(self) -> None:
        with self.lock:
            if hashlib.sha256(self.json_path.read_bytes()).hexdigest() != self.source_hash:
                raise ValueError('原始 JSON 已发生变化，拒绝写入与 source_sha256 不一致的进度')
            _atomic_json(self.output_path, self._build_output())
            output_hash = hashlib.sha256(self.output_path.read_bytes()).hexdigest()
            _atomic_json(self.progress_path, self._progress_payload(output_hash))

    def _validate_product(self, product_id: int, color: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        if type(product_id) is not int or not 0 <= product_id < len(self.source_data):
            raise ValueError('商品序号无效')
        item = self.source_data[product_id]
        colors, error = self._product_colors(item)
        if error or (color is not None and color not in colors):
            raise ValueError('颜色选项不存在，或该商品没有可编辑的 Color 对象')
        return item, colors

    def assign(self, product_id: int, color: str, image_index: int | None) -> None:
        with self.lock:
            item, colors = self._validate_product(product_id, color)
            if image_index is not None:
                images = item.get('images')
                if not isinstance(images, list) or type(image_index) is not int or not 0 <= image_index < len(images):
                    raise ValueError('图片序号超出原 JSON images 数组范围')
                url = images[image_index]
                if not isinstance(url, str) or not url.strip():
                    raise ValueError('该序号没有有效的原始图片 URL')
                folder = _safe_product_folder(self.images_root, item.get('md5'))
                _, issue = _image_for_index(folder, image_index) if folder else (None, 'MD5 图片文件夹不存在')
                if issue:
                    raise ValueError(issue)
                conflicts = [self._color_state(product_id, name) for name in colors if name != color]
                for other in conflicts:
                    if other['url'] == url and other['status'] != 'auto_success':
                        raise ValueError(f'此图片已绑定到 {other["name"]}；请先清除该颜色的绑定')
                # 未确认的自动结果让位于人工选择；已确认结果不会被静默覆盖。
                for other in conflicts:
                    if other['url'] == url:
                        name = other['name']
                        self.assignments.get(product_id, {}).pop(name, None)
                        self.origins.get(product_id, {}).pop(name, None)
                        self.detections.setdefault(product_id, {})[name] = {
                            **other['detection'], 'status': 'review', 'reason': '候选图片已被人工分配给其他颜色，请复核'}
            self.assignments.setdefault(product_id, {}).pop(color, None)
            self.origins.setdefault(product_id, {}).pop(color, None)
            if image_index is None:
                self.cleared.add((product_id, color))
                self.reviewed.discard((product_id, color))
            else:
                self.assignments[product_id][color] = image_index
                self.origins[product_id][color] = 'manual'
                self.reviewed.add((product_id, color))
                self.cleared.discard((product_id, color))
            self.save()

    def confirm(self, product_id: int, color: str | None = None) -> int:
        with self.lock:
            _, colors = self._validate_product(product_id, color)
            names = [color] if color is not None else list(colors)
            confirmed = [name for name in names if self._color_state(product_id, name)['status'] == 'auto_success']
            if not confirmed:
                raise ValueError('没有待确认的自动识别结果')
            self.reviewed.update((product_id, name) for name in confirmed)
            self.save()
            return len(confirmed)

    def _eligible(self, product_id: int) -> list[str]:
        colors, error = self._product_colors(self.source_data[product_id])
        if error:
            return []
        return [name for name in colors if self._color_state(product_id, name)['status'] in {'pending', 'auto_failed', 'auto_success'}]

    def start_recognition(self, product_id: int | None = None) -> None:
        with self.lock:
            if self.job['running']:
                raise ValueError('已有识别任务在运行，请等待完成')
            if product_id is not None:
                self._validate_product(product_id)
            ids = [product_id] if product_id is not None else list(range(len(self.source_data)))
            ids = [index for index in ids if self._eligible(index)]
            self.job = {'running': bool(ids), 'stopping': False, 'stopped': False,
                        'total': len(ids), 'completed': 0, 'current': '', 'error': '', 'elapsed': 0}
            if not ids:
                return
            self.stop_event.clear()
            self.worker = threading.Thread(target=self._run_recognition, args=(ids,), daemon=True, name='local-color-recognition')
            self.worker.start()

    def stop_recognition(self) -> dict[str, Any]:
        # Do not claim idle until the worker has really exited: this prevents
        # an immediate restart from reviving the previous job via event.clear().
        with self.lock:
            if self.job['running']:
                self.stop_event.set()
                self.job['stopping'] = True
            return dict(self.job)

    def _run_recognition(self, ids: list[int]) -> None:
        started = time.monotonic()
        try:
            for product_id in ids:
                if self.stop_event.is_set():
                    break
                item = self.source_data[product_id]
                with self.lock:
                    self.job['current'] = str(item.get('title') or item.get('md5') or '')
                completed = self._recognize_one(product_id)
                with self.lock:
                    if completed:
                        self.job['completed'] += 1
                    self.job['elapsed'] = round(time.monotonic() - started, 1)
        except Exception as exc:
            with self.lock:
                self.job['error'] = f'识别中止：{exc}；可继续人工标注或重新识别'
        finally:
            with self.lock:
                self.job['running'] = False
                self.job['stopped'] = self.stop_event.is_set()
                self.job['stopping'] = False
                self.job['current'] = ''
                self.job['elapsed'] = round(time.monotonic() - started, 1)

    def _cached_features(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        with self.lock:
            if key in self.feature_cache:
                self.feature_cache.move_to_end(key)
                return self.feature_cache[key]
        feature = extract_features(path)
        with self.lock:
            self.feature_cache[key] = feature
            self.feature_cache.move_to_end(key)
            while len(self.feature_cache) > self.FEATURE_CACHE_LIMIT:
                self.feature_cache.popitem(last=False)
        return feature

    def _recognize_one(self, product_id: int) -> bool:
        item = self.source_data[product_id]
        images = item.get('images') if isinstance(item.get('images'), list) else []
        folder = _safe_product_folder(self.images_root, item.get('md5'))
        features = {}
        for index, url in enumerate(images):
            if self.stop_event.is_set():
                return False
            if not isinstance(url, str) or not url.strip():
                continue
            path, issue = _image_for_index(folder, index) if folder else (None, 'MD5 图片文件夹不存在')
            if issue or path is None:
                features[index] = {'error': issue or '图片文件不存在'}
                continue
            try:
                features[index] = self._cached_features(path)
            except (OSError, ValueError, SyntaxError) as exc:
                features[index] = {'error': f'图片无法读取：{exc}'}
        with self.lock:
            if self.stop_event.is_set():
                return False
            colors, _ = self._product_colors(item)
            eligible = self._eligible(product_id)
            if not eligible:
                return True
            reserved = {self._color_state(product_id, name)['url'] for name in colors if name not in eligible}
        detections = recognize_product(list(colors), features, reserved, images, targets=eligible)
        with self.lock:
            if self.stop_event.is_set():
                return False
            # Manual edits may have happened while extracting/scoring; revalidate
            # eligibility and reservations at commit time, under the same lock.
            eligible = [name for name in eligible if name in self._eligible(product_id)]
            reserved = {self._color_state(product_id, name)['url'] for name in colors if name not in eligible}
            # 重算只替换尚未人工确认的自动结果；原索引和人工状态始终不动。
            for name in eligible:
                self.assignments.get(product_id, {}).pop(name, None)
                self.origins.get(product_id, {}).pop(name, None)
                info = detections[name]
                if info['status'] == 'success' and images[info['image_index']] in reserved:
                    info = {**info, 'status': 'review', 'reason': '候选已被人工绑定给其他颜色，请复核'}
                self.detections.setdefault(product_id, {})[name] = info
                if info['status'] == 'success':
                    self.assignments.setdefault(product_id, {})[name] = info['image_index']
                    self.origins.setdefault(product_id, {})[name] = 'auto'
            self.save()
            return True

    def image_path(self, product_id: int, image_index: int) -> Path:
        item, _ = self._validate_product(product_id)
        images = item.get('images')
        if (not isinstance(images, list) or type(image_index) is not int
                or not 0 <= image_index < len(images)
                or not isinstance(images[image_index], str) or not images[image_index].strip()):
            raise ValueError('图片序号超出原 JSON images 数组范围或 URL 无效')
        folder = _safe_product_folder(self.images_root, item.get('md5'))
        if folder is None or not folder.is_dir():
            raise ValueError('MD5 图片文件夹无效')
        path, issue = _image_for_index(folder, image_index)
        if issue:
            raise ValueError(issue)
        return path

    def sheet_path(self, product_id: int) -> Path:
        if type(product_id) is not int or not 0 <= product_id < len(self.source_data):
            raise ValueError('商品序号无效')
        item = self.source_data[product_id]
        md5 = item.get('md5') if isinstance(item, dict) else None
        folder = _safe_product_folder(self.images_root, md5)
        if folder is None:
            raise ValueError('MD5 图片文件夹无效')
        contact_root = _safe_product_folder(self.images_root, '_contact_sheets')
        if contact_root is None:
            raise ValueError('拼图目录超出图片根目录')
        path = (contact_root / (str(md5) + '.jpg')).resolve()
        if not path.is_relative_to(contact_root) or not path.is_file():
            raise FileNotFoundError('拼图不存在')
        return path


def _make_handler(platform: ManualLabelPlatform):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ColorLabel/1.0"

        def _json(self, value: Any, status: int = 200) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = MANUAL_LABEL_PLATFORM_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/state":
                with platform.lock:
                    self._json(platform.state())
                return
            if parsed.path in {"/api/sheet", "/api/image"}:
                try:
                    query = parse_qs(parsed.query)
                    product_id = int(query.get("id", [""])[0])
                    with platform.lock:
                        path = (platform.image_path(product_id, int(query.get("index", [""])[0]))
                                if parsed.path == "/api/image" else platform.sheet_path(product_id))
                        body = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "image/jpeg")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                except (ValueError, FileNotFoundError, OSError) as exc:
                    self._json({"error": str(exc)}, 404)
                return
            self._json({"error": "接口不存在"}, 404)

        def do_POST(self) -> None:
            if self.path not in {"/api/assign", "/api/save", "/api/recognize", "/api/recognize/stop", "/api/confirm"}:
                self._json({"error": "接口不存在"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1024 * 1024:
                    raise ValueError("请求内容过大")
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                if not isinstance(payload, dict):
                    raise ValueError("请求格式无效")
                if self.path == "/api/assign":
                    product_id = payload.get("id")
                    color = payload.get("color")
                    image_index = payload.get("image_index")
                    if type(product_id) is not int or not isinstance(color, str):
                        raise ValueError("商品或颜色参数无效")
                    if image_index is not None and type(image_index) is not int:
                        raise ValueError("图片序号参数无效")
                    with platform.lock:
                        platform.assign(product_id, color, image_index)
                    self._json({"ok": True})
                elif self.path == "/api/recognize/stop":
                    self._json({"ok": True, "job": platform.stop_recognition()})
                elif self.path == "/api/recognize":
                    product_id = payload.get("id")
                    if product_id is not None and type(product_id) is not int:
                        raise ValueError("商品序号无效")
                    platform.start_recognition(product_id)
                    self._json({"ok": True})
                elif self.path == "/api/confirm":
                    product_id = payload.get("id")
                    color = payload.get("color")
                    if type(product_id) is not int or (color is not None and not isinstance(color, str)):
                        raise ValueError("商品或颜色参数无效")
                    confirmed = platform.confirm(product_id, color)
                    self._json({"ok": True, "confirmed": confirmed})
                else:
                    with platform.lock:
                        platform.save()
                    self._json({"ok": True, "output": str(platform.output_path)})
            except (ValueError, json.JSONDecodeError, OSError) as exc:
                self._json({"error": str(exc)}, 400)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="本地颜色识别、人工复核与标注商品 Color 图片")
    parser.add_argument("json_file", nargs="?", type=Path, help="商品 JSON 文件")
    parser.add_argument("images_dir_pos", nargs="?", type=Path, help="图片目录；默认 JSON 同目录下的 images/")
    parser.add_argument("--images-dir", type=Path, help="指定图片目录")
    parser.add_argument("--output", type=Path, help="输出 JSON；默认 <原文件名>_manual_labeled.json")
    args = parser.parse_args()
    if args.images_dir and args.images_dir_pos:
        parser.error("图片目录请只用位置参数或 --images-dir 指定一次")
    images_dir = args.images_dir or args.images_dir_pos

    if args.json_file is None:
        try:
            pasted_json = _clean_pasted_path(input("请粘贴商品 JSON 文件路径："))
            if not pasted_json:
                print("未提供 JSON 文件路径，已退出。")
                return 2
            pasted_images = ("" if images_dir is not None else _clean_pasted_path(
                input("请粘贴图片文件夹路径（直接回车使用 JSON 同目录下的 images）：")))
        except (EOFError, KeyboardInterrupt):
            print("输入已取消。")
            return 130
        json_file = Path(pasted_json)
        if pasted_images:
            images_dir = Path(pasted_images)
    else:
        json_file = args.json_file

    json_path = Path(_clean_pasted_path(str(json_file))).expanduser().resolve()
    if not json_path.is_file():
        parser.error(f"JSON 文件不存在：{json_path}")
    images_root = Path(_clean_pasted_path(str(images_dir or json_path.parent / "images"))).expanduser().resolve()
    if not images_root.is_dir():
        parser.error(f"图片目录不存在：{images_root}；请先运行 download_images.py")
    output_path = Path(_clean_pasted_path(str(
        args.output or json_path.with_name(json_path.stem + "_manual_labeled.json")))).expanduser().resolve()
    if output_path == json_path:
        parser.error("输出 JSON 不能覆盖原文件")

    try:
        platform = ManualLabelPlatform(json_path, images_root, output_path)
        print("正在检查并生成缺失或过期的商品拼图…")
        _contact_dir, sheet_count, unreadable_count = create_contact_sheets(images_root)
        if unreadable_count:
            print(f"拼图中有 {unreadable_count} 张图片读取失败，已标出。")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"启动失败：{exc}")
        return 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(platform))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"商品数：{len(platform.source_data)}；本次新生成拼图：{sheet_count}")
    print(f"标注结果将自动保存到：{output_path}")
    print(f"进度文件：{platform.progress_path}")
    print(f"标注平台已启动：{url}")
    print("在页面点击“本地识别全部”，按状态筛选后确认或手动调整；每次修改自动保存。")
    print("按 Ctrl+C 关闭平台。")
    threading.Timer(0.4, lambda: webbrowser.open(url, new=2)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n正在关闭标注平台…")
    finally:
        platform.stop_event.set()
        if platform.worker is not None:
            platform.worker.join(timeout=5)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
