# 螺丝钉主客户端 UI 重构方案

> 基于 `docs/UI_Design_Audit_Checklist.md` 的审计结论，针对主客户端（`studio/gui/` + `studio/ui/`）制定的具体重构方案。
> 目标：建立统一的 Design Token + 组件规范，治理硬编码样式，提升视觉一致性与维护性。

---

## 一、重构目标与原则

### 1.1 核心目标

| 目标 | 说明 |
|------|------|
| 统一视觉语言 | 主客户端所有页面共用同一套颜色、字体、间距、圆角、阴影 |
| 治理硬编码 | 95% 以上的样式通过 Design Token / QSS class 控制，减少内联样式 |
| 提升专业感 | 从“功能可用”升级到“创意工具级”视觉体验 |
| 支持主题切换 | 完善暗色主题，补齐浅色主题，支持运行时一键切换 |
| 降低维护成本 | 新增页面/组件可直接复用规范，减少重复造轮子 |

### 1.2 设计原则

1. **Dark-first, Light-compatible**：默认暗色，浅色作为派生主题
2. **Token-first**：任何颜色、间距、字号必须来自 token，禁止硬编码
3. **Component-driven**：页面由组件拼装，而非每个页面独立写样式
4. **渐进式迁移**：旧页面分批改造，不追求一次性全部重写
5. **保留交互逻辑**：只改视觉层，不改业务逻辑和数据流

---

## 二、Design Token 体系设计

### 2.1 Token 分层架构

```
tokens/
├── primitives/           # 原始值（不直接用）
│   ├── colors.json       # 品牌色、中性色、功能色、平台色
│   ├── typography.json   # 字体栈、字号、字重、行高
│   ├── spacing.json      # 间距、内边距、外边距
│   ├── radius.json       # 圆角
│   └── shadow.json       # 阴影
├── semantic/             # 语义化 token（组件/页面使用）
│   ├── colors.json       # bg/text/border/accent 语义映射
│   ├── typography.json   # heading/body/caption/label
│   └── elevation.json    # 层级阴影
└── components/           # 组件 token
    ├── button.json
    ├── card.json
    ├── input.json
    ├── table.json
    └── navigation.json
```

### 2.2 颜色 Token（暗色主题）

```css
/* primitives */
--color-brand-50: #e0e7ff;
--color-brand-100: #c7d2fe;
--color-brand-200: #a5b4fc;
--color-brand-300: #818cf8;
--color-brand-400: #6366f1;
--color-brand-500: #4f46e5;
--color-brand-600: #4338ca;

--color-neutral-0: #ffffff;
--color-neutral-50: #f0f1f7;
--color-neutral-100: #c3c6d2;
--color-neutral-200: #9ca1b1;
--color-neutral-300: #73788c;
--color-neutral-400: #5f6475;
--color-neutral-500: #4c5060;
--color-neutral-600: #3a3e4b;
--color-neutral-700: #2b3040;
--color-neutral-800: #1e212b;
--color-neutral-900: #151722;
--color-neutral-950: #0b0c10;

--color-success-400: #34d399;
--color-warning-400: #fbbf24;
--color-danger-400: #f87171;
--color-info-400: #60a5fa;

/* semantic */
--color-bg-base: #0b0c10;
--color-bg-elevated: #12141d;
--color-bg-surface: #151722;
--color-bg-surface-hover: #1a1d2a;
--color-bg-input: #171a25;
--color-bg-input-hover: #1c1f2c;
--color-bg-overlay: rgba(0, 0, 0, 0.6);

--color-text-primary: #f0f1f7;
--color-text-secondary: #c3c6d2;
--color-text-tertiary: #9ca1b1;
--color-text-muted: #73788c;
--color-text-disabled: #4c5060;

--color-border-default: #252938;
--color-border-hover: #2b3040;
--color-border-active: #6366f1;
--color-border-divider: #1e212b;

--color-accent-primary: #6366f1;
--color-accent-primary-hover: #818cf8;
--color-accent-gradient: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);

--color-status-success: #34d399;
--color-status-warning: #fbbf24;
--color-status-danger: #f87171;
--color-status-info: #60a5fa;
```

### 2.3 字体 Token

