# 旺店通ERP API 客户端

Python + Java 混合调用方式，用于查询和管理ERP数据。

## 目录结构

```
erp/
├── README.md              # 本文档
├── config/
│   └── erp_config.py      # 配置文件
├── src/
│   ├── __init__.py
│   ├── erp_client.py      # Python客户端类
│   ├── erp_cli.py         # Python CLI工具
│   └── erp_utils.py       # 工具函数
├── java/
│   ├── WdtClient.java     # Java API客户端源码
│   ├── WdtClient.class
│   ├── TestSign.class
│   └── fastjson-1.2.83.jar
├── scripts/               # 测试和工具脚本
│   ├── list_suites.py     # 列出所有组合装
│   └── query_by_no.py     # 按编号查询
├── gen_sku_no.py          # 递归查找可用商家编码（保留xls完整数据）
└── output/                # 输出数据
    ├── suites_list.txt    # 组合装列表
    └── suites_full.json   # 完整JSON
```

## 快速开始

### 1. 安装依赖

确保已安装 Java JDK 21，并配置好环境变量。

### 2. 配置

编辑 `config/erp_config.py`：

```python
ERP_BASEURL = "https://api.wangdian.cn/openapi2/"
ERP_APPKEY = "wdt112233-jd"
ERP_APPSECRET = "your_secret_here"
ERP_SID = "wdt112233"
```

### 3. 使用CLI工具

```bash
# 列出所有组合装
python -X utf8 src/erp_cli.py list

# 按编号查询
python -X utf8 src/erp_cli.py query --no dyc-080

# 查询并保存
python -X utf8 src/erp_cli.py list --save
```

### 4. 使用Python客户端

```python
from src.erp_client import WdtClient
from config.erp_config import *

client = WdtClient(ERP_BASEURL, ERP_APPKEY, ERP_APPSECRET, ERP_SID)
response = client.search_combinations()
suites = response.get('suites', [])
```

## API接口

### 查询组合装 (suites_query)

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| page_no | int | 页码，默认1 |
| page_size | int | 每页条数，默认100 |
| start_time | string | 开始时间（yyyy-MM-dd HH:mm:ss） |
| end_time | string | 结束时间（yyyy-MM-dd HH:mm:ss） |

**注意**：
- `end_time` 必须是当前时间前2-5分钟
- 不传时间参数时，返回全部数据
- 不支持按商家编码过滤，需要本地筛选

### 返回字段

| 字段 | 说明 |
|:---|:---|
| suite_no | 商家编码 |
| suite_name | 组合装名称 |
| ... | 其他字段 |

## 技术说明

### 为什么用Java调用？

旺店通ERP有IP白名单限制，Python直接请求会被拒绝。通过Java程序调用可以绑定的IP。

### 签名算法

使用与Java一致的签名算法，已在 `WdtClient.java` 中实现。

## 更新日志

- 2026-04-09: 整理目录结构，统一管理ERP相关代码
