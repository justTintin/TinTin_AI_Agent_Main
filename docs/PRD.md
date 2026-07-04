# TinTin AI Agent 商业化 PRD v1.0

## 一、产品定位

面向电商带货商家的 AI 视频创作与运营平台。核心价值：AI 帮你策划→制作→复盘→涨粉，覆盖抖音到全平台。

**商业模式**：软件 License + 素材订阅制。本地算力免费，云端只有轻量数据看板。

---

## 二、版本体系

```
基础版（付费）      直播切片 + 智能混剪 + 绑定1个抖音号
  └─ 标准版（进阶）  + 素材管理 + AI分析 + 文案创作 + 一键成片 + 绑定3个平台账号
       └─ 旗舰版（全功能）+ 数据看板 + 全平台分发 + 数字人 + 工具类 + 绑定无限账号
```

### 账号绑定数量
| 版本 | 价格策略 | 可绑定账号数 | 说明 |
|---|---|---|---|
| 基础版 | 低价引流 | 1 个 | 仅抖音 |
| 标准版 | 主力产品 | 3 个 | 抖音 + 任选2平台 |
| 旗舰版 | 高客单价 | 不限 | 全平台（抖音/小红书/B站/快手/视频号/YouTube） |

### 功能映射（Feature Flag）
| Flag | 版本 | 功能 |
|---|---|---|
| `clip` | 基础 | 直播切片、智能混剪 |
| `material` | 标准 | 素材管理、向量检索、任务列表、素材浏览器、一键成片 |
| `copywriting` | 标准 | 知识库、产品资料、产品文案、分镜脚本、飞书选题 |
| `analytics` | 旗舰 | 数据看板、热点追踪、营销检测、视频预测 |
| `distribute` | 旗舰 | 全平台自动发布、格式适配、定时发布 |
| `digital_human` | 旗舰 | 数字人、声音克隆、视频修复、视频去字幕 |

**通用模块（所有版本）**：封面制作、图像抠图、智能分层、视频转文字、OCR、LUT调色、系统设置。

---

## 三、技术架构：混合模式

### 存储支持
- **本地素材**：支持本地磁盘目录直接扫描（D:\素材、E:\视频等）
- **NAS 素材**：支持 SMB/CIFS 网络共享挂载扫描，不强制上传
- 两种存储模式统一，AI 分析路径自动识别兼容

```
┌───────────────────────────────┐
│  商家本地 PC（≥ RTX 3060 12G）  │
│  ┌─────────────────────────┐ │
│  │  TinTin Desktop App     │ │
│  │  ├ Ollama (视觉识别)     │ │
│  │  ├ CLIP (向量检索)       │ │
│  │  ├ WhisperX (语音转写)   │ │
│  │  └ DeepSeek API (文案)   │ │
│  │                         │ │
│  │  素材源                   │ │
│  │  ├ 本地磁盘 D:\素材       │ │
│  │  ├ NAS 192.168.x.x/素材   │ │
│  │  └ 混合使用不冲突         │ │
│  │                         │ │
│  │  素材 → 本地AI分析       │ │
│  │  视频不出本地 ✅         │ │
│  └─────────────────────────┘ │
│           ↓ (KB 级数据)        │
└───────────────────────────────┘
              ↓
┌───────────────────────────────┐
│  云端 SaaS                    │
│  ├ 用户认证 + License 激活     │
│  ├ 数据看板（播放/粉丝/转化）   │
│  ├ 素材库（BGM/模板/特效）     │
│  ├ 支付 + 订阅管理             │
│  └ 自动更新 + 远程诊断         │
└───────────────────────────────┘
```

---

## 四、License 系统重构

### 当前状态
- RSA 签名 License，硬件指纹绑定
- `features` 数组控制功能开关
- 文件式验证，无在线激活

### 需要改动
| 功能 | 优先级 | 说明 |
|---|---|---|
| 试用白名单 | P0 | 试用期仅指定手机号可激活，其他人拒绝 |
| 在线激活 | P0 | 启动时联网验证 License |
| 试用机制 | P0 | 首次安装 7 天全功能试用，无需 License |
| 功能开关 | P0 | 侧边栏/页面根据 `features` 显示/隐藏 |
| 续费提醒 | P1 | 到期前 7 天界面提示 |
| 离线宽容 | P1 | 断网时 72 小时内不锁死 |
| 防分享 | P2 | 机器码+使用频率异常检测 |

### 试用白名单
```python
# 组内试用期：仅白名单手机号可激活
TRIAL_WHITELIST = {"138xxxxxxxx"}  # 大怪手机号

def can_activate(phone: str) -> bool:
    if TRIAL_WHITELIST and phone not in TRIAL_WHITELIST:
        return False  # 不在白名单，拒绝激活
    return True
```
- 试用结束后清空白名单，开放公测。