```css
/* font family */
--font-sans: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", "Segoe UI", sans-serif;
--font-mono: "JetBrains Mono", "Fira Code", Consolas, monospace;

/* font size */
--text-xs: 11px;
--text-sm: 12px;
--text-base: 13px;
--text-md: 14px;
--text-lg: 16px;
--text-xl: 18px;
--text-2xl: 21px;
--text-3xl: 24px;

/* font weight */
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;

/* line height */
--leading-tight: 1.3;
--leading-normal: 1.5;
--leading-relaxed: 1.6;

/* letter spacing */
--tracking-tight: -0.01em;
--tracking-normal: 0;
--tracking-wide: 0.02em;
```

### 2.4 间距 Token

```css
--space-0: 0;
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
```

### 2.5 圆角 Token

```css
--radius-sm: 6px;
--radius-md: 8px;
--radius-lg: 10px;
--radius-xl: 12px;
--radius-2xl: 14px;
--radius-pill: 9999px;
```

### 2.6 阴影 / 光晕 Token

```css
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.2);
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.25);
--shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.35);
--shadow-glow-primary: 0 0 12px rgba(99, 102, 241, 0.25);
--shadow-inset: inset 0 1px 0 rgba(255, 255, 255, 0.05);
```

---

## 三、组件规范设计

### 3.1 组件清单

| 组件 | 优先级 | 说明 |
|------|--------|------|
| Button | P0 | 主按钮、次按钮、幽灵按钮、危险按钮、图标按钮、加载状态 |
| Card | P0 | 标准卡片、功能卡片、设置卡片 |
| Input | P0 | 文本输入、文本域、数字输入、搜索框 |
| Select | P0 | 下拉选择、多选 |
| Checkbox / Radio | P0 | 复选框、单选框 |
| Switch | P0 | 开关 |
| Table | P0 | 表格、表头、行、选中态、空状态 |
| Navigation | P0 | 侧边栏按钮、顶部标签、面包屑 |
| Modal / Dialog | P1 | 弹窗、确认框、抽屉 |
| Toast / Notification | P1 | 通知提示 |
| Empty State | P1 | 空状态插图 |
| Loading State | P1 | 加载中、骨架屏 |
| Progress | P1 | 进度条、步骤条 |
| Badge / Tag | P1 | 状态标签、平台标签 |
| Tooltip | P1 | 工具提示 |
| Tabs | P1 | 标签页 |
| Divider | P2 | 分隔线 |
| Avatar | P2 | 头像 |
| Timeline | P2 | 时间线 |

### 3.2 Button 规范示例

```css
/* Base */
.button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 7px 14px;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  line-height: var(--leading-tight);
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

/* Primary */
.button--primary {
  background: var(--color-accent-gradient);
  color: var(--color-neutral-0);
  border-color: rgba(139, 118, 255, 0.35);
}
.button--primary:hover {
  filter: brightness(1.1);
}
.button--primary:active {
  transform: scale(0.98);
}
.button--primary:disabled {
  background: var(--color-neutral-700);
  color: var(--color-neutral-400);
  border-color: var(--color-border-default);
  cursor: not-allowed;
}

/* Secondary */
.button--secondary {
  background: var(--color-bg-surface);
  color: var(--color-text-secondary);
  border-color: var(--color-border-default);
}
.button--secondary:hover {
  background: var(--color-bg-surface-hover);
  color: var(--color-text-primary);
  border-color: var(--color-border-hover);
}

/* Ghost */
.button--ghost {
  background: transparent;
  color: var(--color-text-secondary);
  border-color: var(--color-border-default);
}

/* Danger */
.button--danger {
  background: rgba(248, 113, 113, 0.1);
  color: var(--color-status-danger);
  border-color: rgba(248, 113, 113, 0.35);
}

/* Sizes */
.button--sm { padding: 5px 10px; font-size: var(--text-sm); }
.button--md { padding: 7px 14px; font-size: var(--text-base); }
.button--lg { padding: 9px 18px; font-size: var(--text-md); }
```

### 3.3 Card 规范示例

```css
.card {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-xl);
  padding: var(--space-4);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.card:hover {
  border-color: var(--color-border-hover);
}

.card--interactive:hover {
  border-color: var(--color-accent-primary);
  box-shadow: var(--shadow-glow-primary);
}

.card--feature {
  background: linear-gradient(180deg, #191d2b 0%, #141722 100%);
  border-top: 3px solid var(--color-accent-primary);
}
```

