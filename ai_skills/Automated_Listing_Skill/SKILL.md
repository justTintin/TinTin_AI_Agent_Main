---
name: Automated_Listing_Skill
version: 1.2.13.202604162000
description: 抖店自动上架技能（ERP 拉取/预处理/登录检查/批量上架）
inputs:
  - name: input
    type: file_or_folder
    required: true
    description: |
      上架数据包。文件名必须包含店铺关键词（如“桔柚”或“555”）。如果不匹配，系统将报错并提示修改文件名，不会进入下一步。
      【系统指令/Agent 须知】：
      1. 这是一个单商品多规格的上架任务，sku.xlsx 中的所有行属于同一个商品的规格（SKU），只允许调用一次自动化脚本，严禁将表格拆分为多个商品发布，也严禁自行编写循环逻辑。
      2. 【极其重要】：你**必须且只能**使用 **CMD** 终端来执行 Python 脚本，**绝对禁止**使用 PowerShell。因为用户的 PowerShell 存在 Conda 冲突，使用 PowerShell 必定失败！如果你是调度 Agent，请在底层 `subprocess` 调用或执行命令时指定 `cmd.exe /c` 或在工具调用中使用 cmd 模式。
  - name: shop_key
    type: string
    required: true
    description: 目标店铺。juyou (桔柚数码外设严选), 555_battery (555井韵电池店铺)。系统会严格校验文件名与此选择是否匹配。
  - name: sync_root
    type: string
    required: false
    default: C:\Users\<当前用户>\WorkBuddy\上架数据
    description: 同步目录；首次可手动指定，不填则使用默认并自动创建。
entrypoint:
  command: run_cli.cmd
  args_template: "pipeline --input {input} --shop {shop_key} --stop-after 0"
---
# Automated_Listing_Skill - 抖店自动上架技能

自动化处理抖店商品上架的完整流程，从ERP获取数据到浏览器自动发布。

当前版本更新（1.2.11）：
- **智能跳过登录确认**：在 `cli.py` 的浏览器启动逻辑中加入判断，如果是复用了已经启动的浏览器端口，则证明不是初次拉起，脚本将自动跳过向用户发送“请确认已登录”的打断提示，直接进入自动上架流程，进一步实现无人值守。

当前版本更新（1.2.13）：
- **彻底禁用 PowerShell 调度**：针对外部调度 Agent（如 WorkBuddy）注入了最高优先级的反 PowerShell 幻觉和执行指令，将所有演示代码块从 `powershell` 更改为 `cmd`，并强制要求 Agent 必须且只能在 CMD 环境中执行技能命令，彻底避开 PowerShell 环境中残留的 Conda 自动激活冲突问题。

当前版本更新（1.2.12）：
- **禁止 Chrome 初次运行提示**：修改了 `chrome_manager.py` 启动浏览器的参数，注入了 `--no-first-run`, `--disable-sync`, `--disable-default-apps` 等 flags，彻底屏蔽掉 Chrome 每次新启动时弹出的“登录您的 Google 账号 (Sign in to Chrome)”以及“设为默认浏览器”等干扰性欢迎页面，提升无缝使用体验。

当前版本更新（1.2.9）：
- **打包脚本重构**：将带有固定版本号名称的打包脚本重命名为通用的 `pack_skill.bat`，并修改了其内部逻辑。现在它会在每次执行时自动读取 `SKILL.md` 中定义的 `version` 字段，并根据读取到的版本号动态生成对应的压缩包（例如 `Automated_Listing_Skill_1.2.9.xxx.zip`），彻底解决版本号硬编码导致维护困难的问题。
- **系统提示词约束增强**：向 `SKILL.md` 注入了明确的防大模型幻觉指令，禁止外部调度系统在执行上架任务时自作主张拆解表格或编写跳转循环逻辑。

