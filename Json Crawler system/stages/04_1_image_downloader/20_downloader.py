"""Download WooCommerce CSV images and rewrite successful URLs."""
import csv
from datetime import datetime
import hashlib
import mimetypes
from pathlib import Path
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import requests

try:
    from PIL import Image
    from io import BytesIO
except ImportError:
    Image = None
    BytesIO = None


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.avif'}
RETRYABLE_STATUS = {408, 425, 429}


def split_image_values(value):
    return [part.strip() for part in re.split(r'\s*,\s*', value or '') if part.strip()]


def split_urls(value):
    return [part for part in split_image_values(value)
            if urlsplit(part).scheme.lower() in {'http', 'https'}]


def _image_data(content, content_type, url):
    if Image is not None:
        try:
            image = Image.open(BytesIO(content))
            image.load()
            if image.format in {'JPEG', 'JPG'} and image.mode in {'RGB', 'L'}:
                return content, '.jpg'
            if image.mode in {'RGBA', 'LA', 'P'}:
                rgba = image.convert('RGBA')
                background = Image.new('RGB', rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel('A'))
                image = background
            else:
                image = image.convert('RGB')
            output = BytesIO()
            image.save(output, format='JPEG', quality=90)
            return output.getvalue(), '.jpg'
        except Exception as exc:
            raise ValueError('响应内容不是有效图片') from exc

    media_type = (content_type or '').split(';', 1)[0].strip().lower()
    extension = mimetypes.guess_extension(media_type) if media_type.startswith('image/') else None
    if extension == '.jpe':
        extension = '.jpg'
    if extension not in IMAGE_EXTENSIONS:
        suffix = Path(urlsplit(url).path).suffix.lower()
        extension = suffix if suffix in IMAGE_EXTENSIONS else None
    if extension is None:
        raise ValueError(f'无法识别图片格式 ({media_type or "unknown"})')
    return content, extension


def _atomic_csv(path, fieldnames, rows):
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8-sig', newline='',
                                         dir=path.parent, suffix='.tmp', delete=False) as handle:
            temp_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def run_download(csv_path, wp_site, workers, stop, emit):
    source = Path(csv_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.csv':
        raise ValueError(f'WP CSV 文件不存在或格式不正确：{source}')
    parts = urlsplit(wp_site)
    if parts.scheme.lower() != 'https' or not parts.netloc:
        raise ValueError('WordPress 地址必须是有效的 https:// 地址')

    with source.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if 'Images' not in fields:
            raise ValueError(f'CSV 缺少 Images 列；现有列：{fields}')
        rows = [{key: value or '' for key, value in row.items() if key is not None}
                for row in reader]

    urls = list(dict.fromkeys(url for row in rows for url in split_urls(row.get('Images', ''))))
    now = datetime.now()
    upload_path = f'{wp_site.rstrip("/")}/wp-content/uploads/{now:%Y/%m}/'
    image_dir = source.with_name(f'{source.stem}-images')
    image_dir.mkdir(parents=True, exist_ok=True)
    output = source.with_name(f'{source.stem}-imageOK-{now:%Y%m%d_%H%M%S}.csv')
    emit('log', text=f'读取 {len(rows)} 行，提取到 {len(urls)} 个唯一图片地址')
    emit('log', text=f'图片目录：{image_dir}')
    emit('log', text=f'目标上传路径：{upload_path}')

    url_map = {}
    failures = {}

    def download(url):
        digest = hashlib.md5(url.encode('utf-8')).hexdigest()
        existing = next((path for path in image_dir.glob(digest + '.*')
                         if path.is_file() and path.stat().st_size > 0), None)
        for empty_file in image_dir.glob(digest + '.*'):
            if empty_file.is_file() and empty_file.stat().st_size == 0:
                empty_file.unlink(missing_ok=True)
        if existing:
            return url, upload_path + existing.name, None
        last_error = None
        for attempt in range(1, 4):
            if stop.is_set():
                return url, None, '已停止'
            try:
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=40)
                if response.status_code != 200:
                    last_error = f'HTTP {response.status_code}'
                    if response.status_code not in RETRYABLE_STATUS and response.status_code < 500:
                        break
                    if attempt < 3:
                        time.sleep(attempt * 2)
                        continue
                    break
                data, extension = _image_data(response.content, response.headers.get('Content-Type', ''), url)
                filename = digest + extension
                target = image_dir / filename
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile('wb', dir=image_dir, suffix='.part', delete=False) as handle:
                        temp_path = Path(handle.name)
                        handle.write(data)
                    temp_path.replace(target)
                finally:
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
                return url, upload_path + filename, None
            except (requests.RequestException, ValueError, OSError) as exc:
                last_error = str(exc)
                if isinstance(exc, ValueError):
                    break
                if attempt < 3:
                    time.sleep(attempt * 2)
        return url, None, last_error or '下载失败'

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(download, url) for url in urls]
        for current, future in enumerate(as_completed(futures), 1):
            url, replacement, error = future.result()
            if replacement:
                url_map[url] = replacement
            elif error != '已停止':
                failures[url] = error
            emit('progress', current=current, total=len(urls),
                 text=f'图片 {current}/{len(urls)}：' + ('完成' if replacement else error or '已停止'))

    for row in rows:
        row['Images'] = ', '.join(url_map.get(value, value)
                                  for value in split_image_values(row.get('Images', '')))
    _atomic_csv(output, fields, rows)

    if failures:
        failed_images = image_dir / 'failed_images.txt'
        failed_images.write_text('\n'.join(failures), encoding='utf-8')
        for url, error in failures.items():
            emit('log', text=f'下载失败：{url}（{error}）')
        if 'SKU' in fields:
            failed_set = set(failures)
            skus = list(dict.fromkeys(
                str(row.get('Parent') or row.get('SKU') or '').strip()
                for row in rows
                if any(url in failed_set for url in split_urls(row.get('Images', '')))
                and str(row.get('Parent') or row.get('SKU') or '').strip()
            ))
            (image_dir / 'failed_skus.txt').write_text('\n'.join(skus), encoding='utf-8-sig')
        else:
            (image_dir / 'failed_skus.txt').unlink(missing_ok=True)
        emit('log', text=f'{len(failures)} 个图片地址未能下载，清单：{failed_images}')
    else:
        (image_dir / 'failed_images.txt').unlink(missing_ok=True)
        (image_dir / 'failed_skus.txt').unlink(missing_ok=True)

    emit('log', text=f'新 WP CSV：{output}')
    emit('log', text=f'下载完成：成功 {len(url_map)}，失败 {len(failures)}')
    emit('artifact', path=str(image_dir), text='下载图片目录')
    emit('artifact', path=str(output), text='图片链接替换后的 WP CSV')
    if stop.is_set():
        return 'stopped'
    return 'partial' if failures else 'success'
