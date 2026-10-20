"""CreativeWorld：创意世界 schema、规范化与距离。"""
from __future__ import annotations

import hashlib
import json
import re

from .semantic import normalize_semantic

REQUIRED = ("title", "premise", "tension", "device", "turn", "payoff", "scene")
PERSON_NEEDS = ("on_body", "hands", "any")


def norm(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip("。！？!?，,；;：:")


def _grams(text: str, n: int = 4) -> set[str]:
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", str(text or ""))
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def _norm_need(value: str) -> str:
    v = str(value or "").casefold()
    if v in ("on_body", "onbody", "wear", "body", "上身"):
        return "on_body"
    if v in ("hands", "hands_only", "hand", "手部"):
        return "hands"
    return "any"


def normalize(world: dict, anchor: dict, idx: int = 0) -> dict:
    atoms = anchor.get("claim_atoms") or []
    atom_ids = {a["id"] for a in atoms}
    must_show = [str(x) for x in anchor.get("must_show") or []]
    w = dict(world or {})
    out = {k: str(w.get(k) or "").strip() for k in REQUIRED}
    out["id"] = str(w.get("id") or f"world_{idx:02d}")
    out["world_tags"] = [str(x) for x in (w.get("world_tags") or []) if str(x).strip()]
    out["props"] = [str(x) for x in (w.get("props") or []) if str(x).strip()]
    out["visual_motifs"] = [str(x) for x in
                            (w.get("visual_motifs") or []) if str(x).strip()]
    out["person_need"] = _norm_need(w.get("person_need") or "any")
    out["operator"] = str(w.get("operator") or "")
    out["claim_ids"] = [str(x) for x in (w.get("claim_ids") or [])
                        if str(x) in atom_ids]
    rituals = []
    for r in w.get("proof_rituals") or []:
        if not isinstance(r, dict):
            continue
        action = str(r.get("action") or "").strip()
        evidence = str(r.get("evidence") or "").strip()
        if not action or not evidence:
            continue
        cids = [str(x) for x in (r.get("claim_ids") or [])
                if str(x) in atom_ids]
        rituals.append({"action": action, "evidence": evidence,
                        "claim_ids": cids})
    out["proof_rituals"] = rituals
    # any 不是“随便”，如果动作本身需要手/上身，就推导出真实的 cast 需求
    if out["person_need"] == "any":
        acts = " ".join(r["action"] for r in rituals)
        if any(x in acts for x in ("上身", "试穿", "穿着", "腰线", "臀线", "坐下", "起身")):
            out["person_need"] = "on_body"
        elif any(x in acts for x in ("手", "指", "掌", "揉", "拉", "翻", "搓", "摸", "捏", "撑", "展开")):
            out["person_need"] = "hands"
    if not out["claim_ids"]:
        out["claim_ids"] = list(dict.fromkeys(
            c for r in rituals for c in r.get("claim_ids") or []))
    out["semantic"] = normalize_semantic(w, out)
    raw = "|".join(norm(out.get(k)) for k in
                   ("title", "premise", "device", "turn", "payoff"))
    out["fingerprint"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    out["text"] = " ".join(
        [out.get(k) or "" for k in REQUIRED]
        + [out.get("operator") or "", " ".join(out["world_tags"]),
           " ".join(out["props"]), " ".join(out["visual_motifs"])]
        + [" ".join(r["action"] + r["evidence"] for r in rituals)])
    # 只保留对生成有用的字段，不把内部 text 写进 prompt
    return out


def validate(world: dict, anchor: dict) -> list[str]:
    errors = []
    for k in REQUIRED:
        if not str(world.get(k) or "").strip():
            errors.append(f"缺 {k}")
    if world.get("person_need") not in PERSON_NEEDS:
        errors.append(f"非法 person_need: {world.get('person_need')}")
    atoms = {a["id"] for a in anchor.get("claim_atoms") or []}
    cids = world.get("claim_ids") or []
    bad = [x for x in cids if x not in atoms]
    if bad:
        errors.append(f"非法 claim_ids: {bad}")
    if not cids:
        errors.append("claim_ids 为空")
    rituals = world.get("proof_rituals") or []
    if len(rituals) < 2:
        errors.append("proof_rituals 少于 2 个")
    if not any(r.get("claim_ids") for r in rituals):
        errors.append("proof_rituals 未绑定 claim_id")
    must_show = [str(x) for x in anchor.get("must_show") or []]
    evidence_text = " ".join(str(r.get("evidence") or "") for r in rituals)
    if must_show and not any(x in evidence_text for x in must_show):
        errors.append("proof_rituals 未覆盖任何 must_show 证据")
    if len(world.get("text") or "") < 20:
        errors.append("world 文本过短")
    return errors


def world_distance(a: dict, b: dict) -> float:
    ga, gb = _grams(a.get("text") or ""), _grams(b.get("text") or "")
    if not ga and not gb:
        return 1.0
    return round(1.0 - len(ga & gb) / max(1, len(ga | gb)), 4)


def recent_key(world: dict) -> dict:
    return {"id": world.get("id"), "title": world.get("title"),
            "premise": world.get("premise"), "device": world.get("device"),
            "operator": world.get("operator"),
            "fingerprint": world.get("fingerprint")}


def dump(world: dict) -> str:
    return json.dumps(world, ensure_ascii=False)
