"""World registry：跨批次保留世界指纹与结果，提供 novelty penalty。"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "data" / "worlds" / "registry.jsonl"


def load_recent(limit: int = 40) -> list[dict]:
    if not REGISTRY.exists():
        return []
    rows = []
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows[-limit:]


def record(worlds: list[dict], run_id: str, status: str = "contracts_done"):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("a", encoding="utf-8") as f:
        for w in worlds:
            f.write(json.dumps({
                "run_id": run_id,
                "status": status,
                "created_at": int(time.time()),
                "id": w.get("id"),
                "title": w.get("title"),
                "premise": w.get("premise"),
                "device": w.get("device"),
                "operator": w.get("operator"),
                "fingerprint": w.get("fingerprint"),
                "text": w.get("text"),
            }, ensure_ascii=False) + "\n")
