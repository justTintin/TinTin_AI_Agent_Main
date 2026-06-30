# Automated_Listing_Skill - 抖店自动上架技能

自动化处理抖店商品上架的完整流程。

## 目录结构

```
Automated_Listing_Skill/
├── SKILL.md              # 技能定义文档（完整流程说明）
├── README.md             # 本文档
├── config/               # 配置文件
│   ├── skill_config.py   # 技能配置（数据路径）
│   └── erp_config.py     # ERP API配置
├── erp/                   # ERP数据处理
│   ├── src/              # Python客户端
│   ├── java/             # Java调用层
│   ├── scripts/          # 测试脚本
│   └── gen_sku_no.py     # 商家编码处理
├── browser/               # 浏览器自动化
│   ├── douyin_shop.py    # 抖店商品管理
│   └── batch_publish.py  # 批量发布
├── data/                  # 运行时数据
├── logs/                  # 日志
└── chrome_user_data/       # Chrome用户数据
```

## 快速开始

### 完整流程

```powershell
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

## 详细流程

详见 [SKILL.md](./SKILL.md)

## 配置修改

编辑 `config/skill_config.py` 修改数据路径：

```python
LISTING_DATA_DIR = r"Y:\自动上架workbuddy\上架数据"  # 上架数据目录
LISTING_XLS_NAME = "sku.xlsx"  # xlsx文件名
CHROME_DEBUG_PORT = 9222  # Chrome调试端口
```