### 3.4 Input 规范示例

```css
.input {
  background: var(--color-bg-input);
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-md);
  padding: 8px 12px;
  font-size: var(--text-base);
  color: var(--color-text-primary);
  transition: border-color 0.2s ease, background 0.2s ease;
}
.input:hover {
  border-color: var(--color-border-hover);
}
.input:focus {
  outline: none;
  border-color: var(--color-accent-primary);
  background: var(--color-bg-input-hover);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}
.input::placeholder {
  color: var(--color-text-muted);
}
.input:disabled {
  background: var(--color-bg-elevated);
  color: var(--color-text-disabled);
  cursor: not-allowed;
}
```

### 3.5 Navigation 规范示例

```css
.nav-button {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: 9px 14px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--color-text-tertiary);
  font-size: var(--text-base);
  font-weight: var(--font-medium);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}
.nav-button:hover {
  background: var(--color-bg-surface-hover);
  color: var(--color-text-primary);
}
.nav-button--active {
  background: rgba(99, 102, 241, 0.12);
  color: var(--color-text-primary);
  font-weight: var(--font-semibold);
}
.nav-button--active::before {
  content: "";
  position: absolute;
  left: 0;
  width: 3px;
  height: 20px;
  background: var(--color-accent-primary);
  border-radius: 0 3px 3px 0;
}
```

---

## 四、文件与目录重构计划

### 4.1 目标目录结构

```
studio/
├── ui/
│   ├── design_system/
│   │   ├── tokens/
│   │   │   ├── __init__.py
│   │   │   ├── colors.py          # 颜色 token Python 对象
│   │   │   ├── typography.py      # 字体 token
│   │   │   ├── spacing.py         # 间距 token
│   │   │   └── radius.py          # 圆角/阴影 token
│   │   ├── components/
│   │   │   ├── __init__.py
│   │   │   ├── buttons.py         # 按钮 QSS
│   │   │   ├── cards.py           # 卡片 QSS
│   │   │   ├── inputs.py          # 输入框 QSS
│   │   │   ├── tables.py          # 表格 QSS
│   │   │   ├── navigation.py      # 导航 QSS
│   │   │   └── states.py          # 空/加载/错误态
│   │   ├── themes/
│   │   │   ├── __init__.py
│   │   │   ├── dark.py            # 暗色主题完整 QSS
│   │   │   └── light.py           # 浅色主题完整 QSS
│   │   ├── theme_manager.py       # 主题切换管理器
│   │   └── icon_provider.py       # 统一图标提供器
│   └── gui_styles.py              # 兼容入口，转发到 design_system
├── gui/
│   ├── base_page.py               # 已存在，增强组件化支持
│   ├── widgets/                   # 新增：封装通用控件
│   │   ├── __init__.py
│   │   ├── base_card.py
│   │   ├── base_button.py
│   │   ├── base_input.py
│   │   ├── base_table.py
│   │   ├── empty_state.py
│   │   ├── loading_state.py
│   │   └── page_header.py
│   └── main_window.py             # 主窗口，统一加载主题
```

### 4.2 现有文件迁移策略

| 现有文件 | 处理方式 | 说明 |
|----------|----------|------|
| `studio/ui/gui_styles.py` | 保留为兼容入口 | 内部 `import` 新 `design_system/themes/dark.py` |
| `studio/ui/gui_styles_light.py` | 保留为兼容入口 | 内部 `import` 新 `design_system/themes/light.py` |
| 各页面内联 QSS | 逐步迁移 | 先提取到 `components/*.py`，再替换页面引用 |
| Emoji 图标 | 批量替换 | 统一使用 `icon_provider.py` 获取 SVG 图标 |

---

## 五、页面级重构重点

### 5.1 侧边栏导航

**当前问题**：激活态只有左侧 3px 条，视觉层次普通。

**重构方案**：

1. 分组标题使用 `--text-xs` + `--color-text-muted` + `uppercase` + `letter-spacing-wide`
2. 菜单项统一使用 `nav-button` 组件
3. 激活态改为圆角填充背景 + 左侧 3px 高亮色条 + 图标高亮
4. 增加菜单项 hover 时的微弱背景变化
5. 底部系统设置入口与版本号合并为 footer 区域

