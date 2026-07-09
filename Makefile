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

install-dev: install ## 安装开发依赖
	@echo "注意：打包/发布功能已迁移到独立发布工程 TinTin_Release_Builder"

run: ## 开发模式运行
	./run.sh

build-win build-linux build: ## 打包已迁移到发布工程
	@echo "============================================================"
	@echo "  打包/发布功能已迁移到独立发布工程："
	@echo "    D:\\Project\\TinTin_Release_Builder\\release.py"
	@echo "  请在该工程执行：python release.py"
	@echo "  或双击 运行.bat"
	@echo "============================================================"

clean: ## 清理缓存
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true

check: ## 语法检查所有 Python 文件
	find studio -name '*.py' -not -path '*__pycache__*' | xargs $(PYTHON) -m py_compile
	$(PYTHON) -m py_compile build.py
	@echo "All files OK."
