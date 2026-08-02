# -*- coding: utf-8 -*-
"""统一文件对话框封装（全工程文件选择/保存/目录统一入口）。

与 PySide6.QFileDialog 静态方法签名、返回结构保持一致，方便无感迁移：
  - pick_file        == QFileDialog.getOpenFileName      → (path, selected_filter)
  - pick_files       == QFileDialog.getOpenFileNames     → (paths, selected_filter)
  - pick_save_file   == QFileDialog.getSaveFileName      → (path, selected_filter)
  - pick_directory   == QFileDialog.getExistingDirectory → dir (str)

统一约定：
  - 标题统一带「选择/保存」语义，配合触发按钮 mdi_button 风格；
  - 默认目录为空时走系统默认；过滤器为空时 "All Files (*)"；
  - 全部走系统原生对话框（Windows 原生图标/体验，不做 DontUseNativeDialog）。
"""
from PySide6.QtWidgets import QFileDialog

_ALL = "All Files (*)"


def pick_file(parent=None, caption="选择文件", start_dir="", file_filter=_ALL):
    """选择单个文件。返回 (path, selected_filter)，取消时 path 为空。"""
    return QFileDialog.getOpenFileName(parent, caption, start_dir or "", file_filter or _ALL)


def pick_files(parent=None, caption="选择文件", start_dir="", file_filter=_ALL):
    """选择一个或多个文件。返回 (paths, selected_filter)，取消时 paths 为空列表。"""
    return QFileDialog.getOpenFileNames(parent, caption, start_dir or "", file_filter or _ALL)


def pick_save_file(parent=None, caption="保存文件", start_dir="", file_filter=_ALL):
    """选择保存路径。返回 (path, selected_filter)，取消时 path 为空。"""
    return QFileDialog.getSaveFileName(parent, caption, start_dir or "", file_filter or _ALL)


def pick_directory(parent=None, caption="选择目录", start_dir=""):
    """选择目录。返回目录字符串，取消时为空。"""
    return QFileDialog.getExistingDirectory(parent, caption, start_dir or "")