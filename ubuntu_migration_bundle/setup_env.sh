#!/bin/bash
# Tintin AI Agent - Ubuntu Dependency Setup Script

# Exit immediately if a command exits with a non-zero status
set -e

echo "=== System Package Update ==="
sudo apt-get update -y

echo "=== Installing System Dependencies ==="
# Install python3 virtual env, pip, compiler, ffmpeg and browser shared libraries for playwright
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    ffmpeg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2

# Go up to the workspace root directory (one level up from this script's directory)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
WORKSPACE_DIR="$(dirname "$SCRIPT_DIR")"
cd "$WORKSPACE_DIR"

echo "=== Creating Python Virtual Environment (.venv) ==="
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Virtual environment created at: $WORKSPACE_DIR/.venv"
else
    echo "Virtual environment already exists."
fi

# Activate virtual environment
source .venv/bin/activate

echo "=== Upgrading pip ==="
pip install --upgrade pip

echo "=== Installing Python dependencies ==="
if [ -f "studio/requirements.txt" ]; then
    pip install -r studio/requirements.txt
fi

if [ -f "studio/requirements_gui.txt" ]; then
    pip install -r studio/requirements_gui.txt
fi

echo "=== Installing Playwright and Chromium ==="
# Playwright is required for Douyin API extraction
pip install playwright
playwright install chromium

echo "=== Setting execute permissions on scripts ==="
chmod +x "$SCRIPT_DIR/import_configs.py" || true
chmod +x "$WORKSPACE_DIR/run.sh" || true

echo ""
echo "============================================="
echo "Setup Completed Successfully!"
echo ""
echo "Next steps:"
echo "  1. Place Linux binaries:"
echo "     - Ollama → studio/bin/linux/ollama"
echo "     - Dreamina → studio/bin/linux/dreamina (optional)"
echo "  2. Import configs:  python3 ubuntu_migration_bundle/import_configs.py"
echo "  3. Run:             ./run.sh"
echo "  4. Or use Makefile: make run"
echo "============================================="
