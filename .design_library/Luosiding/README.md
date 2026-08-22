# Luosiding Design System

A design system reconstruction of **Luosiding** — 螺丝钉-电商智能体矩阵，AI 电商短视频创作工作站。
The system is purpose-built for dashboard-style AI creation workstations where operators manage e-commerce short-video tasks, review status, and configure agent pipelines.

> *“让 AI 像螺丝钉一样，把电商短视频创作拧紧到 workflow 里。”*

## Source

- **Figma library:** Luosiding UI Kit
- **Pages:** 3 core screens — 工作台概览、成片任务、系统设置 — plus 6 component families
- **Brand owner:** Luosiding product team

## What this design system covers

- **Foundations** — Indigo/violet brand spectrum, slate neutral scale, 4px spacing grid, Inter + PingFang SC typography, 6-tier radius, 5-level shadow system
- **Components** — 6 documented components: Button, Card, Input, Navigation, Table, Badge
- **Sample slides & UI kit** — Dashboard UI kit focused on task management and configuration surfaces

---

## CONTENT FUNDAMENTALS

### Voice & tone

Luosiding 的语气是冷静、效率优先的工具型中文。文案避免营销煽情，直接陈述动作和状态，适合长时间操作的生产力场景。人称上以第二人称或无人称为主，不卖萌、不使用 Emoji。按钮和行动点偏好动词开头，如“创建任务”“保存设置”，让用户清楚知道点击后会发生什么。状态文案简短，常用两字或四字结构，如“运行中”“生成失败”。平台名词直接引用中文习惯说法，如“小红书”“B站”“抖音”，不另造翻译。

### Concrete copy examples

- 按钮文案：*“创建任务”*
- 按钮文案：*“保存设置”*
- 状态徽章：*“运行中”*
- 状态徽章：*“成功”*
- 状态徽章：*“失败”*
- 平台标签：*“小红书”* / *“B站”* / *“抖音”*
- 导航项：*“工作台概览”*
- 导航项：*“成片任务”*
- 导航项：*“系统设置”*

### When generating copy

- 按钮用动词开头，避免超过 6 个汉字
- 状态标签使用中性、可扫描的短词，优先两字
- 平台名称使用国内用户熟悉的原品牌名，不加引号
- 产品界面中不使用 Emoji 和颜文字
- 错误提示说明“发生了什么 + 下一步可以怎么做”

---

## Visual Foundations

### Color

The system ships **dark mode by default**. Light mode is available by applying the `.light` class to a container.

- **Brand primary:** `#6366F1` (indigo-400) in dark mode / `#4F46E5` (indigo-500) in light mode — Used for primary buttons, active navigation, focus rings, and key data accents.
- **Brand accent:** `#A78BFA` (violet-400) in dark mode / `#8B5CF6` (violet-500) in light mode — Used for feature card highlights, chart differentiation, and premium AI-agent moments.
- **Indigo scale:** 10 stops from `#E0E7FF` (indigo-50) through `#1E1B4B` (indigo-900). The 400 stop `#6366F1` serves as the dark-mode primary and hover/ring highlight.
- **Violet scale:** 10 stops from `#F5F3FF` (violet-50) through `#4C1D95` (violet-900).
- **Neutrals:** A 12-stop slate scale from `#FFFFFF` (slate-0) to `#0B0C10` (slate-950). In the default dark theme, the dominant working neutrals are slate-950 `#0B0C10` for the page background, slate-900 `#151722` for cards and primary surfaces, slate-800 `#1E212B` for elevated containers, slate-700 `#2B3040` for borders and highest containers, slate-300 `#73788C` for muted text, and slate-50 `#F0F1F7` for primary text.
- **Surface hierarchy (dark):**
  - Background: slate-950 `#0B0C10`
  - Surface: slate-900 `#151722`
  - Surface container: slate-800 `#1E212B`
  - Surface container high: slate-700 `#2B3040`
- **Semantic:**
  - Success: `#34D399` (success-400) in dark mode / `#10B981` (success-500) in light mode
  - Warning: `#FBBF24` (warning-400) in dark mode / `#F59E0B` (warning-500) in light mode
  - Danger: `#F87171` (error-400) in dark mode / `#EF4444` (error-500) in light mode
  - Info: `#60A5FA` (info-400) in dark mode / `#3B82F6` (info-500) in light mode, a distinct blue used for neutral informational states
