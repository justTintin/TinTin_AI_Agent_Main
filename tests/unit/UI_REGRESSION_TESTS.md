# UI 回归测试说明

本文档说明 `tests/unit/` 下两个 UI 回归测试的设计意图、断言逻辑和报错含义，供新人快速理解维护。

---

## 1. test_qss_purity.py — QSS 样式表纯净性

**文件**: `tests/unit/test_qss_purity.py`
**被测对象**: `studio/ui/gui_styles.py` 中的 `STYLE_SHEET` 字符串

### 背景

`STYLE_SHEET` 是一个 Python 三引号字符串，内容是 Qt Style Sheet (QSS)，通过 `app.setStyleSheet()` 应用到全局。QSS 的语法和 CSS 类似，但由 Qt 自带解析器处理，**不支持 `#` 行注释**——`#` 在 QSS 中是 ID 选择器的前缀。

如果 Python linter 指令（如 `# noqa: E501`）被误写到 QSS 字符串内部，Qt 会尝试把 `# noqa` 解析为 ID 选择器，解析失败后**从该位置起中断后续所有规则的解析**，导致属性选择器（`QLabel[level="ok"]` 等）全部失效。

### 断言清单

| 测试方法 | 断言逻辑 | 报错信息 | 说明 |
|---|---|---|---|
| `test_no_python_linter_directives` | 逐行扫描 `STYLE_SHEET`，匹配 `# noqa`、`# type: ignore`、`# pragma:`、`# pylint:` 四种 Python 指令模式，匹配行收集到 `bad` 列表 | `STYLE_SHEET 中混入了 Python linter 指令，会破坏 QSS 解析:` + 具体行号和内容 | 核心断言。防止 Python 指令污染 QSS 字符串 |
| `test_brace_balance` | 统计 `{` 和 `}` 出现次数，两者必须相等 | `大括号不配对: {=N, }=M，QSS 将解析失败` | 大括号不配对会导致 QSS 解析中断 |
| `test_comment_balance` | 统计 `/*` 和 `*/` 出现次数，两者必须相等 | `注释标记不配对: /* =N, */ =M` | CSS 注释不配对会影响后续规则解析 |
| `test_property_selectors_work` | 创建 offscreen `QApplication`，应用全量 `STYLE_SHEET`，对 `QLabel#ov_value` 设置 `level` 属性为 `ok/warn/bad/idle`，polish 后取 `windowText()` 颜色，逐一比对期望值 | `属性选择器未生效，可能 QSS 被污染或选择器特异性错误:` + 不匹配的选择器列表 | 端到端验证。直接检查颜色是否正确应用，能捕获字符串纯净性检查遗漏的问题 |

### `test_property_selectors_work` 的期望值

| objectName | 属性 | 值 | 期望颜色 | 语义 |
|---|---|---|---|---|
| `ov_value` | `level` | `ok` | `#34d399` (绿) | 资源使用率正常 |
| `ov_value` | `level` | `warn` | `#fbbf24` (黄) | 资源使用率警告 |
| `ov_value` | `level` | `bad` | `#f87171` (红) | 资源使用率危险 |
| `ov_value` | `level` | `idle` | `#5f6475` (灰) | 资源数据未获取 |

### 跳过条件

- `test_property_selectors_work` 在以下情况会 `skip`：
  - PySide6 不可用（无 GUI 环境的 CI）
  - 已存在非 `QApplication` 的 `QCoreApplication` 实例（其他测试先创建了事件循环，无法再设置样式表）

### 如何添加新的属性选择器检查

在 `cases` 列表中追加元组即可：

```python
cases = [
    ("ov_value", "level", "ok", "#34d399"),
    # 新增：检查服务器状态点
    ("ov_server_dot", "state", "ok", "#34d399"),
]
```

---

## 2. test_page_index.py — 页面索引一致性

**文件**: `tests/unit/test_page_index.py`
**被测对象**: `studio/gui_main.py`（content_stack 构建）和 `studio/gui/main_window_sidebar.py`（菜单索引引用）

### 背景

