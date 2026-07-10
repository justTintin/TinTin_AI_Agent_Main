# 开发指南

## 环境搭建

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
| `studio/requirements_gui.txt` | GUI 主程序依赖（PySide6 / Pillow / numpy / opencv / av / cryptography / watchdog 等，含可选功能注释） |
| `studio/requirements.txt` | 后端依赖（Flask / 爬虫 / 数据库） |
| `studio/requirements_dev.txt` | 开发工具（PyInstaller / Playwright） |

`make install` 安装全部三项，`make install-dev` 额外加 pyinstaller。

> 重型依赖（torch / paddleocr / onnxruntime 等）随各子应用 venv 自带，不在 requirements 中声明。

## 项目结构

```
studio/
├── gui_main.py              应用程序入口
├── config/paths.py           全局路径 & 二进制定位
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

### 1. 创建页面类

```python
# studio/gui/xxx_page.py
from gui.base_page import BasePage

class XxxPage(BasePage):
    def __init__(self, parent_widget, main_window):
        super().__init__(parent_widget, main_window)

    def setup(self):
        # 在这里构建 UI（往 self.parent_widget 上加 layout/控件）
        from PySide6.QtWidgets import QVBoxLayout, QLabel
        root = QVBoxLayout(self.parent_widget)
        root.addWidget(QLabel("XXX"))
```

### 2. 注册页面

页面在 `studio/gui_main.py` 的 `setup_pages()` 中注册，模式为
`QWidget 容器 → setup 方法 → 加入 content_stack`：

```python
# studio/gui_main.py
self.page_xxx = QWidget()
self.setup_xxx_page()              # 在 MainWindow 里定义，或委托给页面类
self.content_stack.addWidget(self.page_xxx)
```

复杂页面通常在 `studio/gui/main_window_pages.py` 里写 `setup_xxx_page()` 方法，
内部实例化页面类并调用 `.setup()`：

```python
def setup_xxx_page(self):
    from gui.xxx_page import XxxPage
    self.xxx_tool = XxxPage(self.page_xxx, self)
    self.xxx_tool.setup()
```

### 3. 添加侧边栏入口

侧边栏导航项在 `studio/gui_main.py` 中构建（按钮 → 切换 `content_stack` 索引）。
新增按钮后连接到对应的 `page_xxx`。

## 跨平台注意事项

1. **路径**：使用 `config/paths.py` 中的常量，不要硬编码
2. **二进制**：通过 `get_bin("xxx")` 获取平台相关路径
3. **系统判断**：`config/paths.IS_WIN` 或 `sys.platform`

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
make build-win      # Windows .exe (交叉编译需 Wine)
make clean          # 清理构建产物
```
