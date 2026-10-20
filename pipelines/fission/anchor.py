"""ProductAnchor：商品锚定层。

Anchor 只描述“什么是这个商品、哪些事实不能变、哪些证据必须出现”，
不描述风格。风格由 style_atlas / planner 独立采样，composer 只做组合。
"""
from __future__ import annotations

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BODY_TERMS = ("小胸", "聚拢", "胸型", "穿出", "上身", "穿着", "穿戴",
              "贴身", "试穿", "副乳", "肩颈")


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def _safe_for_no_person(text: str) -> bool:
    return not any(x in text for x in BODY_TERMS)


def build_anchor(profile: dict) -> dict:
    """从商品 profile 构建不可变锚点；不读 pool，不调用 LLM。"""
    front_policy = (profile.get("reference_policy")
                    or "只负责商品本身；忽略图中的手、背景、文字。")
    front_policy = (front_policy.replace("参考图2", "该参考图")
                    .replace("参考图1", "该参考图"))
    refs = [{
        "view": "front",
        "path": profile["image"],
        "label": "商品正面",
        "policy": front_policy,
    }]
    for key, view, label, policy in (
        ("back_image", "back", "商品背面",
         "只负责背面结构与四排扣；忽略图中的手、背景、文字。"),
        ("inner_image", "inner", "商品内里",
         "只负责内里纹理与软支撑；忽略图中的手、背景、文字。"),
    ):
        if profile.get(key):
            refs.append({"view": view, "path": profile[key],
                         "label": label, "policy": policy})

    atoms = []
    for i, claim in enumerate(profile.get("claims") or [], 1):
        text = str(claim).strip()
        if not text:
            continue
        atoms.append({
            "id": f"claim_{i:02d}",
            "kind": "claim",
            "fact": text,
            "source": "profile.claims",
            "safe_for_no_person": _safe_for_no_person(text),
        })
    for i, item in enumerate(profile.get("must_show") or [], 1):
        text = str(item).strip()
        if not text:
            continue
        atoms.append({
            "id": f"feature_{i:02d}",
            "kind": "feature",
            "fact": text,
            "source": "profile.must_show",
            "safe_for_no_person": True,
        })

    person = dict(profile.get("person") or {})
    return {
        "schema_version": "product-anchor/v1",
        "generated_at": int(time.time()),
        "product_id": profile["product_id"],
        "reference_id": profile.get("reference_id"),
        "identity": profile.get("identity"),
        "category": profile.get("category"),
        "archetype": profile.get("default_archetype") or "ugc_individual_seller",
        "description": profile.get("description") or "",
        "wear_state": profile.get("wear_state") or "",
        "references": refs,
        "must_show": profile.get("must_show") or [],
        "must_not_change": profile.get("must_not_change") or [],
        "claim_atoms": atoms,
        "proof_points": profile.get("proofs") or [],
        "forbidden_claims": (profile.get("constraints") or {}).get(
            "claims_avoid") or [],
        "person": person,
        "allowed_person_visibility": profile.get(
            "allowed_person_visibility") or
            ["full", "partial", "hands_only", "none"],
        "authorization": person.get("authorization", "unknown"),
        "color_policy": profile.get("color_policy", "single"),
        "offer": profile.get("offer") or "活动价，点下方看",
    }


def validate_anchor(anchor: dict) -> list[str]:
    errors = []
    if not anchor.get("claim_atoms"):
        errors.append("claim_atoms 为空")
    refs = anchor.get("references") or []
    if not any(r.get("view") == "front" for r in refs):
        errors.append("references 缺 front")
    for r in refs:
        if not r.get("path"):
            errors.append(f"reference {r.get('view')} 缺 path")
        elif not _resolve(r["path"]).is_file():
            errors.append(f"reference 不存在: {r['path']}")
    person = anchor.get("person") or {}
    if person.get("image") and not _resolve(person["image"]).is_file():
        errors.append(f"person.image 不存在: {person['image']}")
    return errors


def anchor_to_brief(anchor: dict, n: int, text: str | None = None) -> dict:
    """P0 使用的确定性 brief：事实来自 anchor，不再从 claims 里另写一套文案。"""
    facts = [{"key": a["id"], "value": a["fact"], "source": a["source"],
              "confidence": 1.0, "note": a["kind"]}
             for a in anchor["claim_atoms"]]
    person = anchor.get("person") or {}
    return {
        "schema_version": "brief/v0-p0",
        "id": f"brief-{anchor['product_id']}-p0",
        "payload": {
            "product": {
                "product_id": anchor["product_id"],
                "identity": anchor.get("identity"),
                "category": anchor.get("category"),
                "description": anchor.get("description"),
                "image": anchor["references"][0]["path"],
            },
            "facts": facts,
            "unknowns": [],
            "assumptions": [],
            "constraints": {
                "platform": "douyin",
                "language": "zh",
                "claims_avoid": anchor.get("forbidden_claims") or [],
                "color_policy": anchor.get("color_policy"),
            },
            "goal": {
                "deliverables": n,
                "duration_seconds": 12,
                "media": "video",
                "archetype": "ugc_individual_seller",
                "notes": text or "",
            },
            "assets": {
                "person": {"path": person.get("image")},
                "product": {"path": anchor["references"][0]["path"]},
            },
        },
        "provenance": {"anchor": anchor["product_id"]},
    }
