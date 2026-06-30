# -*- coding: utf-8 -*-
"""
split_modules.py  —  一次性拆分 batch_publish.py 为各 tab 子模块
运行：python split_modules.py
"""
import os

SRC = os.path.join(os.path.dirname(__file__), "browser", "batch_publish.py")
BROWSER = os.path.join(os.path.dirname(__file__), "browser")

with open(SRC, encoding="utf-8", errors="replace") as f:
    lines = f.readlines()


def extract(start_line: int, end_line: int) -> str:
    """lines[start_line-1 : end_line-1]  (1-indexed, end exclusive)"""
    return "".join(lines[start_line - 1 : end_line - 1])


def write(filename: str, content: str):
    path = os.path.join(BROWSER, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] {filename}  ({len(content.splitlines())} lines)")


# ──────────────────────────────────────────────────────────────────────────────
# excel_reader.py  —  ExcelReader 类 + 兼容包装 + 文件/图片工具
# Lines 1-583 (imports + helpers + ExcelReader + _structure/_sync)
# ──────────────────────────────────────────────────────────────────────────────
EXCEL_READER_HEADER = '''\
# -*- coding: utf-8 -*-
"""
excel_reader.py
sku.xlsx 唯一读取入口（ExcelReader）及文件/图片辅助工具。
包含：
  - ExcelReader 类（一次性加载 sheet1/sheet2，多次复用）
  - 向后兼容的薄包装函数（_read_title_from_sheet2 等）
  - _collect_main_images / _find_sku_image
  - _structure_all_excel_data / _sync_merchant_code_to_excel
  - 路径解析工具：_resolve_working_dir / _find_latest_batch_dir
"""

import os
import re
import sys
import json
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import LISTING_DATA_DIR

'''

# Extract the body:  starts at line 149 (_resolve_working_dir) through line 583
# Lines 1-148: imports + cdp helpers (moved to chrome_manager)
# Lines 149-583: resolve_working_dir ... _sync_merchant_code_to_excel
excel_body = extract(149, 584)
write("excel_reader.py", EXCEL_READER_HEADER + excel_body)

# ──────────────────────────────────────────────────────────────────────────────
# tab_navigation.py  —  _close_right_drawer + _switch_to_tab (shared by all tabs)
# Lines 1163-1287
# ──────────────────────────────────────────────────────────────────────────────
TAB_NAV_HEADER = '''\
# -*- coding: utf-8 -*-
"""
tab_navigation.py
页面标签切换与右侧浮层关闭（所有 Tab 模块共享）。
  - _close_right_drawer(page)
  - _switch_to_tab(page, tab_name)
"""

import asyncio
import os

'''
write("tab_navigation.py", TAB_NAV_HEADER + extract(1163, 1288))

# ──────────────────────────────────────────────────────────────────────────────
# tab_basic_info.py  —  类目检测/选择、主图上传、品牌、型号/生产厂家、下一步
# Lines 585-1049
# ──────────────────────────────────────────────────────────────────────────────
TAB_BASIC_HEADER = '''\
# -*- coding: utf-8 -*-
"""
tab_basic_info.py
【基础信息】Tab 相关操作：
  - 类目自动填充检测（_detect_category_auto_filled）
  - 推荐类目选择（_try_select_recommended_category）
  - 下一步点击（_click_next_step）
  - 主图上传（_upload_main_images / _wait_upload_done）
  - 品牌填写（_fill_brand）
  - 标签输入通用（_fill_text_input_by_label）
  - 型号/生产厂家填写（_fill_model_and_manufacturer）
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .excel_reader import _read_brand_from_sku, _read_sheet2_value

'''
write("tab_basic_info.py", TAB_BASIC_HEADER + extract(585, 1050))

# ──────────────────────────────────────────────────────────────────────────────
# tab_service.py  —  服务与履约 Tab
# Lines 1050-1111
# ──────────────────────────────────────────────────────────────────────────────
TAB_SERVICE_HEADER = '''\
# -*- coding: utf-8 -*-
"""
tab_service.py
【服务与履约】Tab 相关操作：
  - 商品状态设为下架（_fill_service_and_fulfillment）
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab

'''
write("tab_service.py", TAB_SERVICE_HEADER + extract(1050, 1112))

# ──────────────────────────────────────────────────────────────────────────────
# tab_other_info.py  —  其他信息 Tab + 保存草稿
# Lines 1112-1162
# ──────────────────────────────────────────────────────────────────────────────
TAB_OTHER_HEADER = '''\
# -*- coding: utf-8 -*-
"""
tab_other_info.py
【其他信息】Tab 相关操作 + 保存草稿：
  - _fill_other_info(page)
  - _save_draft(page)
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab

'''
write("tab_other_info.py", TAB_OTHER_HEADER + extract(1112, 1163))

# ──────────────────────────────────────────────────────────────────────────────
# tab_image_text.py  —  图文信息 Tab（详情图上传）
# Lines 1288-1493
# ──────────────────────────────────────────────────────────────────────────────
TAB_IMG_HEADER = '''\
# -*- coding: utf-8 -*-
"""
tab_image_text.py
【图文信息】Tab 相关操作：
  - 商品详情图上传（_fill_image_text_info）
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab, _close_right_drawer

'''
write("tab_image_text.py", TAB_IMG_HEADER + extract(1288, 1494))

# ──────────────────────────────────────────────────────────────────────────────
# tab_price_inventory.py  —  价格库存 Tab（规格填写、规格图、价格/库存表格）
# Lines 1494-2109
# ──────────────────────────────────────────────────────────────────────────────
TAB_PRICE_HEADER = '''\
# -*- coding: utf-8 -*-
"""
tab_price_inventory.py
【价格库存】Tab 相关操作：
  - 发货时间选择（48小时）
  - 商品规格填写与规格图上传
  - 价格与库存表格填写
"""

import asyncio
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "config"))
from skill_config import RESULT_DIR
from .tab_navigation import _switch_to_tab
from .excel_reader import (
    _read_sku_image_names_from_sheet1,
    _read_sheet2_value,
    _read_sku_to_merchant_code_mapping,
    _find_sku_image,
)
from .tab_basic_info import _wait_upload_done

'''
write("tab_price_inventory.py", TAB_PRICE_HEADER + extract(1494, 2110))

print("\nAll modules written!")
print(f"Files created in: {BROWSER}")
