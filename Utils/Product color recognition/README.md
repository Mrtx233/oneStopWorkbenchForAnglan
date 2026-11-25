# 商品颜色识别与复核

使用 Python 3.10+，安装 Pillow（仓库根目录的 `requirements.txt` 已包含）。以下命令从仓库根目录运行；`python` 应是已安装 Pillow 的可用解释器。

```powershell
python -m pip install "Pillow>=9.1"
python "Utils/Product color recognition/download_images.py" "D:/data/products.json"
python "Utils/Product color recognition/color_matcher.py" "D:/data/products.json"
```

也可以不带参数启动两个入口，按提示粘贴路径；支持资源管理器复制的带引号路径。下载器不再假定脚本旁存在某个特定网站的 JSON。

- 图片默认保存在 JSON 旁的 `images/<md5>/000.jpg`、`001.png` 等文件中，编号始终对应**原始 JSON 的 images 索引**。两个入口都接受第二个位置参数指定图片根目录。
- 下载器依据 `options` 中实际的颜色选项数量判断单色/多色，兼容 `Color`、`Colour`、`颜色` 等维度名，不依赖 `option_counts`。单色空链接会补为第一张图片 URL，并以原子替换方式写回输入 JSON；已有链接保持原样。
- 多色商品要求有效且不冲突的 `md5`。发现无效数据会在改写输入 JSON 前退出。
- 仅完整可读且编号唯一的图片可跳过下载。失败结果记录在 `failed.txt`；重跑会更新失败列表，`manifest.csv` 同时包含已验证的缓存图片和本次成功下载的图片。
- 识别平台使用本地颜色规则，不调用远程 AI 服务。自动成功结果直接进入输出 JSON，仍建议人工确认；未知颜色和不确定结果留待人工处理。
- 平台默认另存 `<原文件名>_manual_labeled.json` 和对应的 `_progress.json`。续标时继续打开**原始输入 JSON**，并保留进度文件；不要用已删除部分 images 的结果文件替代原始输入。

## 复核界面

界面保存在 `ui/index.html`，由 Python 入口直接读取，无需 Node、Vue 构建或联网加载资源。移动或打包工具时请保留整个目录（包括 `ui`）。更新界面后，重启平台并刷新浏览器即可生效。

保留深色黑金三栏布局：左侧筛选商品，中间查看编号拼图，右侧选择颜色并确认或调整。金色用于当前选择，蓝框表示自动识别，绿框表示人工确认，金色虚框表示候选。窄屏按顺序排列各区域；图片区可横向滚动，避免将五列拼图缩成难以辨认的缩略图。所有修改仍自动保存，也可点击“保存 JSON”。

颜色卡片、图片标记和选色提示附带常见英文颜色的中文译名，例如 `Beige → 米色`、`Sage Green → 鼠尾草绿`。翻译离线完成，支持常见别名、组合色及条纹等修饰；未收录名称保留原文，已有中文不重复显示。译名仅供界面对照，不会修改 JSON 中的原始颜色键名或改变识别规则。

视觉整理参考 [unslop](https://github.com/heydamir/unslop)，作者 Damir Sokolovsky（@heydamir），按 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 署名使用。适配内容包括间距、字级、按钮层次、响应式布局和键盘焦点，未引入运行时依赖。