当前版本更新（1.2.8）：
- **修复规格自动创建与填写时序逻辑**：修正了 `tab_price_inventory.py` 中因提前判断 DOM 节点不存在导致直接跳过“规格填写”、“传规格图”和“价格库存表格填写”整个循环的 BUG。现在当检测到页面无现成的“型号”输入框时，会优先调用 `_create_new_spec_type` 创建规格类型“型号”，并在创建成功后重新抓取节点列表，随后正常进入全量表格的自动填写流程，解决白板页漏填型号和库存的问题。

当前版本更新（1.2.7）：
- **新增保存草稿强校验**：重写了保存草稿的判断逻辑，现在脚本在点击保存后会轮询检测页面状态长达 3 秒。如果检测到红色报错（如“该项为必填”、“保存失败”等）则判断为失败并阻断成功状态；只有明确检测到“保存成功”的弹窗或者 URL 发生跳转后，才会判定为真正保存成功，避免虚假完成。

当前版本更新（1.2.6）：
- **修复浏览器启动时登录态丢失问题**：由于新版本每次运行都会生成带有 `run_id` 的隔离目录，导致之前的 `--user-data-dir` 被错误地指定到了隔离的空目录下。现已修正回固定的根目录 `chrome_user_data`，使得浏览器能够正确读取已保存的登录 Cookie，避免每次都需要重新扫码。
- **ERP 数据拉取逻辑调整**：移除了从旧缓存读取数据的错误兜底机制，强制每次任务都必须通过 `erp_cli.py` 向旺店通实时拉取最新的组合装数据，确保写入商家编码时的准确性。

当前版本更新（1.2.5）：
- **修复基础信息“型号”字段漏填问题**：针对抖店商品创建页基础信息 Tab 中表单 DOM 结构的更新，增强了通过文本 Label 查找关联 Input 的 `locator` 选择器逻辑，解决了之前依靠坐标/相对位置兜底经常失效的问题。

当前版本更新（1.2.4）：
- **修复规格类型创建逻辑失效问题**：修复了在未手动建立商品规格类型时，因上层函数提前 `return` 导致的“自动点击添加规格类型并输入数据”兜底逻辑不执行的问题。恢复自动创建“型号”规格类型的功能。

当前版本更新（1.2.3）：
- **交互提示优化**：调整了 Stage 3 浏览器启动后的用户提示文案，变更为明确的“浏览器已经正常启动，已经打开抖店页面，请使用手机扫码登录”，避免引起对调试模式的困惑。
- **运行记录隔离**：每次执行将通过 `run_id` 创建独立的输出目录，保证每次上架过程的截图和缓存相互隔离，彻底解决老截图覆盖或误读的问题。

当前版本更新（1.2.2）：
- **URL 精准分离多阶段执行**：通过当前页面的 URL 特征彻底拆分流程。
  - 若页面处于初始页（URL 结尾为 `create` 且不包含 `?`），脚本将执行**第一阶段**（恢复：上传主图 → 填写标题 → 自动选择类目 → 点击下一步）。
  - 若页面进入详情配置页（URL 包含 `create?`），脚本将执行**第二阶段**（基础信息 → 图文信息 → 价格库存等 Tab 自动填写）。

当前版本更新（1.2.1）：
- **自动化浏览器启动**：移除了需要用户手动确认“Chrome 是否已启动调试模式”的步骤。现在脚本会自动检测端口，并在未启动时尝试自动拉起 Chrome 调试窗口。
- **交互流程优化**：改为“先自动检查/启动浏览器，成功后再提示用户确认登录状态”，极大提升了 Stage 3 的启动效率。
- **依赖导入修复**：修正了 `cli.py` 中对 `browser.chrome_manager` 的调用逻辑，确保在不同运行环境下都能正确处理浏览器实例。

