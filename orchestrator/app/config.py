"""集中管理配置: .env 环境变量 + config.yaml 项目配置"""
import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

OUTPUTS = ROOT / "outputs"
REVIEW_DIR = OUTPUTS / "review"
APPROVED_DIR = OUTPUTS / "approved"
PUBLISHED_DIR = OUTPUTS / "published"
FAILED_DIR = OUTPUTS / "failed"
TMP_DIR = OUTPUTS / "tmp"
ASSETS = ROOT / "assets"
WORKFLOWS_DIR = ROOT / "orchestrator" / "workflows"
DB_PATH = ROOT / "data" / "jobs.db"

for d in (REVIEW_DIR, APPROVED_DIR, PUBLISHED_DIR, FAILED_DIR, TMP_DIR, DB_PATH.parent):
    d.mkdir(parents=True, exist_ok=True)


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@lru_cache
def cfg() -> dict:
    p = ROOT / "config.yaml"
    if not p.exists():
        p = ROOT / "config.example.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def section(name: str) -> dict:
    return cfg().get(name) or {}


MINIMAX_API_KEY = env("MINIMAX_API_KEY")
MINIMAX_BASE_URL = env("MINIMAX_BASE_URL", "https://api.minimaxi.com").rstrip("/")
MINIMAX_GROUP_ID = env("MINIMAX_GROUP_ID")

COMFYUI_BASE_URL = env("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
COMFYUI_AUTH = env("COMFYUI_AUTH")  # "user:pass" 或 token

MPT_BASE_URL = env("MPT_BASE_URL", "http://127.0.0.1:8080").rstrip("/")

SAU_BIN = env("SAU_BIN") or str(ROOT / "services" / "social-auto-upload" / ".venv" / "bin" / "sau")
SAU_ACCOUNT = env("SAU_ACCOUNT", "main")

ORCH_TOKEN = env("ORCH_TOKEN")
