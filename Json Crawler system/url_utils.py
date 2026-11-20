"""兼容旧 import：阶段模块仍写 from url_utils import normalize_url_dashes。"""
# worker.py 会把项目根目录插进 sys.path，所以阶段脚本 import 裸名 url_utils 时命中的是本文件，
# 本文件再把实现转给 app.url_utils；改逻辑请改 app/ 那份，这里只做转发。
from app.url_utils import normalize_request_url, normalize_url_dashes

__all__ = ['normalize_url_dashes', 'normalize_request_url']
