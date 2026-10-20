"""DiversityPlanner：从 StyleAtlas 里用 seeded max-min 采样风格。

视觉风格和文案风格分开采样，再组合成 StyleSpec：
- 视觉风格决定人物/机位/场景/节奏/声音；
- 文案风格决定语气/人称/hook/句式/CTA。
这样不会因为参考池里“某条手部视频恰好配某种文案”而把两者锁死。
"""
from __future__ import annotations

import random

from .style_atlas import copy_distance, visual_distance


def _farthest(items: list[dict], n: int, distance, rng: random.Random) -> list[dict]:
    if not items or n <= 0:
        return []
    n = min(n, len(items))
    first = items[rng.randrange(len(items))]
    selected = [first]
    remaining = [x for x in items if x is not first]
    while remaining and len(selected) < n:
        best, best_score = None, -1.0
        for item in remaining:
            score = min(distance(item, s) for s in selected)
            # 用 rng 做轻微抖动，避免同分时永远选池子前面的
            score += rng.random() * 0.01
            if score > best_score:
                best, best_score = item, score
        selected.append(best)
        remaining.remove(best)
    return selected


def _feasibility(visual: dict, anchor: dict) -> dict:
    notes = []
    score = 1.0
    person = anchor.get("person") or {}
    allowed = set(anchor.get("allowed_person_visibility") or
                  ("full", "partial", "hands_only", "none"))
    pv = visual.get("person_visibility")
    if pv not in allowed:
        score = 0.0
        notes.append(f"person_visibility={pv} 不在 profile 允许范围 {sorted(allowed)}")
    if pv in ("full", "partial"):
        if not person.get("image"):
            score = 0.0
            notes.append("anchor 无人物图，不能选真人车道")
    if pv in ("hands_only", "none") and visual.get("presenter_mode") == "direct_speech":
        score = 0.0
        notes.append("无真人变量不能使用直接口播")
    proof = str(visual.get("proof_style") or "")
    views = {r.get("view") for r in anchor.get("references") or []}
    if any(x in proof for x in ("背面", "四排扣", "内里", "翻转")):
        if "back" not in views and "inner" not in views:
            score -= 0.35
            notes.append("缺背面/内里参考图，背面证明有商品漂移风险")
    return {"score": round(max(0.0, score), 3), "notes": notes}



def _counts(styles: list[dict]) -> dict:
    def vals(key, section):
        return sorted({str((x.get(section) or {}).get(key) or "") for x in styles
                       if (x.get(section) or {}).get(key)})
    return {
        "person_visibility": vals("person_visibility", "visual"),
        "presenter_mode": vals("presenter_mode", "visual"),
        "camera_family": vals("camera_family", "visual"),
        "scene_family": vals("scene_family", "visual"),
        "text_density": vals("text_density", "visual"),
        "copy_tone": vals("tone", "copy"),
        "copy_person": vals("person", "copy"),
    }


def _find_none_shot(atlas: dict) -> tuple[dict, dict] | None:
    for item in atlas.get("items") or []:
        for shot in item.get("shot_styles") or []:
            if shot.get("person_visibility") == "none":
                return item, shot
    return None


def _copy_for_tone(atlas: dict, used: set[str], fallback: dict) -> tuple[dict, str]:
    for item in atlas.get("items") or []:
        c = item.get("copy") or {}
        tone = str(c.get("tone") or "")
        if tone and tone not in used:
            return c, item.get("ref_id")
    return fallback, ""


