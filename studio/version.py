# -*- coding: utf-8 -*-
"""
版本号唯一真相源（CalVer 语义混合）。

格式：主.次.修订.构建日期(YYYYMMDD)
  例如 2.1.1.20260709

  · 主.次.修订：语义化版本，手动维护，反映功能迭代节奏
  · 构建日期：自动取打包当天日期，区分同一语义版本的不同构建
    （同一天多次构建共享同一构建号；这是预期行为）

发版时只需改 __base_version__，构建日期由 get_version() 自动附加。
所有需要版本号的地方都应 import __version__ / get_version()。
打包时 pack_release.py 会把完整版本号写入 manifest，用于在线更新比对。
"""
from datetime import date

# 主.次.修订 —— 手动维护，发版时改这里
__base_version__ = "2.1.1"

# 构建日期 —— 自动取当天（打包日）。格式 YYYYMMDD
__build_date__ = date.today().strftime("%Y%m%d")

# 完整版本号 —— 主.次.修订.构建日期
__version__ = f"{__base_version__}.{__build_date__}"

__app_name__ = "螺丝钉-电商智能体矩阵"


def get_version() -> str:
    """返回完整版本号（含构建日期）。"""
    return __version__
