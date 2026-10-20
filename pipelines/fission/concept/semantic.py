"""CreativeWorld / Contract 的单批语义距离。

设计边界：
- semantic 字段的实际值由 LLM 生成（proposer）；
- 字段名、权重、阈值、回退和距离算法由代码固定；
- 不读取历史 run，也不依赖 registry；
- 只用于同一批候选/契约之间的 max-min 和生成前审计。
"""
from __future__ import annotations

import logging
import re
from itertools import combinations

import jieba

jieba.setLogLevel(logging.ERROR)

SEMANTIC_FIELDS = (
    "social_frame",
    "core_device",
    "core_action",
    "proof_form",
    "visual_motif",
    "turn_type",
)

SEMANTIC_WEIGHTS = {
    "core_device": 0.30,
    "core_action": 0.20,
    "proof_form": 0.15,
    "social_frame": 0.15,
    "turn_type": 0.10,
    "visual_motif": 0.10,
}

# 单批内 world / contract 的最低语义距离；低于该值视为“换词不换结构”。
WORLD_MIN_DISTANCE = 0.35
CONTRACT_MIN_DISTANCE = 0.30

_PUNC = re.compile(r"[。！？!?；;，,：:\n]+")
_NORM = re.compile(r"[^一-鿿A-Za-z0-9]+")


def _clean(value, limit: int = 48) -> str:
    text = _PUNC.split(str(value or "").strip())[0]
    text = re.sub(r"\s+", "", text).strip("。！？!?，,；;：:")
    return text[:limit]


def _first(values) -> str:
    if isinstance(values, (list, tuple)):
        for x in values:
            if str(x or "").strip():
                return str(x).strip()
    return str(values or "").strip()


def _fallback(world: dict) -> dict:
    """旧 world / LLM 漏字段时仍然可审计，但不伪装成 LLM 语义标注。"""
    rituals = world.get("proof_rituals") or []
    actions = "；".join(str((r or {}).get("action") or "")
                       for r in rituals if isinstance(r, dict))
    return {
        "social_frame": _first(world.get("world_tags") or []),
        "core_device": _clean(world.get("device") or world.get("premise")),
        "core_action": _clean(_first(actions.split("；"))
                              if actions else world.get("turn")),
        "proof_form": _clean(world.get("device") or "动作验证"),
        "visual_motif": _clean(_first(world.get("visual_motifs") or [])
                               or world.get("scene")),
        "turn_type": _clean(world.get("turn")),
    }


def normalize_semantic(world: dict | None,
                       normalized: dict | None = None) -> dict:
    """把 LLM 输出规范成固定字段；缺失字段由 world 结构回退。"""
    world = world or {}
    base = dict(normalized or world)
    raw = world.get("semantic") if isinstance(world.get("semantic"), dict) else {}
    # 让 semantic_signature 同时看到 LLM 值和规范化后的结构字段
    base["semantic"] = raw
    return {k: v for k, v in semantic_signature(base).items()
            if k != "_source"}


def semantic_signature(world: dict | None) -> dict:
    """取 LLM semantic；缺失字段用 world 结构回退。"""
    world = world or {}
    raw = world.get("semantic") if isinstance(world.get("semantic"), dict) else {}
    fallback = _fallback(world)
    out = {}
    llm_fields = 0
    for key in SEMANTIC_FIELDS:
        value = _clean(raw.get(key))
        if value:
            llm_fields += 1
        else:
            value = fallback.get(key) or ""
        out[key] = value
    out["_source"] = ("llm" if llm_fields == len(SEMANTIC_FIELDS)
                      else "mixed" if llm_fields else "derived")
    return out


def _tokens(text: str) -> set[str]:
    s = _NORM.sub("", str(text or ""))
    if not s:
        return set()
    words = {x for x in jieba.lcut(s) if len(x) >= 2}
    words |= {s[i:i + 2] for i in range(max(0, len(s) - 1))}
    return words