### 实现方式
```python
# studio/utils/license.py 新增
FEATURE_PAGE_MAP = {
    "clip": ["一键成片", "智能混剪", "直播切片"],
    "material": ["素材管理", "向量检索", "素材浏览器"],
    "copywriting": ["知识库", "产品资料", "产品文案", "分镜脚本", "飞书选题"],
    "analytics": ["数据看板", "热点追踪", "营销检测", "视频预测"],
    "distribute": ["全平台发布", "定时发布"],
    "digital_human": ["数字人", "声音克隆", "视频修复", "视频去字幕"],
}

# 账号绑定限制
ACCOUNT_LIMITS = {"basic": 1, "standard": 3, "pro": float("inf")}  # 旗舰版无限

def get_active_features(license_info: LicenseInfo) -> set[str]:
    """返回当前激活的功能集合"""
    if license_info.features:
        return set(license_info.features)
    return {"clip"}  # 免费版默认

def can_access_page(page_index: int, license_info: LicenseInfo) -> bool:
    features = get_active_features(license_info)
    for feat, pages in FEATURE_PAGE_MAP.items():
        if page_index in pages:
            return feat in features
    return True  # 通用模块永远可访问
```

### 侧边栏修改
```python
# studio/gui/main_window_sidebar.py
# 每个 nav_button 加 feature 检查:
if self._can_access_page(target_index):
    layout.addWidget(btn)
```

---

## 五、用户系统（P0）

### 数据模型
```
users:
  id, phone, password_hash, created_at, last_login
  
licenses:
  id, user_id, machine_id, features[], issued_at, expires_at, status
  
subscriptions:
  id, user_id, plan, started_at, ends_at, auto_renew
```

### 接口
```
POST /api/auth/login          → 手机号+验证码登录
POST /api/auth/refresh        → 刷新 token
GET  /api/license/activate    → 激活 License
GET  /api/license/status      → 查询状态
POST /api/license/renew       → 续费
GET  /api/material/list       → 素材库列表
GET  /api/analytics/dashboard → 数据看板
```

### 本地实现
- 首次启动 → 登录页（手机号）
- 登录成功 → 后台校验 License → 解锁对应功能
- 断网 → 72 小时内使用缓存 License，超时锁死

---

## 六、素材订阅库（P1）

### 内容分类
- BGM（背景音乐，按风格/情绪/节奏）
- 模板（片头/转场/片尾/封面）
- 特效（粒子/光效/文字动画）
- AI 模型（Ollama 模型 / Whisper 模型 / CLIP checkpoint）

### 功能
- 本地缓存机制（下载后离线可用）
- 版本更新提醒
- 收藏/搜索/预览

---

## 七、多平台分发（P2）

### 目标平台
抖音、小红书、B站、快手、视频号、YouTube

### 功能
- 视频格式自动适配（9:16 / 16:9 / 1:1）
- 标题/话题标签自动生成
- 定时发布（通过平台 API / 模拟）
- 发布状态追踪

---

## 八、数据看板（P1）

### 指标
- 播放量、完播率、互动率（点赞/评论/分享）
- 粉丝增长趋势
- 视频排名（按播放量/互动）
- 竞品对比

### 技术
- 云端存储分析结果（KB 级）
- 前端 ECharts 可视化
- 平台数据通过 API / Cookie 抓取

---

## 九、渐进路线

| 阶段 | 内容 | 预计工时 |
|---|---|---|
| Phase 1 | License 在线激活 + 功能开关 + 登录页 + 试用白名单 | 2 周 |
| Phase 2 | 侧边栏版本过滤 + 账号绑定限制 + 支付接入 | 2 周 |
| Phase 3 | 云数据看板 + 自动发布引擎 + 素材库后台 | 3 周 |
| Phase 4 | 多平台分发（全平台适配+定时发布）+ SaaS 后台 | 3 周 |
| Phase 5 | 数字人 + 工具类模块（声音克隆/视频修复/去字幕）| 4 周 |

---

## 十、技术约束

- **Python 3.11+** / PySide6 GUI
- **PostgreSQL** 本地素材库（15万+）
- **Ollama** 本地推理（qwen2.5vl 7B+）
- **CLIP ViT-B-16** 向量检索
- **faster-whisper** 语音转写
- **DeepSeek API** 文本生成
- **Git + Gitea** 代码管理（jckunji.com:3000）
- **Windows 为主**运行平台，Linux 开发环境
- 最低硬件：RTX 3060 12G + 16GB RAM + 500GB SSD