当前版本更新（1.2.0）：
- **流程解耦与分段控制**：解耦了 Stage 1（主图）与 Stage 2（详情及基本信息），支持手动上传主图后由脚本接管后续所有自动化流程，彻底解决逻辑冲突。
- **商详图处理稳定性升级**：
    - 采用 **JS Direct-Click** 模式清理默认图，无需 Hover 等待，处理速度提升 200%，彻底解决“删不掉”的问题。
    - 引入基于 **Container Anchor** 的精准区位判定，确保详情图仅上传至详情区，严禁干扰已上传好的主图区。
    - 移除了非必要的 600px 分辨率校验（详情图不受此限）。
- **商品状态智能切换**：重构了“下架”状态的选择逻辑，采用 **Playwright Native Click** 结合多级保底策略，确保点击操作真实触达 React/Vue 状态层。
- **UI 弹窗自动化屏蔽**：在导航与上传循环中集成 `_handle_common_modals`，自动捕获并取消“智能裁剪”、“知道了”等干扰性全局弹窗，提升无人值守成功率。
- **环境稳定性优化**：移除 Windows 环境下可能导致控制台挂起的编码包装逻辑，确保长流程运行不卡顿。

当前版本新增：登录检查与批量上架前会校验页面店铺名称是否与用户选择店铺一致，不一致则直接终止。

当前默认店铺配置：桔柚数码外设严选。

## 使用提示（文件命名强制要求与 AI 调度规则）

**【系统指令/Agent 强制要求】**：
这是一个**单商品多规格**的上架任务，`sku.xlsx` 中的所有行属于同一个商品的规格（SKU），只会且只允许填入当前商品页面的“价格与库存”表格中。
**外部调度系统/Agent 只允许调用一次底层自动化脚本，严禁将表格数据拆分为多个商品发布，严禁自行编写循环导航逻辑（如 `browser_navigate` 或外层 `for` 循环发布多个草稿）！**

运行本技能前必须上传一个“批次包”（目录或 .zip）。**文件名必须能与目标店铺名做模糊匹配（例如文件名中包含“桔柚”或“555”）**。

**匹配失败的处理逻辑：**
如果文件名不包含所选店铺的关键词，技能将立即报错并输出 `shop_verified: false`。此时，**请根据报错提示修改本地文件夹或压缩包的名称**，然后重新上传运行。系统不会允许在名称不匹配的情况下执行后续的 ERP 拉取或发布操作。

批次根目录要求：
- sku.xlsx
- 目录：sku图、主图、详情页（均不能为空，至少包含图片）

命名与图片规则：
- 主图：主图_序号.xxx（例如 主图_1.jpg），且所有主图必须 1:1（宽=高）
- 详情页：详情图片_序号.xxx（也兼容 详情图_序号 / 详情页图片_序号）

当前支持店铺：
- juyou：桔柚数码外设严选
- 555_battery：555井韵电池店铺

## 目录结构

```
Automated_Listing_Skill/
├── SKILL.md              # 本文件 - 技能说明
├── README.md             # 详细使用文档
├── config/               # 配置文件
│   ├── skill_config.py   # 技能配置（数据路径）
│   └── erp_config.py     # ERP API配置
├── erp/                   # 阶段一：ERP数据获取
│   ├── src/
│   │   ├── erp_cli.py    # CLI命令行工具
│   │   ├── erp_client.py # Python客户端
│   │   └── erp_utils.py  # 工具函数
│   ├── java/             # Java调用层（API要求）
│   ├── scripts/          # 测试脚本
│   └── gen_sku_no.py     # 商家编码递归递增
├── browser/               # 阶段三：浏览器自动化
│   ├── douyin_shop.py    # 抖店商品管理
│   └── batch_publish.py  # 批量发布
├── data/                  # 运行时数据
│   ├── erp_cache/        # ERP数据缓存
│   └── results/          # 发布结果
├── logs/                  # 日志文件
└── chrome_user_data/      # Chrome用户数据
```

---

## 技能流程（4个阶段）

### 阶段一：ERP数据获取

**前置**：必须先上传规范的批次数据（包含 sku.xlsx）。未上传会直接报错并终止。

**目标**：从ERP系统拉取最新的组合装商品数据