def _synthetic(style_id: str, atlas: dict, base: dict, kind: str,
               used_tones: set[str]) -> dict:
    visual = dict(base.get("visual") or {})
    copy = {k: v for k, v in (base.get("copy") or {}).items()
            if k not in ("sample_hook", "sample_cta")}
    if kind == "static":
        shot_pair = _find_none_shot(atlas)
        shot_item, shot = shot_pair if shot_pair else (None, None)
        if shot_item:
            visual.update({
                "camera": shot_item["visual"].get("camera") or visual.get("camera"),
                "camera_family": shot.get("camera_family") or "tabletop",
                "scene": shot_item["visual"].get("scene") or visual.get("scene"),
                "scene_family": shot.get("scene_family") or "tabletop",
            })
        visual.update({
            "person_visibility": "none", "presenter_mode": "ambient",
            "text_density": "low", "pacing": "缓慢，静物陈列",
            "pacing_bucket": "slow",
            "audio_design": "无口播 + 环境音/操作音 + 轻 BGM",
        })
        copy_tone, copy_ref = _copy_for_tone(atlas, used_tones, copy)
        copy.update({
            "tone": copy_tone.get("tone") or "价格直给",
            "person": "none", "hook_type": "细节开场",
            "sentence_style": "关键词标签", "cta_style": "轻收口",
            "text_density": "low",
        })
        name = "静物环境音 · 覆盖合成"
        evidence = [shot.get("evidence_ref")] if shot else []
        parent_copy = copy_ref
    else:
        visual.update({
            "person_visibility": "hands_only", "presenter_mode": "text_only",
            "text_density": "medium",
            "audio_design": "无口播 + 轻 BGM/音效，字幕承载信息",
        })
        copy_tone, copy_ref = _copy_for_tone(atlas, used_tones, copy)
        copy.update({
            "tone": copy_tone.get("tone") or "结构评测",
            "person": "none", "hook_type": "细节开场",
            "sentence_style": "关键词标签", "cta_style": "轻收口",
            "text_density": "medium",
        })
        name = "手部字幕卡 · 覆盖合成"
        evidence = []
        parent_copy = copy_ref
    out = {
        "id": style_id,
        "name": name,
        "visual": visual,
        "copy": copy,
        "visual_signature": {k: visual.get(k) for k in
                             ("person_visibility", "presenter_mode",
                              "camera_family", "scene_family",
                              "pacing_bucket", "text_density")},
        "copy_signature": {k: copy.get(k) for k in
                           ("tone", "person", "hook_type", "sentence_style",
                            "cta_style", "text_density")},
        "evidence_refs": list(dict.fromkeys(
            evidence + list(base.get("evidence_refs") or []))),
        "parents": {"visual_ref": base.get("parents", {}).get("visual_ref"),
                    "copy_ref": parent_copy or base.get("parents", {}).get("copy_ref"),
                    "synthesized": kind},
        "generated_by": "coverage_synthesis",
    }
    return out


def _apply_coverage(styles: list[dict], atlas: dict, anchor: dict) -> tuple[list[dict], dict]:
    before = _counts(styles)
    used = set(before["copy_tone"])
    replaced = []
    allowed = set(anchor.get("allowed_person_visibility") or
                  ("full", "partial", "hands_only", "none"))
    if len(styles) >= 5:
        if "none" in allowed and "none" not in before["person_visibility"]:
            candidates = [i for i, x in enumerate(styles)
                          if (x.get("visual") or {}).get("person_visibility") == "hands_only"]
            idx = candidates[-1] if candidates else len(styles) - 1
            base = styles[idx]
            styles[idx] = _synthetic(styles[idx]["id"], atlas, base, "static", used)
            used.add(styles[idx]["copy"].get("tone") or "")
            replaced.append({"index": idx, "kind": "static"})
        if "hands_only" in allowed and "text_only" not in before["presenter_mode"]:
            candidates = [i for i, x in enumerate(styles)
                          if i not in {r["index"] for r in replaced}
                          and (x.get("visual") or {}).get("person_visibility") == "hands_only"]
            if not candidates:
                candidates = [i for i, x in enumerate(styles)
                              if i not in {r["index"] for r in replaced}
                              and (x.get("visual") or {}).get("person_visibility") == "full"]
            idx = candidates[-1] if candidates else len(styles) - 1
            base = styles[idx]
            styles[idx] = _synthetic(styles[idx]["id"], atlas, base, "text_only", used)
            used.add(styles[idx]["copy"].get("tone") or "")
            replaced.append({"index": idx, "kind": "text_only"})
        # 覆盖声音轴：5 条里要同时有同期声/画外音/无口播/环境音
        modes = {str((x.get("visual") or {}).get("presenter_mode") or "")
                 for x in styles}
        if "voiceover" not in modes and allowed & {"full", "partial", "hands_only"}:
            candidates = [i for i, x in enumerate(styles)
                          if i not in {r["index"] for r in replaced}
                          and (x.get("visual") or {}).get("presenter_mode") == "direct_speech"]
            if candidates:
                idx = candidates[-1]
                vis = styles[idx]["visual"]
                vis["presenter_mode"] = "voiceover"
                vis["audio_design"] = "画外口播 + 场景底噪 + 轻 BGM"
                styles[idx]["visual_signature"]["presenter_mode"] = "voiceover"
                styles[idx]["copy"]["person"] = "narrator"
                styles[idx]["copy_signature"]["person"] = "narrator"
                replaced.append({"index": idx, "kind": "voiceover_mutation"})
    after = _counts(styles)
    return styles, {"before": before, "after": after, "synthetic": replaced}

