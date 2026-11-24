"""工作台路径选择与参数快照。"""
import os
from pathlib import Path
import subprocess
import sys
from tkinter import filedialog, messagebox

from app.constants import PROXY_SERVER
from app.project_paths import REPO
from app.user_settings import save_user_settings
from common.step_loader import load_step


def _parse_skip_images(text):
    # 把跳图输入串（如 "2,3, -1"）解析成整数位置列表，供阶段 02 按下标丢图。
    # 空串 -> []（不跳图）；非法 token 或 0 位置直接抛错给 start() 的异常处理弹窗。
    text = (text or '').strip()
    if not text:
        return []
    positions = []
    # 兼容中文逗号：先归一成英文逗号再切分，逐段去空白。
    for part in text.replace('，', ',').split(','):
        token = part.strip()
        if not token:
            continue
        # 负号 + 纯数字 = 倒数位置（-1 表示最后一张）；纯数字 = 正数位置（1 表示第一张）。
        if token.startswith('-') and token[1:].isdecimal():
            value = -int(token[1:])
        elif token.isdecimal():
            value = int(token)
        else:
            raise ValueError(f'跳图位置必须是整数，例如 2,3 或 -1,-2：{token}')
        # 0 既非正序也非倒序下标，属误输入。
        if value == 0:
            raise ValueError('跳图位置不能为 0，第一张用 1，最后一张用 -1')
        positions.append(value)
    return positions


