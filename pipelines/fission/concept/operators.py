"""世界生成算子：可插拔的创意变异提示，不是固定世界分类。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "configs" / "concepts" / "operators.json"

DEFAULT = [
    {"name": "invert", "description": "反转默认假设"},
    {"name": "ritualize", "description": "把日常动作仪式化"},
    {"name": "test", "description": "设计一个可拍的小测试"},
    {"name": "compare", "description": "做旧/新或颜色比较"},
    {"name": "collection", "description": "把商品变成一套系统"},
]


def load_operators() -> list[dict]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        ops = [x for x in (data.get("operators") or data) if isinstance(x, dict)
               and x.get("name")]
        return ops or DEFAULT
    except Exception:
        return DEFAULT
