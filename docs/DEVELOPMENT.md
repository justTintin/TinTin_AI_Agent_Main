# 开发指南

## 环境搭建

### Linux

```bash
# 克隆后首次
make install-dev

# 验证
make check       # 所有 .py 语法检查通过
make run         # 启动 GUI
```

### 依赖说明

| 文件 | 用途 |
|------|------|
| `studio/requirements.txt` | 核心依赖 (Flask / 爬虫 / 数据库) |
| `studio/requirements_gui.txt` | GUI 依赖 (PySide6 / faster-whisper) |
| `studio/requirements_dev.txt` | 开发工具 (PyInstaller / Playwright) |

`make install` 安装全部三项，`make install-dev` 额外加 pyinstaller。

## 项目结构

```
studio/
├── gui_main.py              应用程序入口
├── config/paths.py           全局路径 & 跨平台二进制定位
├── gui/                      页面层 (View)
│   ├── base_page.py          页面基类
│   ├── main_window_*.py      主窗口拆分 (sidebar / pages / services 等)
│   ├── threads.py            QThread 工作线程
│   ├── dialogs.py            对话框
│   └── *_page.py             各功能页面
├── core/                     业务逻辑 (Model)
│   ├── douyin_parser.py      抖音 HTML 解析
│   ├── douyin_video.py       视频信息提取
│   ├── browser_fetcher.py    Playwright 浏览器封装
│   └── ...
├── utils/                    工具层 (Service)
│   ├── thread_worker.py      QThread 基类
│   ├── comfyui_client.py     ComfyUI API
│   ├── voxcpm_client.py      VoxCPM TTS API
│   ├── ollama_manager.py     Ollama 本地模型
│   └── ...
└── ui/
    └── gui_styles.py         暗色主题 QSS
```

## 添加新功能页面

### 1. 创建页面

```python
# studio/gui/xxx_page.py
from PySide6.QtWidgets import QWidget
from gui.base_page import BasePage

class XxxPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.page_id = "xxx"

    def build_ui(self):
        # 在这里构建 UI
        pass
```

### 2. 注册页面

编辑 `studio/gui/main_window_pages.py`：

```python
from gui.xxx_page import XxxPage

# 在 init_pages() 中：
self.xxx_page = XxxPage()
self.pages["xxx"] = self.xxx_page
```

### 3. 添加侧边栏

编辑 `studio/gui/main_window_sidebar.py`，在对应分类下添加入口。

## 跨平台注意事项

1. **路径**：使用 `config/paths.py` 中的常量，不要硬编码
2. **二进制**：通过 `get_bin("xxx")` 获取平台相关路径
3. **系统判断**：`config/paths.IS_WIN` 或 `sys.platform`
4. **Qt 平台差异**：Wayland 需要 `QT_WAYLAND_SHELL_INTEGRATION=xdg-shell`

## 第三方应用集成

`apps/` 目录下的工具通过 `utils/<name>_client.py` 封装：

| 应用 | 客户端 | 协议 |
|------|--------|------|
| VoxCPM2 | `voxcpm_client.py` | HTTP REST |
| ComfyUI | `comfyui_client.py` | WebSocket + HTTP |
| Ollama | `ollama_manager.py` | subprocess + HTTP |

## 日志

```python
from utils.logger_utils import get_logger
logger = get_logger(__name__)
logger.info("...")
```

日志输出到 `.runtime/logs/app.log`。

## Building

```bash
make build          # 当前平台
make build-linux    # Linux 可执行文件
make build-win      # Windows .exe (交叉编译需 Wine)
make clean          # 清理构建产物
```