**预期效果**：更像专业创意工具的导航，如 DaVinci Resolve / Runway。

### 5.2 工作台首页 (`agent_home_page.py`)

**当前问题**：任务卡片内联样式多，AI 对话面板未完成视觉统一。

**重构方案**：

1. 顶部增加统一页面标题栏：
   - 左侧：页面标题 + 当前时间/状态
   - 右侧：全局搜索、设置快捷入口
2. 任务卡片改为 `card--feature` 组件：
   - 顶部 3px 品牌色条
   - 图标使用统一图标库
   - 标题 15px bold，描述 12px muted
   - hover 时边框发光 + 微抬
3. AI 对话面板重新设计：
   - 用户气泡：右侧，深色背景
   - 助手气泡：左侧，品牌色微弱背景
   - 输入框：`input--chat` 变体，底部固定
   - 附件列表：小缩略图 + 删除按钮
   - 斜杠菜单：统一 popup 样式
4. 智能体快捷条使用 `pill-button` 组件

### 5.3 内容页面通用结构

每个页面统一采用以下布局：

```
+--------------------------------------------------+
|  Page Header（标题 + 副标题 + 主操作）              |
+--------------------------------------------------+
|                                                  |
|  Content Area                                    |
|  ├── Filter Bar / Toolbar                        |
|  ├── Main Content（表格/卡片/表单）                |
|  └── Empty / Loading / Error State               |
|                                                  |
+--------------------------------------------------+
```

**Page Header 组件**：

```python
class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", actions: list = None):
        ...
```

**统一空状态组件**：

```python
class EmptyState(QWidget):
    def __init__(self, icon: str, title: str, description: str, action_text: str = ""):
        ...
```

**统一加载状态组件**：

```python
class LoadingState(QWidget):
    def __init__(self, text: str = "加载中..."):
        ...
```

### 5.4 系统设置

**当前问题**：作为独立二级窗口打开，遮挡主界面。

**重构方案（二选一）**：

- **方案 A**：改为右侧抽屉（Drawer），从右侧滑出，不遮挡当前工作区
- **方案 B**：在主窗口内以 Tab 形式嵌入，与“工作台”同级

**推荐方案 A**，更符合现代桌面应用习惯。

---

## 六、图标体系重构

### 6.1 图标库选择

**推荐：Phosphor Icons**

- 原因：线条风格现代、支持权重变化（Thin / Light / Regular / Bold / Fill / Duotone）、与创意工具视觉匹配、开源免费
- 备选：Tabler Icons（同样优秀）

### 6.2 替换策略

| 当前图标 | 替换方式 |
|----------|----------|
| Emoji (`🎬`, `📂`, `🎨`) | 全部删除，替换为 Phosphor SVG |
| MDI 图标 | 逐步替换为 Phosphor，保持语义一致 |
| Fluent Icon | 在 VSR 旧版中保留；主程序中逐步替换 |
| 内联 SVG | 提取到 `assets/icons/` 或使用图标库 |

### 6.3 图标使用规范

```python
# 统一图标提供器
icon_provider.get("rocket", size=20, color="--color-text-secondary")
icon_provider.get("check", size=16, color="--color-status-success", weight="bold")
```

---

## 七、主题切换实现

### 7.1 技术方案

1. 维护两套完整 QSS：`dark.py` + `light.py`
2. 通过 `theme_manager.py` 统一加载：

```python
class ThemeManager:
    THEME_DARK = "dark"
    THEME_LIGHT = "light"
    
    def __init__(self, app: QApplication):
        self.app = app
        self.current_theme = self.THEME_DARK
    
    def load_theme(self, theme: str):
        qss = dark_qss if theme == self.THEME_DARK else light_qss
        self.app.setStyleSheet(qss)
        self.current_theme = theme
    
    def toggle(self):
        new_theme = self.THEME_LIGHT if self.current_theme == self.THEME_DARK else self.THEME_DARK
        self.load_theme(new_theme)
```

3. 配置中持久化主题偏好
4. 启动时读取配置并应用主题

### 7.2 Token 在 QSS 中的使用

```css
/* 旧写法 */
QPushButton { background-color: #232736; }

/* 新写法 */
QPushButton {
  background-color: var(--color-bg-surface);
  border: 1px solid var(--color-border-default);
}
```

