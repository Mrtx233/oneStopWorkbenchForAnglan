# -*- coding: utf-8 -*-
# =====================================================================
# 文件名   : Image Downloader.py（WordPress 图片批量下载工具）
# 来源     : 由 wp-CsvImagesDownLoad.exe 逆向还原（PyInstaller 打包 / Python 3.10）
# 说明     : 本文件为还原代码的"整理注释版"，逻辑与原始程序完全一致，
#            仅补充了模块分区、类与方法注释，便于阅读和维护。
#
# ┌─ 功能流程 ─────────────────────────────────────────────────────┐
# │ 1. 选择 CSV 文件 → 读取其中的 "Images" 列                       │
# │ 2. 提取该列中的图片 URL（支持一行多图，逗号分隔）并去重          │
# │ 3. 多线程并发下载图片到本地目录                                  │
# │ 4. 将 CSV 中的图片链接替换为 WordPress 上传路径                  │
# │ 5. 保存新 CSV、失败图片 URL 清单、失败商品 SKU 清单                          │
# └────────────────────────────────────────────────────────────────┘
# =====================================================================


# =====================================================================
# 第一部分：标准库导入
# =====================================================================
import os            # 路径、目录、文件操作
import re            # 正则表达式（分割、清洗文件名）
import time          # 下载失败后的重试间隔
import hashlib       # MD5，用于生成唯一的本地文件名
from io import BytesIO                # 内存字节流，用于图片格式转换

# =====================================================================
# 第二部分：第三方库导入
# =====================================================================
import pandas as pd                 # 读取 / 处理 CSV
import requests                     # 发起 HTTP 图片下载
from concurrent.futures import ThreadPoolExecutor, as_completed  # 多线程下载
import threading                    # 线程锁（保证字典写入安全）
from datetime import datetime       # 时间戳、目录年份月份、日志时间

try:
    from PIL import Image           # 图片格式转换（png/webp 等转 jpg）
    _pil_ok = True
except ImportError:                 # 未安装 Pillow 时降级：跳过转换，仅按原扩展名处理
    Image = None
    _pil_ok = False

if _pil_ok:
    try:
        import pillow_heif          # HEIC/HEIF（苹果设备照片）解码支持
        pillow_heif.register_heif_opener()  # 注册后 Image.open 可识别 .heic/.heif
    except ImportError:             # 未装 pillow-heif 时仅无法转 HEIC，其余格式不受影响
        pass

# =====================================================================
# 第三部分：GUI 库导入（tkinter 及扩展）
# =====================================================================
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkinter.ttk import Progressbar


