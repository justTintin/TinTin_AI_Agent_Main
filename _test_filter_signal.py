# -*- coding: utf-8 -*-
"""验证 toggled + partial 信号连接在 PySide6 6.6.3 中正常工作"""
import sys
sys.path.insert(0, r'D:\Project\TinTin_AI_Agent_Main\studio')
from functools import partial
from PySide6.QtWidgets import QApplication, QPushButton

app = QApplication([])
results = []
updating = [False]
btns = {}

def on_toggled(dim, checked):
    if updating[0]:
        return
    results.append((dim, checked))

dims = [None, 'account', 'content_type', 'product_cat', 'industry']
for d in dims:
    btn = QPushButton(str(d))
    btn.setCheckable(True)
    btn.toggled.connect(partial(on_toggled, d))
    btns[d] = btn

# 模拟 setup: 初始选中 "全部"
btns[None].setChecked(True)
assert (None, True) in results, f"setup toggle missing: {results}"

# 模拟用户点击 "account" (toggle = 模拟点击)
results.clear()
btns['account'].toggle()  # checked: False -> True
assert ('account', True) in results, f"user click toggle missing: {results}"

# 模拟 _set_style_filter: 编程式更新所有按钮（带 guard）
results.clear()
updating[0] = True
try:
    for d in dims:
        btns[d].setChecked(d == 'account')
finally:
    updating[0] = False
assert results == [], f"guarded updates should not trigger handler: {results}"

# 验证按钮状态
assert btns['account'].isChecked()
assert not btns[None].isChecked()
assert not btns['content_type'].isChecked()

# 模拟用户点击已选中按钮（取消选中 → 应触发 checked=False）
results.clear()
btns['account'].toggle()  # checked: True -> False
assert ('account', False) in results, f"uncheck toggle missing: {results}"

# 模拟恢复选中（guard 内）
updating[0] = True
try:
    btns['account'].setChecked(True)
finally:
    updating[0] = False
assert btns['account'].isChecked()

# 同时验证旧的 clicked+lambda 方式是否有问题
clicked_results = []
btn2 = QPushButton("test_clicked")
btn2.setCheckable(True)
btn2.clicked.connect(lambda _chk, d='x': clicked_results.append(d))
btn2.toggle()  # 模拟点击
print(f"clicked+lambda results: {clicked_results}")
if not clicked_results:
    print("!! CONFIRMED: clicked+lambda 在此 PySide6 版本中确实失效 !!")
else:
    print("clicked+lambda 也能工作（问题可能在其他环节）")

print(f"PySide6 toggled+partial: ALL TESTS PASS")
