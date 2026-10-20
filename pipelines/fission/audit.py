"""P0 审计：商品锚点 / 风格距离 / 文案去重。"""
from __future__ import annotations

import re
from collections import Counter

from .style_atlas import copy_distance, visual_distance
from .concept.schema import world_distance
from .concept.semantic import (contract_semantic_audit,
                               semantic_audit)

_PUNC = re.compile(r"[。！？!?；;，,\n]+")


def _norm(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip("。！？!?，,；;：:")


def _variant_sentences(contracts: list[dict]) -> list[set[str]]:
    out = []
    for c in contracts:
        vals = set()
        for b in (c.get("structure") or {}).get("beats") or []:
            info = b.get("information") or {}
            for key in ("claim", "proof", "text_overlay", "voiceover",
                        "offer_cta"):
                for s in _PUNC.split(str(info.get(key) or "")):
                    s = _norm(s)
                    if len(s) >= 4:
                        vals.add(s)
        out.append(vals)
    return out


def _sentences(contracts: list[dict]) -> list[str]:
    return [s for vals in _variant_sentences(contracts) for s in vals]


def _cross_variant(contracts: list[dict]) -> dict:
    sets = _variant_sentences(contracts)
    counts = Counter(s for vals in sets for s in vals)
    cross = {s: n for s, n in counts.items() if n >= 2}
    return {
        "duplicates": len(cross),
        "examples": list(cross)[:12],
        "rate": round(len(cross) / max(1, len(counts)), 4),
    }


def _duplicate_stats(values: list[str]) -> dict:
    norm = [x for x in (_norm(v) for v in values) if x]
    counts = Counter(norm)
    dup = {k: v for k, v in counts.items() if v > 1}
    return {
        "total": len(norm),
        "unique": len(counts),
        "duplicates": len(dup),
        "examples": list(dup)[:8],
    }


def audit_contracts(contracts: list[dict], anchor: dict,
                    styles: list[dict], plan_distances: list[dict] | None = None) -> dict:
    n = len(contracts)
    atom_ids = {a["id"] for a in anchor.get("claim_atoms") or []}
    anchor_errors = []
    claim_ids = []
    for c in contracts:
        sid = ((c.get("provenance") or {}).get("style_id"))
        for b in (c.get("structure") or {}).get("beats") or []:
            info = b.get("information") or {}
            cid = info.get("claim_id")
            claim_ids.append(cid)
            if cid not in atom_ids:
                anchor_errors.append(f"{sid} beat {b.get('index')} 非法 claim_id={cid}")
            if not b.get("product_evidence"):
                anchor_errors.append(f"{sid} beat {b.get('index')} 缺 product_evidence")
        refs = (c.get("target") or {}).get("references") or []
        if not any(r.get("kind") == "product" for r in refs):
            anchor_errors.append(f"{sid} 缺 product reference")
        if not ((c.get("target") or {}).get("product") or {}).get("must_show"):
            anchor_errors.append(f"{sid} 缺 must_show")

    hooks, ctas, claims, voices, texts = [], [], [], [], []
    for c in contracts:
        beats = (c.get("structure") or {}).get("beats") or []
        if beats:
            hooks.append((beats[0].get("information") or {}).get("claim") or
                         (beats[0].get("information") or {}).get("text_overlay"))
        for b in beats:
            info = b.get("information") or {}
            claims.append(info.get("claim"))
            voices.append(info.get("voiceover"))
            texts.append(info.get("text_overlay"))
            if info.get("offer_cta"):
                ctas.append(info.get("offer_cta"))
    sent = _sentences(contracts)
    sent_stats = _duplicate_stats(sent)
    cross = _cross_variant(contracts)
    copy = {
        "hooks": _duplicate_stats([x for x in hooks if x]),
        "ctas": _duplicate_stats([x for x in ctas if x]),
        "claims": _duplicate_stats([x for x in claims if x]),
        "voiceovers": _duplicate_stats([x for x in voices if x]),
        "text_overlays": _duplicate_stats([x for x in texts if x]),
        "sentences": sent_stats,
        "cross_variant": cross,
        "unique_hooks": len({_norm(x) for x in hooks if _norm(x)}),
        "unique_ctas": len({_norm(x) for x in ctas if _norm(x)}),
        "variant_count": n,
    }
    copy["ok"] = (
        copy["unique_hooks"] == n and copy["unique_ctas"] == n
        and sent_stats["total"] > 0
        and cross["rate"] < 0.25
    )

    style_rows = []
    for i in range(len(styles)):
        for j in range(i + 1, len(styles)):
            a, b = styles[i], styles[j]
            style_rows.append({
                "a": a["id"], "b": b["id"],
                "visual": visual_distance(
                    {"visual_signature": a.get("visual_signature") or {}},
                    {"visual_signature": b.get("visual_signature") or {}}),
                "copy": copy_distance(
                    {"copy_signature": a.get("copy_signature") or {}},
                    {"copy_signature": b.get("copy_signature") or {}}),
            })
    axis = {
        "person_visibility": len({(s.get("visual") or {}).get("person_visibility")
                                  for s in styles}),
        "presenter_mode": len({(s.get("visual") or {}).get("presenter_mode")
                               for s in styles}),
        "camera_family": len({(s.get("visual") or {}).get("camera_family")
                              for s in styles}),
        "scene_family": len({(s.get("visual") or {}).get("scene_family")
                             for s in styles}),
        "copy_tone": len({(s.get("copy") or {}).get("tone") for s in styles}),
        "copy_cta": len({(s.get("copy") or {}).get("cta_style") for s in styles}),
    }
    min_visual = min([x["visual"] for x in style_rows], default=0)
    min_copy = min([x["copy"] for x in style_rows], default=0)
    perceptual_ok = True
    allowed = set(anchor.get("allowed_person_visibility") or
                  ("full", "partial", "hands_only", "none"))
    has_concept = any((c.get("structure") or {}).get("creative_world")
                      for c in contracts)
    expected_person = min(4, len(allowed), n)
    if has_concept:
        # 创意世界决定 cast：不再为了覆盖四类人物强行改变世界
        expected_person = min(3, len(allowed), n)
    if n >= 5:
        perceptual_ok = (axis["person_visibility"] >= expected_person
                         and axis["presenter_mode"] >= min(2 if has_concept else 3, n)
                         and len({(s.get("visual") or {}).get("text_density")
                                  for s in styles}) >= 2
                         and axis["copy_tone"] >= 3)
    elif n >= 3:
        perceptual_ok = axis["person_visibility"] >= 2
    style = {
        "pairwise": style_rows,
        "min_visual_distance": min_visual,
        "min_copy_distance": min_copy,
        "coverage": axis,
        "perceptual_ok": perceptual_ok,
        "ok": (not style_rows or (min_visual >= 0.15 and min_copy >= 0.15))
              and perceptual_ok,
    }
    worlds = [((c.get("structure") or {}).get("creative_world") or {})
              for c in contracts]
    worlds = [w for w in worlds if w]
    if worlds:
        char_pairs = []
        for i in range(len(worlds)):
            for j in range(i + 1, len(worlds)):
                char_pairs.append({
                    "a": worlds[i].get("id"), "b": worlds[j].get("id"),
                    "distance": world_distance(worlds[i], worlds[j]),
                })
        semantic_worlds = semantic_audit(worlds)
        concept = {
            "enabled": True,
            "count": len(worlds),
            "unique_titles": len({w.get("title") for w in worlds}),
            "unique_premises": len({w.get("premise") for w in worlds}),
            "unique_devices": len({w.get("device") for w in worlds}),
            # 兼容旧字段：字面距离保留用于排查；主判断使用 semantic
            "min_distance": semantic_worlds["min_distance"],
            "pairs": semantic_worlds["pairs"],
            "char_min_distance": (
                min([x["distance"] for x in char_pairs], default=0)
                if len(worlds) >= 2 else 1.0),
            "char_pairs": char_pairs,
            "semantic": semantic_worlds,
        }
        concept["ok"] = (
            concept["unique_titles"] == len(worlds)
            and concept["unique_premises"] == len(worlds)
            and semantic_worlds["ok"])
    else:
        concept = {"enabled": False, "ok": True, "count": 0,
                   "semantic": {"ok": True, "count": 0}}
    semantic_contracts = contract_semantic_audit(contracts)
    semantic = {"worlds": concept.get("semantic") or {},
                "contracts": semantic_contracts,
                "ok": bool((concept.get("semantic") or {}).get("ok", True)
                           and semantic_contracts.get("ok", True))}
    return {
        "schema_version": "p0-audit/v0",
        "ok": (not anchor_errors and copy["ok"] and style["ok"]
               and concept["ok"] and semantic["ok"]),
        "anchor": {"ok": not anchor_errors, "errors": anchor_errors,
                   "claim_ids": dict(Counter(claim_ids))},
        "style": style,
        "copy": copy,
        "concept": concept,
        "semantic": semantic,
    }
