"""跨阶段共用工具。"""
# common 提供与业务无关的基础设施：步骤加载（step_loader）、原子落盘（atomic_io）、
# 停止检查（stop）。阶段脚本通过 worker 加进 sys.path 的项目根目录 import 它们。
