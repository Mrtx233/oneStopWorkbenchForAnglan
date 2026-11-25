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