def _set_distance(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.5
    if not a or not b:
        return 0.8
    return 1.0 - len(a & b) / max(1, len(a | b))


def _axis_distance(a: str, b: str) -> float:
    na = _NORM.sub("", str(a or ""))
    nb = _NORM.sub("", str(b or ""))
    if na and na == nb:
        return 0.0
    return _set_distance(_tokens(na), _tokens(nb))


def semantic_distance(a: dict, b: dict) -> float:
    """加权语义距离；0=完全相同，1=完全不相交。"""
    sa, sb = semantic_signature(a), semantic_signature(b)
    total = 0.0
    for key, weight in SEMANTIC_WEIGHTS.items():
        total += weight * _axis_distance(sa.get(key), sb.get(key))
    return round(total, 4)


def semantic_audit(worlds: list[dict],
                   threshold: float = WORLD_MIN_DISTANCE) -> dict:
    rows = [w for w in worlds if isinstance(w, dict)]
    if len(rows) < 2:
        return {
            "ok": True,
            "count": len(rows),
            "min_distance": 1.0,
            "threshold": threshold,
            "pairs": [],
            "unique_core_devices": len(rows),
            "duplicate_core_devices": [],
            "sources": [semantic_signature(w).get("_source")
                        for w in rows],
        }
    pairs = []
    for i, j in combinations(range(len(rows)), 2):
        pairs.append({
            "a": rows[i].get("id") or rows[i].get("title"),
            "b": rows[j].get("id") or rows[j].get("title"),
            "distance": semantic_distance(rows[i], rows[j]),
        })
    devices = [semantic_signature(w).get("core_device") or ""
               for w in rows]
    unique = len(set(devices))
    min_distance = min(x["distance"] for x in pairs) if pairs else 1.0
    return {
        "ok": min_distance >= threshold and unique == len(rows),
        "count": len(rows),
        "min_distance": round(min_distance, 4),
        "threshold": threshold,
        "pairs": pairs,
        "unique_core_devices": unique,
        "duplicate_core_devices": sorted(
            {d for d in devices if d and devices.count(d) > 1}),
        "sources": [semantic_signature(w).get("_source") for w in rows],
    }


def contract_signature(contract: dict) -> dict:
    st = contract.get("structure") or {}
    fmt = (contract.get("target") or {}).get("format") or {}
    pres = fmt.get("presentation") or {}
    world = st.get("creative_world") or {}
    sem = semantic_signature(world)
    actions = " ".join(str(b.get("action") or "")
                       for b in st.get("beats") or [])
    claims = {str((b.get("information") or {}).get("claim_id") or "")
              for b in st.get("beats") or []}
    return {
        **sem,
        "cast": f"{pres.get('person_visibility')}/{pres.get('presenter_mode')}",
        "action_tokens": _tokens(actions),
        "claim_ids": {x for x in claims if x},
    }


def contract_distance(a: dict, b: dict) -> float:
    """契约语义距离，强调 world 装置 + 可拍动作 + cast。"""
    sa, sb = contract_signature(a), contract_signature(b)
    world = semantic_distance(
        (a.get("structure") or {}).get("creative_world") or {},
        (b.get("structure") or {}).get("creative_world") or {},
    )
    action = _set_distance(sa["action_tokens"], sb["action_tokens"])
    cast = 0.0 if sa["cast"] == sb["cast"] else 1.0
    claims = _set_distance(sa["claim_ids"], sb["claim_ids"])
    return round(0.45 * world + 0.30 * action + 0.15 * cast + 0.10 * claims,
                 4)


def contract_semantic_audit(contracts: list[dict],
                            threshold: float = CONTRACT_MIN_DISTANCE) -> dict:
    rows = [c for c in contracts if isinstance(c, dict)]
    if len(rows) < 2:
        return {"ok": True, "count": len(rows), "min_distance": 1.0,
                "threshold": threshold, "pairs": [],
                "unique_casts": len(rows)}
    pairs = []
    for i, j in combinations(range(len(rows)), 2):
        pairs.append({
            "a": f"v{i + 1:02d}",
            "b": f"v{j + 1:02d}",
            "distance": contract_distance(rows[i], rows[j]),
        })
    min_distance = min(x["distance"] for x in pairs) if pairs else 1.0
    casts = [contract_signature(c)["cast"] for c in rows]
    return {
        "ok": min_distance >= threshold,
        "count": len(rows),
        "min_distance": round(min_distance, 4),
        "threshold": threshold,
        "pairs": pairs,
        "unique_casts": len(set(casts)),
        "casts": casts,
    }