> 注：Qt 5.12+/Qt 6 的 QSS 支持 CSS 变量语法，可在 `:root` 中定义变量。

---

## 八、迁移执行计划

### Phase 1：基础 Token 与工具（1 周）

| 任务 | 负责人 | 产出 |
|------|--------|------|
| 建立 `studio/ui/design_system/tokens/` | 前端/设计 | colors.py, typography.py, spacing.py, radius.py |
| 建立 `studio/ui/design_system/themes/dark.py` | 前端 | 完整暗色主题 QSS |
| 建立 `studio/ui/design_system/themes/light.py` | 前端 | 完整浅色主题 QSS |
| 建立 `ThemeManager` | 前端 | theme_manager.py |
| 建立 `IconProvider` | 前端 | icon_provider.py + Phosphor 图标资源 |
| 改造 `gui_styles.py` 为兼容入口 | 前端 | 不破坏现有引用 |

### Phase 2：基础组件封装（1 周）

| 任务 | 产出 |
|------|------|
| 封装 `BaseButton` | 支持 primary/secondary/ghost/danger + 尺寸 |
| 封装 `BaseCard` | 标准卡片、功能卡片 |
| 封装 `BaseInput` | 输入框、搜索框、文本域 |
| 封装 `BaseTable` | 表格 + 表头 + 行 + 空状态 |
| 封装 `PageHeader` | 页面标题栏 |
| 封装 `EmptyState` / `LoadingState` | 空/加载状态 |

### Phase 3：高频页面改造（2 周）

按优先级改造：

1. 工作台首页（`agent_home_page.py`）
2. 系统设置（`system_settings_dialog.py`）
3. 素材生成 / 即梦素材页
4. 成片任务 / 一键成片 / 智能混剪
5. 我的知识库 / 产品资料
6. 媒体工具页

### Phase 4：全页面走查与修复（1 周）

- 暗色主题全页面截图走查
- 浅色主题全页面截图走查
- 修复边界问题（滚动条、弹窗、禁用态）
- 统一空状态/加载状态

### Phase 5：性能与维护性优化（1 周）

- 清理剩余硬编码样式
- 提取可复用布局组件
- 补充 UI 组件使用文档
- 建立新增页面的视觉检查清单

---

## 九、风险与注意事项

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| QSS 变量在旧 Qt 版本兼容性 | 中 | 确认 Qt 6.2+ 支持；如不支持，改用 Python 字符串替换 |
| 改造期间功能回归 | 高 | 只改样式不改逻辑；每改完一个页面即测试 |
| 页面数量多，工期不可控 | 中 | 按 Phase 分批执行，优先高频页面 |
| 浅色主题设计经验不足 | 中 | 参考 GitHub Desktop、VS Code Light+ |
| 图标替换遗漏 | 中 | 全局搜索 Emoji 和 MDI 引用，建立替换清单 |
| 团队成员不适应新规范 | 低 | 编写《UI 组件使用指南》 |

---

## 十、验收标准

| 检查项 | 验收标准 |
|--------|----------|
| Token 覆盖率 | 95% 以上的颜色/间距/字号来自 token，硬编码颜色 ≤5% |
| 组件复用 | 新增页面 80% 以上样式来自基础组件 |
| 主题切换 | 暗色/浅色可一键切换，无明显视觉异常 |
| 图标统一 | 全产品无 Emoji，图标来自统一图标库 |
| 页面一致性 | 同类型页面（表格页、表单页、卡片页）视觉一致 |
| 无障碍 | 主要按钮/链接有清晰 focus 态；颜色对比度 ≥ 4.5:1 |
| 性能 | 启动时间不劣化；QSS 加载时间不劣化 |

---

## 十一、参考资源

- 暗色主题参考：DaVinci Resolve, Runway ML, Linear
- 浅色主题参考：GitHub Desktop, VS Code Light+, Figma
- 图标库：Phosphor Icons (https://phosphoricons.com)
- 设计系统文档：Atlassian Design System, Carbon Design System
- Qt 样式参考：https://doc.qt.io/qt-6/stylesheet-reference.html

---

*本方案为初步重构蓝图，实际执行时可根据团队资源与优先级调整。*
