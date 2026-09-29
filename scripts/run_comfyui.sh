#!/usr/bin/env bash
cd "$(dirname "$0")/../services/ComfyUI"
exec .venv/bin/python main.py --listen 127.0.0.1 --port 8188 "$@"
