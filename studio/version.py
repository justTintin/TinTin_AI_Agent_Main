# -*- coding: utf-8 -*-
"""
版本号唯一真相源。

所有需要版本号的地方都应从这里 import __version__，避免散落在各处的硬编码。
打包时 pack_release.py 会把 __version__ 写入 manifest，用于版本比对与在线更新。

版本号规则：语义化版本 major.minor.patch（如 2.1.1）。
发版时：改这里 → 同步 README.md / about.md / CHANGELOG.md。
"""

__version__ = "2.1.1"
__app_name__ = "螺丝钉-电商智能体矩阵"


def get_version() -> str:
    """返回当前版本号字符串。"""
    return __version__