- **Vibe:** The palette is cool, technical, and high-contrast. Indigo provides trust and clarity for an AI tool, violet adds a subtle intelligent accent without feeling playful, and the slate scale keeps surfaces crisp and scan-able across dense dashboard tables.

### Typography

- **Primary face:** **Inter** — Used for display, heading, and body text on all platforms, loaded from Google Fonts with weights 400, 500, 600, 700.
- **Chinese fallback:** **PingFang SC**, then **Microsoft YaHei**, then system sans-serif. This keeps Chinese text crisp on macOS and Windows without requiring a custom webfont.
- **Mono face:** **JetBrains Mono** with **Fira Code** and Consolas as fallbacks — used for code snippets, token names, and numeric IDs.
- **Scale:**
  - Display: 48px / 700 / line-height 1.1
  - H1: 32px / 700 / line-height 1.2
  - H2: 26px / 600 / line-height 1.25
  - H3: 21px / 600 / line-height 1.3
  - H4: 18px / 600 / line-height 1.4
  - Lead: 16px / 400 / line-height 1.6
  - Body: 14px / 400 / line-height 1.6
  - Caption: 12px / 400 / line-height 1.5
  - Eyebrow: 11px / 600 / line-height 1.4 / letter-spacing 0.08em / uppercase
  - Mono: 13px / 400 / line-height 1.6
- **Letter-spacing:** Display uses `-0.02em` for tighter headlines; eyebrow uses `0.08em` for all-caps labels.
- **Line-height:** Headings are compact (`1.1`–`1.4`) to keep dense dashboards scannable; body and lead stay at `1.6` for readable paragraphs.

### Spacing

The system uses a **4px base grid**. Tokens are `--space-1: 4px`, `--space-2: 8px`, `--space-3: 12px`, `--space-4: 16px`, `--space-5: 20px`, `--space-6: 24px`, `--space-7: 28px`, `--space-8: 32px`, `--space-10: 40px`, `--space-12: 48px`, `--space-16: 64px`. Default control heights are 36px for buttons and inputs, 28px for small variants, and 44px for large variants. Sidebar width is 264px and page header height is 64px.

### Radius

- **6px** (`--radius-sm`) — small chips and compact tags
- **8px** (`--radius-md`) — default controls: buttons, inputs, navigation items, platform badges
- **10px** (`--radius-lg`) — larger cards and containers
- **12px** (`--radius-xl`) — standard cards
- **14px** (`--radius-2xl`) — modals and floating panels
- **9999px** (`--radius-full`) — status badges and pills only

Radius is deliberately restrained: no 0px sharp corners and no oversized 20px+ rounding. Cards stay at 12px so the interface feels organized, while full pills are reserved for status badges.

### Shadow / Elevation

Five layers, all tinted with the slate-950 base `#0B0C10`:

1. **Card (level 1):** `0 1px 2px rgba(11, 12, 16, 0.08)` — resting cards and panels
2. **Card Hover (level 2):** `0 4px 12px rgba(11, 12, 16, 0.12)` — interactive cards on hover
3. **Float (level 3):** `0 8px 24px rgba(11, 12, 16, 0.16)` — dropdowns, popovers, tooltips
4. **Modal (level 4):** `0 16px 40px rgba(11, 12, 16, 0.20)` — dialogs and drawers
5. **Overlay (level 5):** `0 24px 60px rgba(11, 12, 16, 0.28)` — full-screen overlays

The shadow philosophy is disciplined: every elevation step doubles perceived depth, and shadows remain cool-toned so they do not introduce warm gray artifacts against the slate palette.

### Borders, backgrounds, and motion

