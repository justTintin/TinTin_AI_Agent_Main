# legacy_crawler —— 旧版视频抓取/搬运系统（已归档）

本目录是项目早期的 **TikTok / YouTube / 抖音 视频抓取 + MongoDB 存储 + Flask 预览 + 自动搬运** 系统，
现已与正在迭代的 `studio/` 桌面应用分离归档。**不属于 studio GUI 运行所需**，可独立使用或整体删除/拆为独立仓库。

## 目录结构

```
legacy_crawler/
├── config.ini                  # 爬虫配置([Crawlers]/[Login]/[Douyin_Advanced]/[MySQL] 等)
├── project_analysis.md         # 旧系统的详细分析文档
├── timing_crawl.py             # 定时抓取入口  → core.crawlers.Crawlers
├── run_server.py               # Flask 预览/搬运服务(默认 5050)
├── check_mongo.py              # MongoDB 连接自检
├── repro_test.py               # 抖音解析复现脚本
├── templates/                  # run_server.py 的 Flask 页面
├── assets/                     # 运行所需的 JS(a-bogus 签名、stealth)
└── core/
    ├── crawlers.py             # 各平台抓取主逻辑
    ├── login.py                # Selenium/UC 登录与发布
    ├── douyin_advanced_crawler.py  # 独立的互动价值筛选(MySQL)
    ├── refresh_douyin_cookies.py
    ├── a_lxml_create_html.py
    └── (以下 4 个为 studio/core 的快照副本)
        douyin_a_bogus.py / douyin_video.py / browser_fetcher.py / douyin_parser.py
```

## 与 studio 的关系

- `douyin_a_bogus.py`、`douyin_video.py`、`browser_fetcher.py`、`douyin_parser.py` 这 4 个底层模块
  同时被 studio GUI(`studio/core/douyin_user_downloader.py`)使用，因此 **原件保留在 `studio/core/`**，
  此处是归档时的**副本**，让本目录可独立运行。两处若需修改请注意它们已不再同步。
- studio GUI 仅依赖 `studio/core/` 下的 `creator_browser_controller.py` 与 `douyin_user_downloader.py`，
  与本目录无任何 import 关系。

## 归档时所做的修改

- `timing_crawl.py`: `from crawlers import Crawlers` → `from core.crawlers import Crawlers`
- `run_server.py`:  `from login import Login`     → `from core.login import Login`

## 运行（如需）

```bash
cd legacy_crawler
python -u timing_crawl.py test     # 抓取
python -u run_server.py            # Flask 预览(需 MongoDB / 见 config.ini)
```

> 依赖 MongoDB、MySQL、Node.js 及手动维护的 cookies；属历史代码，未在新环境验证。
