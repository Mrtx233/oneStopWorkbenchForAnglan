"""Stage 04.1: download images referenced by a WooCommerce CSV."""
from pathlib import Path

from common.step_loader import load_step

HERE = Path(__file__).resolve().parent


def run(settings, stop, emit):
    csv_path = settings.get('image_csv')
    wp_site = (settings.get('image_wp_site') or '').strip()
    workers = int(settings.get('image_workers', 8))
    if not csv_path:
        raise ValueError('请先选择阶段 04 导出的 WP CSV')
    if not wp_site:
        raise ValueError('请填写目标 WordPress 地址')
    downloader = load_step(HERE / '20_downloader.py')
    return downloader.run_download(csv_path, wp_site, workers, stop, emit)