- **Borders:** Default border color is slate-700 `#2B3040` in dark mode and slate-200 `#9CA1B1` in light mode; subtle dividers use slate-600 `#3A3E4B` in dark mode and slate-100 `#C3C6D2` in light mode. Borders are 1px solid and used to separate cards and table rows rather than relying on shadow alone.
- **Backgrounds:** Page background is slate-950 `#0B0C10` by default (`--background`). Cards use `--surface` (`#151722`), while sidebar and secondary containers use `--surface-container-low` (`#151722` in dark mode / `#F0F1F7` in light mode).
- **Motion:** Fast interactions use 150ms, default transitions use 200ms, and slower reveals use 300ms. Default easing is `cubic-bezier(0.4, 0, 0.2, 1)`. Color, transform, and shadow transitions are defined separately so agents can apply the right property.
- **Iconography:** Default icon sizes are 16px (small), 20px (medium), and 24px (large). Navigation uses 20px icons consistently.

---

## Component Patterns

| Component | Preview | Contract | CSS Source | Key Facts | Key Insight |
|---|---|---|---|---|---|
| Button | `preview/component-button.html` | `components/button.json` | `components.css` section Button | 5 variants (Primary, Secondary, Ghost, Danger, Icon); sizes 28px / 36px / 44px; states Default/Hover/Active/Disabled/Loading | Primary fills with `#4F46E5`; Icon button is square and uses 20px icon slot |
| Card | `preview/component-card.html` | `components/card.json` | `components.css` section Card | 3 variants (Standard, Feature, Interactive); 12px radius; Feature adds top accent bar; Interactive elevates to shadow-2 on hover | Feature card is the signature workspace entry pattern with a brand accent bar |
| Input | `preview/component-input.html` | `components/input.json` | `components.css` section Input | 4 variants (Text, Search, Textarea, Number); sizes 28px / 36px / 44px; states Default/Hover/Focus/Disabled/Error | Search variant prefixes a 20px icon; error state maps to `--color-error` |
| Navigation | `preview/component-navigation.html` | `components/navigation.json` | `components.css` section Navigation | 3 variants (Sidebar Button, Top Tab, Breadcrumb); active sidebar item uses primary fill + left highlight | Sidebar icon slot is fixed at 20px; grouping titles use eyebrow style |
| Table | `preview/component-table.html` | `components/table.json` | `components.css` section Table | 2 variants (Default, Striped); 5 states including Selected and Empty; row height 44px; anatomy Header/Row/Cell/Selection/Actions | Striped variant alternates with `--surface-container-low` `#F0F1F7` |
| Badge | `preview/component-badge.html` | `components/badge.json` | `components.css` section Badge | 3 variants (Status, Platform, Tag); sizes 20px / 24px; Status uses semantic colors and `radius-full` | Platform badge is the only variant that can inherit external brand colors for 小红书 / B站 / 抖音 |

---

## Index

- `README.md` — this file
- `SKILL.md` — agent skill manifest
- `colors_and_type.css` — CSS variables for color, type, radius, shadow, spacing
- `css.json` — structured token understanding source
- `components.css` — aggregated component CSS extracted from preview pages
- `components/` — component contracts (`button.json`, `card.json`, `input.json`, `navigation.json`, `table.json`, `badge.json`)
- `preview/` — small HTML cards for the Design System tab
- `ui_kits/dashboard/` — full click-thru dashboard recreation (工作台概览、成片任务、系统设置)
- `uikit-plan.json` — UI Kit layout policy and screen inventory

---

## Caveats / known substitutions

1. **Inter** is loaded from Google Fonts; if the network is unavailable, the system falls back to PingFang SC and Microsoft YaHei. This is acceptable for Chinese-heavy dashboards but Latin numerals may lose their geometric width.
2. **JetBrains Mono** is loaded from Google Fonts for code and mono text. Fallback to Fira Code or Consolas preserves readability for token names and numeric IDs.
3. Component copy examples in Content Fundamentals are derived from component usage guidelines and UI kit screen names rather than a separate `ui-copies` bundle. They are representative of the observed voice but should be verified against production Figma text layers.
4. The dark-mode shadow values override to pure `rgba(0, 0, 0, ...)` rather than slate-tinted shadows. This is a deliberate contrast boost for dark surfaces.
5. `components.css` aggregates preview-derived styles; if a component preview and its JSON contract diverge, treat the preview DOM/CSS as the first source and the JSON contract as intent documentation.