class CrawlerDialogs:
    def show(self, index):
        # 只映射当前页，键盘 Tab 不会进入被隐藏的页面。
        if self.current != index:
            self.panels[self.current].grid_remove()
        self.current = index
        panel = self.panels[index]
        if not panel.winfo_manager():
            panel.grid(row=0, column=0, sticky='nsew')
        for i, button in self.nav.items():
            button.set_selected(i == index)
        # 进入商品页(2)时自动刷新域名文件列表，省去手点「刷新列表」。
        if index == 2:
            self.refresh_files()
        elif index == 5:
            self.refresh_wp_csv()

    def refresh_wp_csv(self, force_latest=False):
        project = Path(self.project.get()).expanduser()
        candidates = []
        for folder in (project / '价格匹配', project / '原价', project):
            if folder.is_dir():
                candidates.extend(path for path in folder.glob('wp-*.csv')
                                  if path.is_file() and '-imageOK-' not in path.stem)
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            if not self.image_csv.get().strip():
                self.status.set('未找到 WP 导出 CSV；可手动选择文件')
            return
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        selected = Path(self.image_csv.get()).expanduser() if self.image_csv.get().strip() else None
        if force_latest or selected is None or not selected.is_file():
            self.image_csv.set(str(latest.resolve()))
        self.status.set(f'找到 {len(candidates)} 个 WP 导出文件，最新：{latest.name}')

    def browse_image_csv(self):
        path = filedialog.askopenfilename(
            initialdir=self.project.get(), filetypes=[('WP CSV', 'wp-*.csv'), ('CSV', '*.csv')],
        )
        if path:
            self.image_csv.set(path)

    def refresh_paths(self):
        # 参数一变就清空可能过期的预览与统计，避免用户误读上一轮结果。
        self.preview.delete(*self.preview.get_children())
        self._sync_preview_hint()
        self.stats.set('')

    def on_setting_changed(self):
        # 变量写监听的回调：始终刷预览；若正忙且已有本轮快照，追加「已改，下轮生效」提示。
        self.refresh_paths()
        if self.busy and self.active_settings:
            self.lock_text.set(self._lock_summary(self.active_settings) + '  ·  已改，下轮生效')

    def refresh_files(self):
        # 重建商品页列表：列出 <项目>/Json 下的域名链接 CSV（旧版 .json 在无同名 CSV 时也列出）。
        self.product_files.delete(0, 'end')
        folder = Path(self.project.get()) / 'Json'
        if not folder.is_dir():
            self._sync_file_hint()
            return
        for path in sorted(folder.iterdir()):
            # 过滤掉索引文件与恢复中间态，只留真正可作为采集目标的域名文件。
            if path.suffix.lower() not in ('.csv', '.json') or not path.is_file():
                continue
            if path.name in ('links_index.csv', 'links_index.json') or '.recovery-' in path.name:
                continue
            if path.suffix.lower() == '.json' and (folder / (path.stem + '.csv')).exists():
                continue
            self.product_files.insert('end', path.name)
        self._sync_file_hint()

    def browse_project(self):
        # 选项目目录：initialdir 优先当前输入，空则回仓库根 REPO；用户取消(空串)时不改值。
        path = filedialog.askdirectory(initialdir=self.project.get() or str(REPO))
        if path:
            self.project.set(path)

    def browse_price_dir(self):
        # 阶段 04 输入目录：选中的目录路径写入 price_input（留空则由下游走默认 CSV 目录）。
        path = filedialog.askdirectory(initialdir=self.project.get())
        if path:
            self.price_input.set(path)

    def browse_price_file(self):
        # 阶段 04 单个 CSV 输入：filetypes 过滤只让选 .csv。
        path = filedialog.askopenfilename(initialdir=self.project.get(), filetypes=[('CSV', '*.csv')])
        if path:
            self.price_input.set(path)

    def open_folder(self, path):
        # 用系统文件管理器打开目录：先校验存在（不存在提示「尚未生成」），再按平台分发。
        folder = Path(path)
        if not folder.is_dir():
            messagebox.showinfo('提示', '目录尚未生成')
            return
        folder = str(folder.resolve())  # resolve 成绝对路径，避免相对路径打不开
        try:
            if os.name == 'nt':
                os.startfile(folder)                     # Windows
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder])       # macOS
            else:
                subprocess.Popen(['xdg-open', folder])   # Linux 桌面
        except OSError as exc:
            messagebox.showerror('无法打开目录', str(exc))

    def settings(self):
        # 把 UI 变量拍成一份 dict 快照交给 controller/子进程；这里做全部校验，抛错由 start() 弹窗。
        project = self.project.get().strip()
        if not project:
            raise ValueError('请选择项目目录')
        pages = self.pages.get().strip()
        # 页数：留空 = 不限（下游当 0）；填了必须是 >=1 的正整数。
        if pages and (not pages.isdecimal() or int(pages) < 1):
            raise ValueError('每分类最大页数必须为正整数，或留空')
        option_limits = {}
        value = self.option_limits['Color'].get().strip()
        if value:
            # Color 上限同理：留空表示颜色不限，不写入 dict。
            if not value.isdecimal() or int(value) < 1:
                raise ValueError('Color 上限必须为正整数，或留空')
            option_limits['Color'] = int(value)
        gallery_limit_text = self.gallery_image_limit.get().strip()
        if gallery_limit_text and not gallery_limit_text.isdecimal():
            raise ValueError('无颜色补图数必须是 0 或更大的整数')
        gallery_image_limit = int(gallery_limit_text) if gallery_limit_text else 4
        image_csv = self.image_csv.get().strip()
        image_wp_site = self.image_wp_site.get().strip().rstrip('/')
        image_workers_text = self.image_workers.get().strip()
        # 尺码梯度定价保留价差上限与候选窗口两个参数，交由后端校验。
        pricing = load_step(Path(__file__).resolve().parents[1] /
                            'stages/04_price_export/00_pricing_config.py')
        rules = pricing.resolve_rules(self.price_spread_percent.get().strip(),
                                      self.window_lower.get().strip(),
                                      self.window_upper.get().strip())
        skip_image_positions = _parse_skip_images(self.skip_images.get())
        return {
            'project': str(Path(project).resolve()),               # 统一绝对路径，子进程按此定位项目
            'categories': self.categories.get('1.0', 'end').strip(),  # 分类全文（每行一条）
            'max_pages': int(pages) if pages else 0,               # 0 = 不限页
            'xpath': self.xpath.get().strip(),
            'skip_image_positions': skip_image_positions,          # 阶段 02 跳图位置
            'use_standard_sizes': bool(self.use_standard_sizes.get()),
            'keep_description_images': bool(self.keep_description_images.get()),
            'keep_description_tables': bool(self.keep_description_tables.get()),
            'browser_path': self.browser_path.strip() or None,     # 浏览器路径；空则自动探测
            'include_other_options': bool(self.include_other_options.get()),
            'price_input': self.price_input.get().strip(),         # 阶段 04 输入，空 = 默认目录
            'price_spread_percent': str(rules.spread_percent),
            'window_lower': str(rules.window_lower),               # 阶段 04 候选窗口下界
            'window_upper': str(rules.window_upper),               # 阶段 04 候选窗口上界
            'make_raw_prices': bool(self.make_raw_prices.get()),   # 阶段 04 是否生成原价表
            'match_prices': bool(self.match_prices.get()),         # 阶段 04 是否做价格匹配
            'option_limits': option_limits,                        # 阶段 03 每件颜色上限
            'color_images_only': bool(self.color_images_only.get()),   # 有颜色维度时只保留本块颜色图
            'gallery_image_limit': gallery_image_limit,            # 无 Color 维度时最多补入的相册图数
            'options': [name for name, var in [('Color', self.color), ('Size', self.size)] if var.get()],  # 勾选要写入的维度
            'split_mode': self.split_mode.get(),                  # 切分模式：parts / each
            'split_parts': self.split_parts.get().strip(),        # 均分份数，切分阶段校验
            'split_price_col': self.split_price_col.get().strip(),  # 均分排序价格列（price1/price2，空=原序）
            'split_overwrite': bool(self.split_overwrite.get()),  # 切分是否覆盖同名输出
            'image_csv': image_csv,
            'image_wp_site': image_wp_site,
            'image_workers': image_workers_text,
        }

    def _lock_summary(self, settings):
        # 将本轮参数快照显示在任务栏；空项换成易读的默认值。
        limits = settings.get('option_limits') or {}
        pages = settings.get('max_pages') or '不限'
        proxy = PROXY_SERVER
        skip = settings.get('skip_image_positions') or []
        skip_text = ','.join(str(n) for n in skip) if skip else '不跳'
        # 无 Color 维度时按本轮上限补图；有 Color 维度且勾选开关时只保留颜色图。
        gallery = ('拆色仅色图' if settings.get('color_images_only') else
                   f'无色补{settings.get("gallery_image_limit", 4)}张')
        # flows：本轮阶段 04 实际要跑的流程，两个都没勾时只剩合并与导出。
        flows = '+'.join(name for name, on in (('原价', settings.get('make_raw_prices', False)),
                                               ('匹配', settings.get('match_prices', True))) if on) or '仅导出'
        return (
            f'本轮：页{pages} · {proxy} · '
            f'颜色{limits.get("Color", "不限")} · {gallery} · '
            f'尺码{"标准" if settings.get("use_standard_sizes", False) else "网站原值"} · '
            f'描述图{"保留" if settings.get("keep_description_images", False) else "删除"} · '
            f'表格{"保留" if settings.get("keep_description_tables", False) else "删除"} · '
            f'其他维度{"开" if settings.get("include_other_options", False) else "关"} · '
            f'跳图{skip_text} · 价差{settings.get("price_spread_percent", "30")}% · '
            f'窗口[{settings.get("window_lower", "0.75")}~{settings.get("window_upper", "1.25")}] · '
            f'产出{flows}'
        )

    def persist_settings(self, settings):
        # 启动时保存上次项目与各功能开关，下次启动作默认值。
        save_user_settings({
            'last_project': settings.get('project', ''),
            'use_standard_sizes': settings.get('use_standard_sizes', False),
            'keep_description_images': settings.get('keep_description_images', False),
            'keep_description_tables': settings.get('keep_description_tables', False),
            'include_other_options': settings.get('include_other_options', False),
            'gallery_image_limit': settings.get('gallery_image_limit', 4),
            'browser_path': settings.get('browser_path') or '',
        })
