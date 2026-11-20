"""本机 user_settings.json。"""
# 保存上次项目与功能开关，丢失后使用默认设置。
import json
from pathlib import Path

# 项目目录（本文件在 app/ 下，parents[1] 即上一级），设置文件与程序同级，整目录可随意搬动
ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / 'user_settings.json'


def load_user_settings():
    # 读取本机设置：任何异常（首次运行没文件、编码坏了、手改出错）都当作「没有设置」，
    # 绝不能让 GUI 启动阶段因为一个配置文件报错就崩掉。
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data          # 顶层不是字典（列表/字符串）时视为无效，走下面的空默认
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_user_settings(data):
    # 落盘失败（只读介质、目录无写权限）静默忽略：本机设置非关键数据，不值得打断用户操作
    try:
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:
        pass
