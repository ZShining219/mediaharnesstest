#!/usr/bin/env bash
# AI 传媒工作流 - 本机环境安装 (macOS)
# 用法: scripts/setup.sh [--local-comfyui] [--mpt]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> [1/4] 编排器环境 (Python 3.12 + uv)"
uv venv .venv --python 3.12 --clear
uv pip install -p .venv -r requirements.txt

echo "==> [2/4] 克隆开源组件"
mkdir -p services
clone() { [ -d "services/$2" ] || git clone --depth 1 "$1" "services/$2"; }
clone https://github.com/comfyanonymous/ComfyUI ComfyUI
clone https://github.com/dreammis/social-auto-upload social-auto-upload
clone https://github.com/harry0703/MoneyPrinterTurbo MoneyPrinterTurbo

echo "==> [3/4] social-auto-upload (抖音等发布)"
cd services/social-auto-upload
uv venv .venv --python 3.12 --clear
uv pip install -p .venv -e .
.venv/bin/patchright install chromium || echo "patchright chromium 安装失败, 可稍后重试"
cd "$ROOT"

if [[ " $* " == *" --local-comfyui "* ]]; then
  echo "==> [4/4] 本机 ComfyUI (仅开发调试/轻量任务; 视频大模型请用云端 GPU)"
  cd services/ComfyUI
  uv venv .venv --python 3.12 --clear
  uv pip install -p .venv torch torchvision torchaudio
  uv pip install -p .venv -r requirements.txt
  [ -d custom_nodes/ComfyUI-Manager ] || \
    git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Manager custom_nodes/ComfyUI-Manager
  cd "$ROOT"
fi

if [[ " $* " == *" --mpt "* ]]; then
  echo "==> 安装 MoneyPrinterTurbo 环境"
  cd services/MoneyPrinterTurbo
  uv sync --frozen || uv pip install -r requirements.txt
  [ -f config.toml ] || cp config.example.toml config.toml
  cd "$ROOT"
fi

[ -f .env ] || cp .env.example .env && echo "请编辑 .env 填入密钥"
[ -f config.yaml ] || cp config.example.yaml config.yaml
mkdir -p outputs/tmp data logs

cat <<'EOF'

✅ 安装完成

启动:
  scripts/run_orchestrator.sh        # 编排器+审核页 http://127.0.0.1:8800
  scripts/run_comfyui.sh             # 本机 ComfyUI (需 --local-comfyui 安装)
  cd services/MoneyPrinterTurbo && uv run python main.py   # MPT API/WebUI

待你授权/配置 (详见 README "待办授权清单"):
  1. .env 填入 MINIMAX_API_KEY
  2. sau douyin login --account main   # 扫码登录抖音
  3. 云端 GPU ComfyUI (视频模型), 见 docs/cloud-gpu.md
  4. 声音克隆样本 + 角色照片 -> assets/
EOF
