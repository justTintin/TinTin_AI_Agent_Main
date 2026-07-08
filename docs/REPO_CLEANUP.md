# 仓库清理清单（第一步：瘦身源码树）

> 目标：把"应用源码"与"二进制 / 模型 / 运行时数据"分开。
> 当前整棵树约 **84 GB**，真正的源码只有几 MB。
> 下表所有"不入库"项已写进根目录 [.gitignore](../.gitignore)，**文件仍保留在磁盘**，只是不纳入版本控制。

## 一、不入库（已在 .gitignore 覆盖）

| 路径 | 体积 | 说明 |
|------|------|------|
| `apps/` | ~59 G | 第三方工具与模型：voxcpm2、vsr-v1.1.1 / v1.4.0、PaddleOCR、whisper-models、pw-browsers、rembg、whisperx |
| `studio/.runtime/` | 6.5 G | 临时文件(3.6G)、whisper 模型缓存(2.9G)、日志 |
| `studio/assets/ollama_models/` | 5.6 G | ollama 模型权重 |
| `python_embeded/` | 9.2 G | 嵌入式 Python 运行时 |
| `studio/bin/` | 1.9 G | ollama.exe + lib 等二进制 |
| `studio/playwright_profile/` | 641 M | 浏览器 profile（含登录态，敏感） |
| `ffmpeg.exe / ffplay.exe / ffprobe.exe` | 287 M | 媒体处理二进制 |
| `node_modules/` | 16 M | Node 依赖（由 package.json 还原） |
| `studio/browser_profile/` | 3.7 M | 浏览器 profile（敏感） |
| `studio/outputs/ studio/downloads/ studio/logs/ logs/ scratch/` | — | 运行产物 / 草稿 |
| `accounts/sessions/ *cookies* config.ini ai_config.json` | — | **凭据 / 密钥，务必不入库** |
| `*.bak .DS_Store __pycache__/ *.log` | — | 备份 / 系统垃圾 / 缓存 |

**忽略后体积：~84 G → 约 10 MB 源码。**

## 二、保留入库（真源码与小资源）

- `studio/` 下所有 `.py`（gui / core / utils / ui / config）
- `studio/assets/` 中的：`voice_samples/`、`douyin_a_bogus.js`、`douyin_x-bogus.js`、`stealth.min.js`、`app_icon.*`、`workflow/`、`__init__.py`
- `templates/`、`README*.md`、`CHANGELOG.md`、`about.md`
- `package.json`、`package-lock.json`、`pyproject.toml`（建议新增）

## 三、已处理的决定

- **`ai_skills/`（原 817 M / 实际未入库）**：经核查无任何代码依赖、未提交入库，**已整体删除**（含 439M 打包产物），并移除 `.gitignore` 中失效的 `ai_skills/*/dist/` 规则。
- **旧爬虫系统 `legacy_crawler/`**：README 自述「已归档，不属于 studio GUI 运行所需，可整体删除」，且功能已被 `studio/core/` 取代。经核查无运行时调用，**已整体删除**。
  - 连带清理 `export_configs.py` 中复制 `legacy_crawler/config.ini` 的死代码行。

## 四、仍待人工确认

| 项 | 处理建议 |
|----|---------|
| `app_icon.png.bak` / `app_icon.ico.bak` | 直接删除（已被 `*.bak` 忽略，但磁盘上仍在） |

## 四、启用前提

仓库目前**尚未 git 初始化**（`Is a git repository: false`），`.gitignore` 在 `git init` 后才生效。建议顺序：

```bash
git init
git add .gitignore                 # 先只加忽略规则
git status                          # 确认大文件、凭据均未被追踪
git add .
git commit -m "chore: 初始基线，源码树瘦身"
```

> 若以后某个被忽略的运行时目录需在新机器还原，请在 README 写明获取方式（下载脚本 / 模型来源），不要重新提交进仓库。