主界面使用 `QStackedWidget`（`content_stack`）管理页面。页面索引由 `addWidget()` 调用顺序决定：第 1 个 `addWidget` → index 0，第 2 个 → index 1，以此类推。

侧边栏菜单通过 `switch_page(index)` 切换页面。如果删除某个页面（删除了一个 `addWidget` 调用），后续所有页面的索引会整体偏移，但侧边栏中的索引引用不会自动更新，导致**菜单文字和实际显示的页面错位**。

### 静态分析方法

本测试不启动 GUI，而是用正则表达式对源代码做静态分析：

| 提取方法 | 数据来源 | 正则模式 | 产出 |
|---|---|---|---|
| `_extract_stack_order` | `gui_main.py` | `content_stack\.addWidget\(self\.(page_\w+)\)` | 有序列表 `[page_downloader, page_hotspots, ...]`，列表下标 = stack 索引 |
| `_extract_sidebar_indices` | `main_window_sidebar.py` | `switch_page\((\d+)\)` + `"[^"]+"\s*,\s*(\d+)\s*,` + `target_index...(\d+)` | 集合 `{0, 1, 3, 14, 19, ...}`，所有被引用的索引 |

### 断言清单

| 测试方法 | 断言逻辑 | 报错信息 | 说明 |
|---|---|---|---|
| `test_stack_has_enough_pages` | `len(stack_pages) > max(sidebar_indices)` | `content_stack 只有 N 个页面，但侧边栏引用了索引 M（越界）` | 防止页面被删除后索引越界 |
| `test_sidebar_index_maps_to_named_page` | 遍历每个 sidebar 索引，`stack_pages[idx]` 不在占位名称集合中 | `侧边栏索引 N 映射到占位页面 page_XXX，该索引对应的真实页面可能已被删除但索引未更新` | 防止菜单指向被删除/占位的页面 |
| `test_lazy_page_indices_within_range` | 遍历所有 `_register_lazy_page(N, ...)` 调用，`N < len(stack_pages)` | `_register_lazy_page(N, ...) 索引超出 content_stack 范围（共 M 页）` | 防止懒加载注册的索引越界 |
| `test_no_orphan_placeholder` | 遍历 stack 中所有占位页面，确认其索引不在 `sidebar_indices` 中 | `侧边栏引用了占位页面索引 N（page_XXX），说明删除页面后索引未对齐` | 反向检查：占位页面不应被任何菜单引用 |

### 占位页面机制

删除页面时，如果直接删掉 `addWidget` 调用，会导致后续索引偏移。正确做法是保留一个空 `QWidget` 作为占位，维持索引槽位：

```python
# 占位：保持索引对齐，不删 addWidget
self.page_terminal_placeholder = QWidget()
self.content_stack.addWidget(self.page_terminal_placeholder)
```

测试会确认这些占位页面的索引没有被任何侧边栏菜单引用。

### 如何添加新的占位页面

在以下两处同步添加：

1. `test_sidebar_index_maps_to_named_page` 的 `placeholder_names` 集合
2. `test_no_orphan_placeholder` 的 `known_placeholders` 集合

```python
placeholder_names = {"page_terminal_placeholder", "page_new_placeholder"}
known_placeholders = {"page_terminal_placeholder", "page_new_placeholder"}
```

---

## 运行方式

```powershell
# 单独运行
python_embeded\python.exe -m unittest discover -s tests\unit -p "test_qss_purity.py" -v
python_embeded\python.exe -m unittest discover -s tests\unit -p "test_page_index.py" -v

# 全量测试门禁（包含这两个测试）
python_embeded\python.exe -m unittest discover tests\unit
```

## 维护原则

- **新增页面**：在 `gui_main.py` 中 `addWidget` 后，确认侧边栏索引正确指向新位置。
- **删除页面**：用占位 `QWidget` 替代被删除的 `addWidget`，避免索引偏移；同时在 `known_placeholders` 中登记。
- **新增 QSS 属性选择器**：在 `test_qss_purity.py` 的 `cases` 列表中追加期望颜色验证。
- **新增 Python linter 指令**：确保 `# noqa` 等指令不出现在 `STYLE_SHEET` 三引号字符串内部。
