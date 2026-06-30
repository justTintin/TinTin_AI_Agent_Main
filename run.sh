#!/usr/bin/env bash
# AI电商智能体 — Linux 启动脚本
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SCRIPT_DIR}/studio"
VENV_DIR="${SCRIPT_DIR}/.venv"

# Python 解释器
if [ -f "${VENV_DIR}/bin/python" ]; then
    PYTHON="${VENV_DIR}/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

ENTRY="${APP_DIR}/gui_main.py"

if [ ! -f "$ENTRY" ]; then
    echo "[ERROR] gui_main.py not found at $ENTRY"
    exit 1
fi

# PATH：包含 pip --user 安装的脚本（playwright 等）
export PATH="$HOME/.local/bin:$PATH"

# PYTHONPATH：工程源码 + --user site-packages
SITE_USER="$HOME/.local/lib/$($PYTHON -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')/site-packages"
export PYTHONPATH="${APP_DIR}${PYTHONPATH:+:}${SITE_USER}${PYTHONPATH:+:}${PYTHONPATH}"

# 运行时目录
mkdir -p "${APP_DIR}/.runtime/logs" "${APP_DIR}/.runtime/tmp" "${APP_DIR}/.runtime/cookies"
export TMP="${APP_DIR}/.runtime/tmp"
export TMPDIR="${TMP}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-${SCRIPT_DIR}/apps/pw-browsers}"

# QtWebEngine 禁用 GPU 渲染（避免 Wayland + NVIDIA 下段错误）
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---disable-gpu --disable-software-rasterizer}"

# 避免 faster_whisper/ctranslate2 的 ASCII 编码错误
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# Wayland popup 修复（如下拉框有问题再启用）
# export QT_WAYLAND_SHELL_INTEGRATION=xdg-shell

# 中文输入法（Wayland 下走 compositor text-input 协议）
# 必须 unset QT_IM_MODULE，否则 Qt6 会尝试加载不存在的 IM 插件，破坏原生协议
unset QT_IM_MODULE
export GTK_IM_MODULE=fcitx5
export XMODIFIERS=@im=fcitx5


echo "[INFO] Python:   $PYTHON"
echo "[INFO] Entry:    $ENTRY"
echo "[INFO] DISPLAY:  ${DISPLAY:-未设置}"

# 无显示器时自动启用 xvfb
if [ -z "${DISPLAY:-}" ] && command -v xvfb-run &>/dev/null; then
    echo "[INFO] 无显示器，自动启用 xvfb..."
    exec xvfb-run --server-args="-screen 0 1280x1024x24" "$PYTHON" "$ENTRY" "$@"
fi

exec "$PYTHON" "$ENTRY" "$@"