def plan_styles(atlas: dict, n: int, anchor: dict,
                seed: int | None = None,
                coverage: bool = True) -> dict:
    items = [x for x in (atlas.get("items") or [])
             if _feasibility(x.get("visual") or {}, anchor)["score"] > 0]
    if not items:
        raise ValueError("StyleAtlas 没有可用风格")
    seed = int(seed if seed is not None else random.SystemRandom().randrange(1, 10**9))
    rng = random.Random(seed)
    visuals = _farthest(items, n, visual_distance, rng)
    copies = _farthest(items, n, copy_distance, rng)
    styles = []
    coverage_info = {}
    for i in range(n):
        v = visuals[i % len(visuals)]
        c = copies[i % len(copies)]
        visual = dict(v["visual"])
        # sample_hook/sample_cta 只是池子证据，不能进入生成 prompt
        copy = {k: x for k, x in c["copy"].items()
                if k not in ("sample_hook", "sample_cta")}
        styles.append({
            "id": f"s{i + 1}",
            "name": f"{v['ref_id']} × {copy.get('tone')}",
            "visual": visual,
            "copy": copy,
            "visual_signature": dict(v["visual_signature"]),
            "copy_signature": dict(c["copy_signature"]),
            "evidence_refs": list(dict.fromkeys(
                (v.get("evidence_refs") or []) + (c.get("evidence_refs") or [])[:1])),
            "parents": {"visual_ref": v["ref_id"],
                        "copy_ref": c["ref_id"]},
            "feasibility": _feasibility(visual, anchor),
        })
    if coverage:
        styles, coverage_info = _apply_coverage(styles, atlas, anchor)
    distances = []
    for i in range(len(styles)):
        for j in range(i + 1, len(styles)):
            distances.append({
                "a": styles[i]["id"], "b": styles[j]["id"],
                "visual": visual_distance(
                    {"visual_signature": styles[i]["visual_signature"]},
                    {"visual_signature": styles[j]["visual_signature"]}),
                "copy": copy_distance(
                    {"copy_signature": styles[i]["copy_signature"]},
                    {"copy_signature": styles[j]["copy_signature"]}),
            })
    return {
        "schema_version": "style-plan/v0",
        "seed": seed,
        "count": len(styles),
        "styles": styles,
        "distances": distances,
        "coverage": coverage_info,
        "policy": {
            "method": "seeded_max_min",
            "visual_axes": ["person_visibility", "presenter_mode",
                            "camera_family", "scene_family",
                            "pacing_bucket", "text_density"],
            "copy_axes": ["tone", "person", "hook_type", "sentence_style",
                          "cta_style", "text_density"],
        },
    }
