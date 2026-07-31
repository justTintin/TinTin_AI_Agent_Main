# 螺丝钉-电商智能体矩阵 · 图标系统设计规范

## 应用图标（App Icon）· Aurora Icon

- **风格**：圆角方形（Windows 风格），深空渐变底，与暗色主题 `#0b0c10` 系一致
- **中心图形**：螺丝钉头（Indigo→Violet 渐变 + 白色十字槽）＝ 品牌「螺丝钉」
- **环绕图形**：8 节点矩阵环 + 连接线 + 虚线轨道 ＝ 「智能体矩阵」；星光点缀 ＝ AI
- **源文件**：`studio/tools/make_app_icon.py`（QPainter 绘制，可改参数重新生成）
- **输出**：
  - `studio/assets/app_icon.png`（512，窗口/托盘图标）
  - `studio/assets/app_icon.ico`（16/32/48/64/128/256 多尺寸，PyInstaller exe 图标）
  - `studio/assets/icons/icon_16~256.png`（多尺寸 PNG 集）
- **重新生成**：`python studio/tools/make_app_icon.py`

## 风格定义
- **风格**：线性图标（Stroke），圆角端点
- **网格**：24×24px 基准
- **线宽**：2px
- **颜色**：继承主题色（`var(--text-secondary)`），激活态（`var(--accent)`）

## 图标清单

### 创作模块
| 名称 | 中文 | SVG |
|------|------|-----|
| `video-create` | 一键成片 | 胶片 + 闪电 |
| `video-mix` | 智能混剪 | 两胶片交叉 |
| `live-clip` | 直播切片 | 直播圆点 + 剪刀 |

### 素材模块
| 名称 | 中文 | SVG |
|------|------|-----|
| `material-mgr` | 素材管理 | 文件夹 + 图片 |
| `vector-search` | 向量检索 | 放大镜 + 节点 |
| `asset-browser` | 素材浏览器 | 地球 + 图片 |

### 文案模块
| 名称 | 中文 | SVG |
|------|------|-----|
| `knowledge-base` | 知识库 | 书本 + 灯泡 |
| `product-lib` | 产品资料 | 盒子 + 标签 |
| `feishu-sync` | 飞书选题 | 云同步 + 文档 |

### 运营模块
| 名称 | 中文 | SVG |
|------|------|-----|
| `dashboard` | 数据看板 | 仪表盘 |
| `account-mgr` | 账户管理 | 用户 + 盾牌 |

### 工具模块
| 名称 | 中文 | SVG |
|------|------|-----|
| `cover-maker` | 封面制作 | 图片 + 画笔 |
| `image-matting` | 图像抠图 | 图片 + 剪刀 |
| `digital-human` | 数字人 | 人脸 + AI |
| `voice-clone` | 声音克隆 | 麦克风 + DNA |
| `video-ocr` | OCR识别 | 文字 + 扫描 |
| `video-repair` | 视频修复 | 视频 + 魔法棒 |

### 系统模块
| 名称 | 中文 | SVG |
|------|------|-----|
| `settings` | 系统设置 | 齿轮 |
| `help` | 帮助 | 问号圆圈 |