# =====================================================================
# 类一：ImageDownloader —— 图片下载核心业务逻辑
# =====================================================================
class ImageDownloader:
    """
    负责完整的图片下载流程：
      初始化 → 创建目录 → 读取CSV → 提取URL → 多线程下载 → 保存失败清单 → 替换链接 → 保存新CSV
    不依赖界面，可通过回调函数把日志/进度传递给外部（如 GUI）。
    """

    # ---------------------------------------------------------------
    # 构造方法：接收配置并初始化内部状态
    # ---------------------------------------------------------------
    def __init__(self, csv_file, wp_site, download_workers, log_callback, progress_callback,
                 retry_rounds=1, retry_wait=5, only_urls=None,
                 image_dir=None, new_csv_tag='imageOK', max_attempts=3):
        """初始化下载器。

        参数:
            csv_file           : 要处理的 CSV 文件路径
            wp_site            : WordPress 站点地址（会自动补齐末尾斜杠）
            download_workers   : 并发下载线程数
            log_callback       : 日志回调函数，接收一个字符串参数
            progress_callback  : 进度回调函数，接收 (current, total, message)
            retry_rounds       : 首轮结束后，对失败项自动补采的轮数（默认 1 轮）
            retry_wait         : 每轮补采前的等待秒数（给网络/源站恢复时间）
            only_urls          : 只处理这些 URL（用于“重试上次失败图片”，None = 全部）
            image_dir          : 复用已有图片目录（重试时传入上次的目录，已下载的自动跳过）
            new_csv_tag        : 输出 CSV 的文件名标签，默认 imageOK，重试时用 retryOK
            max_attempts       : 单张图片的首轮最大尝试次数（默认 3）
        """
        # --- 基础配置 ---
        self.csv_file = csv_file
        self.wp_site = wp_site.rstrip('/') + '/'      # 归一化，确保以 "/" 结尾
        self.download_workers = download_workers
        self.log_callback = log_callback              # 可能为 None，则用 print 兜底
        self.progress_callback = progress_callback
        self.retry_rounds = max(0, int(retry_rounds))
        self.retry_wait = max(0, int(retry_wait))
        self.only_urls = set(only_urls) if only_urls else None
        self.image_dir = image_dir                    # 为空则由 setup_directories 自动生成
        self.new_csv_tag = new_csv_tag
        self.max_attempts = max(1, int(max_attempts))

        # --- 运行期状态（初始化为空） ---
        self.new_csv_path = None    # 处理后的新 CSV 路径
        self.failed_txt = None      # 下载失败 URL 清单文件
        self.failed_sku_txt = None  # 下载失败图片所属商品的 SKU 清单文件
        self.wp_upload_path = None  # WordPress 上传路径（形如 site/wp-content/uploads/yyyy/mm/）
        self.df = None              # pandas DataFrame（CSV 数据）

        # --- 数据容器 ---
        self.all_urls = []     # 去重后的全部图片 URL 列表
        self.local_map = {}    # url -> 本地保存路径
        self.wp_url_map = {}   # url -> WordPress 上传路径
        self.failed_urls = []  # 最终下载失败的 URL

        # --- 线程锁：多线程下保护共享字典 ---
        self.lock = threading.Lock()

    # ---------------------------------------------------------------
    # 工具方法：日志 / 进度转发
    # ---------------------------------------------------------------
    def log(self, message):
        """输出一条日志：优先走回调，无回调则打印到控制台。"""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def update_progress(self, current, total, message=''):
        """转发进度信息给回调（GUI 用它刷新进度条）。"""
        if self.progress_callback:
            self.progress_callback(current, total, message)

    # ---------------------------------------------------------------
    # 工具方法：生成安全唯一的本地文件名
    # ---------------------------------------------------------------
    def get_safe_filename(self, url):
        """根据 URL 生成唯一、统一为 .jpg 的本地文件名。

        规则：
            1. 以 URL 的 MD5 作为主名，保证同一 URL 永远映射到同一文件（幂等、可断点续传）
            2. 扩展名统一为 .jpg：所有图片下载后都会转成 JPEG 再保存，
               因此文件链接也统一以 .jpg 结尾
        """
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()  # URL 哈希
        return f"{url_hash}.jpg"

    # ---------------------------------------------------------------
    # 工具方法：把任意图片字节转换为 JPEG（非 jpg 格式统一转 jpg）
    # ---------------------------------------------------------------
    def to_jpeg_bytes(self, raw_bytes):
        """把下载到的图片字节转换为 JPEG 字节，返回 (jpeg_bytes, 是否发生转换)。

        规则：
            1. 已是 JPEG/JPG 且为 RGB/L 模式 → 原样返回（不重编码，避免质量损失）
            2. PNG / WebP / GIF 等其它格式 → 转为 JPEG；透明通道用白底合成
            3. 调色板 P 模式、CMYK 等 → 统一转 RGB 后编码
            4. 转换失败（内容不是有效图片）→ 返回 None，由调用方决定处理
        """
        if Image is None:
            return raw_bytes, False  # 无 Pillow 时降级：原样保存，不做转换
        try:
            img = Image.open(BytesIO(raw_bytes))
            fmt = (img.format or '').upper()
            if fmt in ('JPEG', 'JPG') and img.mode in ('RGB', 'L'):
                return raw_bytes, False
            img.load()
            if img.mode in ('RGBA', 'LA', 'P'):
                # 透明 / 调色板图：转 RGBA 后贴到白底，避免透明变黑
                rgba = img.convert('RGBA')
                background = Image.new('RGB', rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel('A'))
                img = background
            else:
                img = img.convert('RGB')
            output = BytesIO()
            img.save(output, format='JPEG', quality=90)
            return output.getvalue(), True
        except Exception:
            return None, False

    # ---------------------------------------------------------------
    # 流程一：创建下载目录与输出路径
    # ---------------------------------------------------------------
    def setup_directories(self):
        """根据当前日期和 CSV 所在目录，创建图片目录并生成各类输出路径。"""
        current_date = datetime.now()
        # 形如 "2026/10"
        year_month = f"{current_date.year}/{current_date.month:02d}"
        # WordPress 上传路径格式：site/wp-content/uploads/yyyy/mm/
        self.wp_upload_path = f"{self.wp_site}wp-content/uploads/{year_month}/"

        # CSV 所在目录 与 CSV 基名（不含扩展名）
        csv_dir = os.path.dirname(self.csv_file)
        base_name = os.path.splitext(os.path.basename(self.csv_file))[0]

        # 图片目录：默认 csv目录/<基名>-images；重试时复用上次的目录，已下载的文件自动跳过
        if not self.image_dir:
            self.image_dir = os.path.join(csv_dir, f"{base_name}-images")
        os.makedirs(self.image_dir, exist_ok=True)   # exist_ok=True 可重复创建

        # 输出路径：新 CSV、失败清单
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.new_csv_path = os.path.join(
            csv_dir, f"{base_name}-{self.new_csv_tag}-{timestamp}.csv")
        self.failed_txt = os.path.join(self.image_dir, 'failed_images.txt')
        self.failed_sku_txt = os.path.join(self.image_dir, 'failed_skus.txt')

        self.log(f"图片目录: {self.image_dir}")
        self.log(f"图片URL路径格式: {self.wp_upload_path}")

    # ---------------------------------------------------------------
    # 流程二：读取 CSV
    # ---------------------------------------------------------------
    def read_csv(self):
        """读取 CSV，按字符串类型解析，空值填充为空串，并校验存在 'Images' 列。"""
        self.log('开始读取 CSV...')
        # dtype=str 防止数字被自动转换；encoding=utf-8-sig 兼容带 BOM 的文件
        self.df = pd.read_csv(self.csv_file, dtype=str, encoding='utf-8-sig').fillna('')
        self.log(f"CSV 行数: {len(self.df)}")

        # 校验必须存在 Images 列，否则报错终止
        if 'Images' not in self.df.columns:
            raise Exception(f"CSV 中不存在 Images 列，现有列: {self.df.columns.tolist()}")

    # ---------------------------------------------------------------
    # 流程三：提取并去重所有图片 URL
    # ---------------------------------------------------------------
    def extract_urls(self):
        """遍历 CSV 的 Images 列，按逗号切分、过滤 http 开头的链接，并去重。"""
        self.log('开始提取图片链接...')
        self.all_urls = []

        # 每一行 Images 可能包含多个 URL（用逗号分隔）
        for imgs in self.df['Images']:
            if not imgs:                      # 跳过空单元格
                continue
            parts = re.split(r'\s*,\s*', imgs)   # 按逗号（允许空格）切分
            for url in parts:
                url = url.strip()             # 去除首尾空白
                if url.startswith('http'):    # 仅收录 http/https 链接
                    self.all_urls.append(url)

        # dict.fromkeys 用于去重，保留首次出现顺序
        self.all_urls = list(dict.fromkeys(self.all_urls))

        # 仅重试模式下，只保留上次失败的 URL
        if self.only_urls is not None:
            before = len(self.all_urls)
            self.all_urls = [u for u in self.all_urls if u in self.only_urls]
            self.log(f"重试模式：待重试 {len(self.all_urls)} 张（CSV 中共 {before} 张）")

        self.log(f"提取到图片数量: {len(self.all_urls)}")

    # ---------------------------------------------------------------
    # 流程四：下载单张图片（含重试）
    # ---------------------------------------------------------------
    def download_image(self, index, total, url):
        """下载单张图片，最多重试 3 次；返回是否成功。

        参数:
            index : 当前序号（用于进度/日志显示）
            total : 总数量
            url   : 图片地址
        """
        # --- 计算本地路径与 WordPress 路径 ---
        filename = self.get_safe_filename(url)
        save_path = os.path.join(self.image_dir, filename)
        wp_image_url = self.wp_upload_path + filename

        # --- 本地路径始终记录；WP 映射要等图片真正落盘后才写入 ---
        with self.lock:
            self.local_map[url] = save_path

        # --- 若文件已存在，跳过下载，直接视为成功 ---
        if os.path.exists(save_path):
            with self.lock:
                self.wp_url_map[url] = wp_image_url
            self.log(f"[{index}/{total}] 已存在: {filename}")
            self.update_progress(index, total, f"已存在: {filename}")
            return True

        # --- 循环重试下载：瞬时错误退避重试，永久错误（404 等）直接放弃 ---
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1:
                wait = 2 * (attempt - 1)          # 退避：2s、4s、6s…而不是固定等 2 秒
                time.sleep(wait)
            try:
                self.log(f"[{index}/{total}] 下载: {url}（第 {attempt}/{self.max_attempts} 次）")
                # 请求（非流式，一次性读入内存以便格式转换），伪装 UA，60 秒超时
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'},
                                 timeout=60)

                if r.status_code == 200:
                    raw = r.content
                    # 统一转 JPEG：png/webp/gif 等格式转成真正的 jpg 字节
                    jpg_bytes, converted = self.to_jpeg_bytes(raw)
                    if jpg_bytes is None:
                        # 内容不是有效图片（防盗链页面/错误页），重试也无意义
                        self.log(f"[{index}/{total}] 内容非有效图片，放弃: {url}")
                        break
                    with open(save_path, 'wb') as f:
                        f.write(jpg_bytes)
                    # 只有文件确实写入成功才登记 WP 路径；
                    # 失败时 CSV 保留原始链接，避免生成指向空文件的死链
                    with self.lock:
                        self.wp_url_map[url] = wp_image_url
                    if converted:
                        self.log(f"[{index}/{total}] 已转 jpg: {filename}")
                    else:
                        self.log(f"[{index}/{total}] 下载成功: {filename}")
                    self.update_progress(index, total, f"成功: {filename}")
                    return True

                # 只在临时性错误上重试，避免对 404/403 白白重试三次
                if r.status_code in self.RETRYABLE_STATUS:
                    self.log(f"[{index}/{total}] 临时错误 {r.status_code}，稍后重试")
                else:
                    self.log(f"[{index}/{total}] 状态码 {r.status_code}（不可重试），放弃")
                    break
            except Exception as e:
                # 超时、连接重置、DNS 失败等网络问题 → 值得继续重试
                self.log(f"[{index}/{total}] 网络异常: {e}")

        # --- 本轮用尽仍未成功：先记入失败清单，后面还会补采/手动重试 ---
        with self.lock:
            self.failed_urls.append(url)
        self.log(f"[{index}/{total}] 本轮失败，已记入待重试清单")
        self.update_progress(index, total, f"失败: {filename}")
        return False

    # ---------------------------------------------------------------
    # 流程五：多线程下载全部图片
    # ---------------------------------------------------------------
    def _download_batch(self, urls):
        """下载一批 URL，返回 (成功数, 失败数)。"""
        total = len(urls)
        success_count = 0
        fail_count = 0

        with ThreadPoolExecutor(max_workers=self.download_workers) as executor:
            # 注意：as_completed 必须传 future 对象集合，不能传整个 dict
            # （原程序传了 dict，遍历到字符串键会报错）
            futures = [executor.submit(self.download_image, index, total, url)
                       for index, url in enumerate(urls, 1)]
            for future in as_completed(futures):
                if future.result():
                    success_count += 1
                else:
                    fail_count += 1
        return success_count, fail_count

    def download_all_images(self):
        """多线程下载全部图片；首轮结束后对失败项自动补采 retry_rounds 轮。"""
        self.log('开始多线程下载图片...')
        success_count, fail_count = self._download_batch(self.all_urls)
        self.log(f"首轮完成 - 成功: {success_count}, 失败: {fail_count}")

        # --- 自动补采：很多失败只是瞬时网络抖动/源站限流，隔几秒往往能拿到 ---
        for round_no in range(1, self.retry_rounds + 1):
            if not self.failed_urls:
                break
            pending = list(self.failed_urls)      # 本轮要补采的 URL
            self.failed_urls = []                 # 清空，只保留补采后仍失败的
            if self.retry_wait:
                self.log(f"\n补采第 {round_no}/{self.retry_rounds} 轮：{len(pending)} 张，"
                         f"等待 {self.retry_wait} 秒...")
                time.sleep(self.retry_wait)
            else:
                self.log(f"\n补采第 {round_no}/{self.retry_rounds} 轮：{len(pending)} 张")

            ok, bad = self._download_batch(pending)
            success_count += ok
            fail_count = bad
            self.log(f"补采第 {round_no} 轮完成 - 成功: {ok}, 仍失败: {bad}")

        self.log(f"\n下载完成 - 成功: {success_count}, 失败: {fail_count}")

    # ---------------------------------------------------------------
    # 流程六：保存下载失败的 URL 清单
    # ---------------------------------------------------------------
    def save_failed_urls(self):
        """把失败的 URL 写入 failed_images.txt（每行一个）。"""
        if self.failed_urls:
            with open(self.failed_txt, 'w', encoding='utf-8') as f:
                for url in self.failed_urls:
                    f.write(url + '\n')
            self.log(f"失败图片数量: {len(self.failed_urls)}，已保存到: {self.failed_txt}")
        else:
            self.log('所有图片下载成功')

    # ---------------------------------------------------------------
    # 流程六之二：保存下载失败图片对应的商品 SKU 清单
    # ---------------------------------------------------------------
    def save_failed_skus(self):
        """把“有图片下载失败”的商品 SKU 写入 failed_skus.txt（每行一个）。

        规则：
            1. 变体行（Type=variation）的图片属于整个商品，取 Parent 作为商品 SKU；
               主商品行取本行 SKU。
            2. 同一商品多张图失败、或同一个 URL 出现在多行，只输出一次（保序去重）。
            3. CSV 没有 SKU 列时跳过，仅提示，不影响主流程。
        """
        if not self.failed_urls:
            self.log('没有失败图片，无需生成 SKU 清单')
            return

        if 'SKU' not in self.df.columns:
            self.log('CSV 中不存在 SKU 列，跳过失败 SKU 清单生成')
            return

        failed_set = set(self.failed_urls)
        skus = []

        for _, row in self.df.iterrows():
            imgs = row.get('Images', '')
            if not imgs:
                continue
            # 该行只要有一张图最终失败，整行对应的商品就算失败
            urls = [u.strip() for u in re.split(r'\s*,\s*', imgs)]
            if not any(u in failed_set for u in urls):
                continue

            # 变体行取父商品 SKU；主商品行取自身 SKU
            sku = str(row.get('Parent', '') or '').strip()
            if not sku:
                sku = str(row.get('SKU', '') or '').strip()
            if sku:
                skus.append(sku)

        skus = list(dict.fromkeys(skus))   # 去重但保留首次出现顺序
        with open(self.failed_sku_txt, 'w', encoding='utf-8-sig') as f:
            for sku in skus:
                f.write(sku + '\n')

        self.log(f"失败商品 SKU 数量: {len(skus)}，已保存到: {self.failed_sku_txt}")

    # ---------------------------------------------------------------
    # 流程七：替换 CSV 中的图片链接为 WordPress 路径
    # ---------------------------------------------------------------
    def replace_csv_links(self):
        """遍历 Images 列，把每个成功下载的 URL 替换成对应的 WordPress 上传路径。"""
        self.log('开始替换 CSV 图片链接...')
        new_images = []

        for imgs in self.df['Images']:
            if not imgs:                       # 空单元格保持为空
                new_images.append('')
                continue

            parts = re.split(r'\s*,\s*', imgs)  # 切分多图
            new_part_list = []
            for url in parts:
                url = url.strip()
                if not url:
                    continue
                if url in self.wp_url_map:      # 下载成功 → 替换为 wp 路径
                    new_part_list.append(self.wp_url_map[url])
                else:                           # 未下载成功 → 保留原链接
                    new_part_list.append(url)
            new_images.append(', '.join(new_part_list))

        # 用替换后的列表覆盖原 Images 列
        self.df['Images'] = new_images

    # ---------------------------------------------------------------
    # 流程八：保存处理后的新 CSV
    # ---------------------------------------------------------------
    def save_new_csv(self):
        """把替换后的 DataFrame 写入新 CSV（utf-8-sig，不写索引）。"""
        self.log('开始保存新 CSV...')
        self.df.to_csv(self.new_csv_path, index=False, encoding='utf-8-sig')
        self.log(f"新 CSV 文件: {self.new_csv_path}")

    # ---------------------------------------------------------------
    # 主流程入口：串联全部步骤
    # ---------------------------------------------------------------
    def run(self):
        """按顺序执行完整下载流程，整体异常捕获后返回布尔结果。"""
        try:
            self.setup_directories()   # 1. 建目录
            self.read_csv()            # 2. 读 CSV
            self.extract_urls()        # 3. 提取 URL

            # 没有图片链接则提前结束
            if len(self.all_urls) == 0:
                self.log('没有发现图片链接')
                return True

            self.download_all_images()  # 4. 多线程下载
            self.save_failed_urls()     # 5. 保存失败清单
            self.save_failed_skus()     # 5.1 保存失败商品 SKU 清单
            self.replace_csv_links()    # 6. 替换链接
            self.save_new_csv()         # 7. 保存新 CSV
            return True

        except Exception as e:
            self.log(f"错误: {str(e)}")
            return False