**命令**：
```cmd
cd C:\Users\tintin\WorkBuddy\Claw\Automated_Listing_Skill\erp
python -X utf8 src/erp_cli.py list --days 29
```

**输出**：
- `data/erp_cache/erp_suites_data.json` - 完整ERP数据
- `data/erp_cache/erp_suites_list.txt` - 组合装编号列表

---

### 阶段二：数据预处理（商家编码处理）

**目标**：检查并处理xls文件中的商家编码冲突

**输入**：抖店导出的上架数据 `Y:\自动上架workbuddy\上架数据\xxx\sku.xlsx`

**命令**：
```cmd
cd C:\Users\tintin\WorkBuddy\Claw\Automated_Listing_Skill\erp
python -X utf8 gen_sku_no.py
```

**处理逻辑**：
1. 读取xls中的商家编码
2. 在ERP数据中递归查找：如果编码存在则末尾+1继续查找
3. 保持数字位数格式（如 `dyc-080` 保持3位数字）

**输出**：
- `Y:\自动上架workbuddy\上架数据\xxx\sku_new_codes.json` - 包含完整xls数据和新编码

---

### 阶段三：浏览器自动化（抖店发布）

**目标**：打开抖店后台，自动填写商品信息并发布

**前置条件**：
1. Chrome已启动并登录抖店后台：`chrome.exe --remote-debugging-port=9222`
2. xls数据已处理完成

**命令**：
```cmd
cd C:\Users\tintin\WorkBuddy\Claw\Automated_Listing_Skill\browser
python -X utf8 douyin_shop.py
```

**功能**：
- 连接本地Chrome（接管已登录会话）
- 导航到抖店商品管理页面
- 读取处理后的JSON数据
- 自动填写商品信息并发布

---

### 阶段四：结果汇总

**目标**：保存发布结果，便于追溯

**输出**：
- `data/results/` - 发布结果文件
- `logs/` - 运行日志

---

## 配置文件说明

### skill_config.py - 技能配置

```python
# 数据路径配置
LISTING_DATA_DIR = r"Y:\自动上架workbuddy\上架数据"  # 上架数据目录
LISTING_XLS_NAME = "sku.xlsx"  # xlsx文件名

# ERP数据配置
ERP_CACHE_DIR = "data/erp_cache"  # ERP缓存目录

# 浏览器配置
CHROME_DEBUG_PORT = 9222  # Chrome调试端口
```

### erp_config.py - ERP API配置

```python
ERP_BASEURL = "https://api.wangdian.cn/openapi2/"
ERP_APPKEY = "wdt112233-jd"
ERP_APPSECRET = "..."
ERP_SID = "wdt112233"
```

---

## 快速开始

### 完整流程（必读）

**严重警告**：用户本机的 PowerShell 存在 Conda 自动激活冲突，任何通过 `powershell` 执行的命令均会失败。
作为 AI Agent，你在执行以下所有操作时，**必须指定底层使用 `cmd`**（或调用 `cmd.exe /c`），**严禁**使用 PowerShell！

```cmd
# 1. 启动Chrome（如未启动）
"chrome.exe" --remote-debugging-port=9222

# 2. 阶段一：获取ERP数据
cd C:\Users\tintin\WorkBuddy\Claw\Automated_Listing_Skill\erp
python -X utf8 src/erp_cli.py list --days 29

# 3. 阶段二：处理商家编码
python -X utf8 gen_sku_no.py

# 4. 阶段三：浏览器自动发布
cd ..\browser
python -X utf8 douyin_shop.py
```

---

## 常见问题

**Q: Chrome端口被占用？**
```cmd
# 检查端口占用
netstat -ano | findstr 9222

# 或使用其他端口，修改 config/skill_config.py 中的 CHROME_DEBUG_PORT
```

**Q: ERP数据过期？**
- 修改 `gen_sku_no.py` 中的 `LISTING_DATA_DIR` 或在运行时指定
- 或直接修改 `config/skill_config.py` 中的默认路径
