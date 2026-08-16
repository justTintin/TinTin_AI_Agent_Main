---
name: luosiding-design
description: Use this skill to generate well-branded interfaces and assets for Luosiding — 螺丝钉-电商智能体矩阵，AI 电商短视频创作工作站. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping dashboard UIs.
user-invocable: true
---

# Luosiding Design Skill

Read the `README.md` file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## Quick map

- `README.md` — brand context, content fundamentals, visual foundations (read first)
- `css.json` — structured token understanding source
- `colors_and_type.css` — drop-in runtime CSS variables; link it, do not read it to understand tokens when `css.json` exists
- `components/{slug}.json` — component intent, variants, sizes, and usage rules
- `components/_evidence/` — compact component specifications for evidence-backed Figma libraries (use when preview is insufficient)
- `preview/component-{slug}.html` — first-priority component source; resolved before JSON contracts
- `preview/` — small HTML cards illustrating the foundations and components
- `ui_kits/dashboard/` — full click-thru dashboard recreation (工作台概览、成片任务、系统设置)
- `uikit-plan.json` — layout policy, screen inventory, and allowed component slots
- `library-consumption.json` — recommended downstream read order

## Essentials at a glance

- **Brand primary is `#4F46E5`** (indigo-500), cool and technical; violet `#8B5CF6` is reserved for accents and feature-card highlights.
- **Radius is 6 / 8 / 10 / 12 / 14 / 9999px** — deliberately restrained; cards stay at 12px, full pills only for status badges.
- **Default control height is 36px**; small is 28px and large is 44px, applied consistently to buttons and inputs.
- **Type is Inter + PingFang SC + Microsoft YaHei** for base text; JetBrains Mono for code and token names.
- **Spacing base is 4px** with tokens 4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 64px; dense dashboards rely on 16–24px gutters.
- **Shadow system has 5 cool-tinted layers** from `0 1px 2px rgba(11,12,16,0.08)` up to `0 24px 60px rgba(11,12,16,0.28)`; no shadow at rest for flat controls.
- **Voice is Chinese-first, professional, no Emoji** — buttons use verb-led copy like “创建任务”, status labels stay short like “运行中”.
- **Signature pattern:** Feature Card with a top indigo accent bar is the primary workspace entry point in the dashboard UI kit.