# =====================================================================
# 类二：ImageDownloaderGUI —— tkinter 图形界面
# =====================================================================
class ImageDownloaderGUI:
    """
    WordPress 图片下载工具的图形界面。
    通过回调把 ImageDownloader 的日志与进度展示到界面；
    下载在后台线程执行，避免阻塞界面。
    """

    # ---------------------------------------------------------------
    # 构造方法：创建主窗口并初始化界面
    # ---------------------------------------------------------------
    def __init__(self):
        """创建主窗口、主题样式与初始状态，并构建界面布局。"""
        # --- 主窗口 ---
        self.root = tk.Tk()
        self.root.title('WordPress 图片下载工具')
        self.root.geometry('850x700')
        self.root.resizable(True, True)

        # --- 界面主题 ---
        style = ttk.Style()
        style.theme_use('clam')

        # --- 运行状态 ---
        self.downloader = None        # 当前的 ImageDownloader 实例
        self.download_thread = None   # 后台下载线程
        self.is_downloading = False   # 是否正在下载（防止重复点击）

        self.setup_ui()   # 构建界面

    # ---------------------------------------------------------------
    # 界面布局
    # ---------------------------------------------------------------
    def setup_ui(self):
        """搭建整个窗口：CSV选择、WP地址、线程数、进度、日志、开始按钮。"""
        # --- 主容器（带边距） ---
        main_frame = ttk.Frame(self.root, padding='10')
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)   # 允许伸缩
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # ===== 区域 1：CSV 文件选择 =====
        csv_frame = ttk.LabelFrame(main_frame, text='CSV 文件', padding='10')
        csv_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        csv_frame.columnconfigure(1, weight=1)

        self.csv_path = tk.StringVar()   # 已选文件路径
        ttk.Entry(csv_frame, textvariable=self.csv_path, state='readonly').grid(
            row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 10))
        ttk.Button(csv_frame, text='选择文件', command=self.select_csv_file).grid(row=0, column=1)

        # ===== 区域 2：WordPress 站点地址 =====
        wp_frame = ttk.LabelFrame(main_frame, text='WordPress 地址', padding='10')
        wp_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        wp_frame.columnconfigure(1, weight=1)

        ttk.Label(wp_frame, text='网址:').grid(row=0, column=0, padx=(0, 10))
        self.wp_site = tk.StringVar(value='https://willowyns.com/')  # 默认站点
        wp_entry = ttk.Entry(wp_frame, textvariable=self.wp_site)
        wp_entry.grid(row=0, column=1, sticky=(tk.W, tk.E))
        # ===== 区域 3：下载设置（并发线程数） =====
        thread_frame = ttk.LabelFrame(main_frame, text='下载设置', padding='10')
        thread_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Label(thread_frame, text='并发下载线程数:').grid(row=0, column=0, padx=(0, 10))
        self.workers = tk.IntVar(value=20)   # 默认 20 线程
        workers_spinbox = ttk.Spinbox(thread_frame, from_=1, to=50,
                                      textvariable=self.workers, width=10)
        workers_spinbox.grid(row=0, column=1, sticky=tk.W)
        ttk.Label(thread_frame, text='(1-50，建议 10-30)', foreground='gray').grid(
            row=0, column=2, padx=(10, 0))

        # ===== 区域 4：下载进度条 =====
        progress_frame = ttk.LabelFrame(main_frame, text='下载进度', padding='10')
        progress_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_var = tk.IntVar()
        self.progress_bar = Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E))
        self.progress_label = ttk.Label(progress_frame, text='等待开始...')
        self.progress_label.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))

        # ===== 区域 5：运行日志 =====
        log_frame = ttk.LabelFrame(main_frame, text='运行日志', padding='10')
        log_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # ===== 区域 6：开始下载按钮 =====
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, sticky=(tk.W, tk.E))
        self.start_button = ttk.Button(button_frame, text='开始下载', command=self.start_download)
        self.start_button.pack(side=tk.LEFT)

        # 日志区域可纵向拉伸，其余区域固定
        main_frame.rowconfigure(4, weight=1)

    # ---------------------------------------------------------------
    # 事件处理：选择 CSV 文件
    # ---------------------------------------------------------------
    def select_csv_file(self):
        """弹出文件选择框，把选中的 CSV 路径填入输入框并记录日志。

        若文件名中包含域名（如 wp-slatetide.com男装_...csv → slatetide.com），
        会自动组合成 https://<域名>/ 填入 WordPress 地址框。
        """
        filename = filedialog.askopenfilename(
            title='选择 CSV 文件',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')])
        if filename:
            self.csv_path.set(filename)
            self.log(f"已选择文件: {filename}")

            # 从文件名中提取主域名（如 slatetide.com），自动填入 WordPress 地址
            base = os.path.basename(filename)
            # 匹配 "字母数字.顶级域[.多级域]"，自动跳过 wp- 之类前缀
            m = re.search(r'([a-zA-Z0-9]+(\.[a-zA-Z]{2,})+)', base)
            if m:
                domain = m.group(1)
                self.wp_site.set(f"https://{domain}/")
                self.log(f"已从文件名识别域名: {domain}，自动填入地址 https://{domain}/")

    # ---------------------------------------------------------------
    # 界面刷新：写日志 / 更新进度条
    # ---------------------------------------------------------------
    def log(self, message):
        """在日志框追加一行带时间戳的文本，并滚动到底部、刷新界面。"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)          # 自动滚动到末尾
        self.root.update_idletasks()       # 立即刷新界面

    def update_progress(self, current, total, message=''):
        """更新进度条百分比与文字标签（由后台线程回调调用）。"""
        if total > 0:
            percent = int(current / total * 100)
            self.progress_var.set(percent)
            self.progress_label.config(text=f"{message} ({current}/{total})")
        self.root.update_idletasks()

    # ---------------------------------------------------------------
    # 事件处理：开始下载（含输入校验）
    # ---------------------------------------------------------------
    def start_download(self):
        """校验输入 → 创建下载器 → 启动后台线程开始下载。"""
        # --- 防止重复启动 ---
        if self.is_downloading:
            messagebox.showwarning('提示', '下载任务正在进行中，请等待完成')
            return

        # --- 校验 CSV 文件 ---
        csv_file = self.csv_path.get().strip()
        if not csv_file:
            messagebox.showerror('错误', '请先选择 CSV 文件')
            return
        if not os.path.exists(csv_file):
            messagebox.showerror('错误', 'CSV 文件不存在')
            return

        # --- 校验 WordPress 地址 ---
        wp_site = self.wp_site.get().strip()
        if not wp_site:
            messagebox.showerror('错误', '请输入 WordPress 地址')
            return
        if not wp_site.startswith('https://'):
            messagebox.showerror('错误', 'WordPress 地址必须以 https:// 开头')
            return

        # --- 校验线程数 ---
        workers = self.workers.get()
        if workers < 1 or workers > 50:
            messagebox.showerror('错误', '线程数必须在 1-50 之间')
            return

        # --- 清理界面并输出开始信息 ---
        self.log_text.delete(1.0, tk.END)
        self.progress_var.set(0)
        self.progress_label.config(text='下载中...')

        self.log('==================================================')
        self.log('开始下载任务')
        self.log(f"CSV 文件: {csv_file}")
        self.log(f"WordPress 地址: {wp_site}")
        self.log(f"下载线程数: {workers}")
        self.log('==================================================')

        # --- 禁用按钮，标记正在下载 ---
        self.start_button.config(state=tk.DISABLED)
        self.is_downloading = True

        # --- 创建下载器并启动后台线程 ---
        self.downloader = ImageDownloader(
            csv_file=csv_file,
            wp_site=wp_site,
            download_workers=workers,
            log_callback=self.log,
            progress_callback=self.update_progress)

        self.download_thread = threading.Thread(target=self.download_worker)
        self.download_thread.daemon = True   # 守护线程，主窗口关闭即退出
        self.download_thread.start()

    # ---------------------------------------------------------------
    # 后台线程：执行下载并在主线程回调结果
    # ---------------------------------------------------------------
    def download_worker(self):
        """后台线程执行体：运行下载器，通过 root.after 回到主线程更新界面。"""
        try:
            success = self.downloader.run()
            self.root.after(0, self.download_finished, success)   # 回到主线程
            return None
        except Exception as e:
            self.root.after(0, self.download_finished, False, str(e))
            return None

    # ---------------------------------------------------------------
    # 界面刷新：下载结束处理
    # ---------------------------------------------------------------
    def download_finished(self, success, error_msg=None):
        """下载结束：恢复按钮、输出结果、询问是否打开图片目录。"""
        self.is_downloading = False
        self.start_button.config(state=tk.NORMAL)

        if success:
            self.log('==================================================')
            self.log('✓ 下载任务完成！')
            self.log(f"新 CSV 文件: {self.downloader.new_csv_path}")
            self.log(f"图片目录: {self.downloader.image_dir}")
            if self.downloader.failed_urls:
                self.log(f"失败图片列表: {self.downloader.failed_txt}")
                self.log(f"失败商品 SKU 清单: {self.downloader.failed_sku_txt}")
            self.progress_label.config(text='下载完成！')

            # 询问是否打开图片目录
            result = messagebox.askyesno(
                '完成',
                f"图片处理完成！\n\n新 CSV 文件: {self.downloader.new_csv_path}"
                f"\n图片目录: {self.downloader.image_dir}"
                + (f"\n失败图片: {self.downloader.failed_txt}"
                   f"\n失败商品 SKU: {self.downloader.failed_sku_txt}"
                   if self.downloader.failed_urls else '')
                + "\n\n是否打开图片目录？")
            if result:
                os.startfile(self.downloader.image_dir)   # 系统打开目录
            return
        else:
            self.log(f"✗ 下载任务失败: {error_msg or '未知错误'}")
            self.progress_label.config(text='下载失败')
            messagebox.showerror('错误', f"下载失败: {error_msg or '未知错误'}")
            return

    # ---------------------------------------------------------------
    # 界面入口：进入主事件循环
    # ---------------------------------------------------------------
    def run(self):
        """启动 tkinter 主事件循环。"""
        self.root.mainloop()


# =====================================================================
# 程序入口
# =====================================================================
if __name__ == '__main__':
    app = ImageDownloaderGUI()   # 创建界面
    app.run()                    # 启动主循环
