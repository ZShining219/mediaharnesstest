#!/usr/bin/env bash
# ============================================================
# 云端 GPU ComfyUI 一键部署 (Ubuntu 22.04+, NVIDIA 驱动已就绪)
# 适用: 腾讯云 HAI/CVM GPU、AutoDL 等。显存建议 >= 24GB (GGUF 方案)
# 用法: scp 本脚本到服务器后 bash cloud_comfyui_bootstrap.sh
# ============================================================
set -euo pipefail
WORKDIR="${COMFY_HOME:-/root/ComfyUI}"

echo "==> 系统依赖"
apt-get update && apt-get install -y git ffmpeg python3-venv python3-pip || true

echo "==> ComfyUI"
[ -d "$WORKDIR" ] || git clone https://github.com/comfyanonymous/ComfyUI "$WORKDIR"
cd "$WORKDIR"
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt

echo "==> 自定义节点"
cd custom_nodes
node() { d="$(basename "$1" .git)"; [ -d "$d" ] || git clone --depth 1 "$1" "$d"; }
node https://github.com/ltdrdata/ComfyUI-Manager
node https://github.com/kijai/ComfyUI-WanVideoWrapper        # InfiniteTalk / VACE / MultiTalk
node https://github.com/city96/ComfyUI-GGUF                  # GGUF 低显存加载
node https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite # 视频读写
node https://github.com/Fannovel16/comfyui_controlnet_aux    # 姿态/深度预处理
node https://github.com/kijai/ComfyUI-KJNodes                # 遮罩/工具节点
node https://github.com/kijai/ComfyUI-segment-anything-2     # 自动遮罩
cd ..
for d in custom_nodes/*/; do
  [ -f "$d/requirements.txt" ] && pip install -r "$d/requirements.txt" || true
done

echo "==> 模型下载 (huggingface-cli, 文件以 HF 仓库实际为准, 可注释不需要的)"
pip install -U "huggingface_hub[hf_transfer]"
dl() { huggingface-cli download "$1" "$2" --local-dir "models/$3"; }

# --- 数字人 InfiniteTalk (图+音频 -> 对口型视频) ---
dl Kijai/WanVideo_comfy_GGUF "wan2.1-i2v-14b-480p-Q8_0.gguf" diffusion_models   # ~17GB
dl Kijai/WanVideo_comfy_GGUF "Wan2_1-InfiniteTalk_Single_Q8.gguf" diffusion_models
dl Kijai/WanVideo_comfy "Wan2_1_VAE_bf16.safetensors" vae
dl Kijai/WanVideo_comfy "umt5-xxl-enc-bf16.safetensors" text_encoders
dl Kijai/WanVideo_comfy "open-clip-xlm-roberta-large-vit-huge-14_visual_fp16.safetensors" clip_vision
dl Kijai/WanVideo_comfy "wav2vec2-chinese-base_fp16.safetensors" wav2vec2
dl Kijai/WanVideo_comfy "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors" loras

# --- VACE 视频编辑 (换脸/换衣/换背景) ---
dl QuantStack/Wan2.2_VACE-Fun-A14B-GGUF "Wan2.2_VACE-Fun-A14B-Q5_K_M.gguf" diffusion_models || \
  echo "VACE GGUF 文件名可能有变, 到 QuantStack/Wan2.2_VACE-Fun-A14B-GGUF 查看"
# Phantom (人物/服装一致性, 搭配 VACE 减少脸部漂移)
dl Kijai/WanVideo_comfy "Phantom-Wan-14B_fp16.safetensors" diffusion_models || true

# --- 数字人换装/换发型 (图像编辑, 可选) ---
# dl QuantStack/Qwen-Image-Edit-2509-GGUF "Qwen-Image-Edit-2509-Q4_K_M.gguf" diffusion_models

echo "==> 完成。启动: cd $WORKDIR && .venv/bin/python main.py --listen 0.0.0.0 --port 8188"
echo "    本机编排器 .env 中 COMFYUI_BASE_URL 指向 http://<服务器IP>:8188"
echo "    注意: 端口放公网务必加反向代理鉴权 (Caddy/Nginx basic auth)"
