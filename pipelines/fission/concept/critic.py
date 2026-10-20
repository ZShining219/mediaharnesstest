"""World Critic：只做事实/可拍/商品证据校验，不评价“好不好笑”。"""
from __future__ import annotations

from .schema import normalize, validate


def critique(worlds: list[dict], anchor: dict) -> tuple[list[dict], list[dict]]:
    accepted, rejected, seen = [], [], set()
    for i, raw in enumerate(worlds):
        w = normalize(raw, anchor, i)
        errors = validate(w, anchor)
        if w["fingerprint"] in seen:
            errors.append("与世界库/本批候选重复")
        if errors:
            rejected.append({"world": w, "errors": errors})
            continue
        seen.add(w["fingerprint"])
        accepted.append(w)
    return accepted, rejected
