.PHONY: run build-win build-linux clean install install-dev help

PYTHON := python3
VENV   := .venv

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## 安装运行依赖
	$(PYTHON) -m venv $(VENV) || true
	$(VENV)/bin/pip install --upgrade pip
	[ -f studio/requirements.txt ]        && $(VENV)/bin/pip install -r studio/requirements.txt || true
	[ -f studio/requirements_gui.txt ]     && $(VENV)/bin/pip install -r studio/requirements_gui.txt || true
	$(VENV)/bin/pip install playwright
	$(VENV)/bin/playwright install chromium

install-dev: install ## 安装开发依赖（含 pyinstaller）
	$(VENV)/bin/pip install pyinstaller

run: ## 开发模式运行
	./run.sh

build-win: ## 打包 Windows .exe
	$(PYTHON) build.py win

build-linux: ## 打包 Linux 可执行文件
	$(PYTHON) build.py linux

build: ## 打包当前平台
	$(PYTHON) build.py $$([ "$$(uname -s)" = "Linux" ] && echo "linux" || echo "win")

clean: ## 清理构建产物
	$(PYTHON) build.py clean
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true

check: ## 语法检查所有 Python 文件
	find studio -name '*.py' -not -path '*__pycache__*' | xargs $(PYTHON) -m py_compile
	$(PYTHON) -m py_compile build.py
	@echo "All files OK."
