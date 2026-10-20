"""Brief Synth：商品图 + profile + 用户文字 -> 动态 brief。"""
from __future__ import annotations

import json
from pathlib import Path

from orchestrator.app import reference_analysis as ra
from orchestrator.app.jsonutil import extract_json

from .io import envelope

ROOT = Path(__file__).resolve().parents[2]


def _profile_facts(profile: dict) -> list[dict]:
    facts = [
        {"key": "品类", "value": profile.get("category"), "source": "profile",
         "confidence": 1.0, "note": ""},
        {"key": "商品身份", "value": profile.get("identity"), "source": "profile",
         "confidence": 1.0, "note": ""},
    ]
    for i, x in enumerate(profile.get("must_show") or [], 1):
        facts.append({"key": f"必须出现{i}", "value": x, "source": "profile",
                      "confidence": 1.0, "note": ""})
    for i, x in enumerate(profile.get("claims") or [], 1):
        facts.append({"key": f"可用卖点{i}", "value": x, "source": "profile",
                      "confidence": 0.8, "note": "需与商品图/实物一致"})
    return facts


def synthesize_brief(profile: dict, text: str, deliverables: int = 3,
                     person_override: str | None = None) -> dict:
    product = profile["image"]
    person = person_override or (profile.get("person") or {}).get("image")
    if not person:
        raise ValueError("profile 缺少 person.image")
    prompt = f"""你是商品 brief 生成器。看商品图，结合商品 profile 和用户文字，
输出一份动态 brief，只输出 JSON。

用户文字：{text}
商品 profile：
{json.dumps(profile, ensure_ascii=False)[:5000]}
目标产出数量：{deliverables}

输出结构：
{{
 "product": {{"category_hint": "", "observed": {{}}, "user_provided": {{}}}},
 "facts": [{{"key":"", "value":"", "source":"user|image_observed|profile|inferred",
            "confidence":0.0, "note":""}}],
 "unknowns": [{{"key":"", "why":"", "question":"", "blocking":false}}],
 "assumptions": [],
 "constraints": {{"platform":"douyin", "language":"zh",
                  "claims_avoid":[], "color_policy":"",
                  "compliance_notes":[]}},
 "goal": {{"deliverables":{deliverables}, "duration_seconds":12,
           "media":"video", "archetype":"", "notes":""}}
}}

要求：
1. 区分图像观测/profile/用户提供/推断；不要编造价格、功效、授权。
2. 结合 profile 的 must_show/must_not_change/claims，但不要新增未提供的功效。
3. 未知项写清楚问题，本次测试不阻塞。
4. 只输出 JSON。"""
    txt = ra._ref_llm(timeout=180).chat_vision(
        prompt, [ROOT / product], max_tokens=4500, temperature=0.2,
        json_mode=True)
    data = extract_json(txt) or {}
    payload = data if isinstance(data, dict) else {}
    payload.setdefault("product", {})
    payload["product"]["image"] = product
    payload["product"].setdefault("category_hint", profile.get("category", ""))
    payload.setdefault("facts", [])
    payload.setdefault("unknowns", [])
    payload.setdefault("assumptions", [])
    payload.setdefault("constraints", {})
    payload.setdefault("goal", {})
    payload["goal"]["deliverables"] = deliverables
    payload["goal"].setdefault("duration_seconds", 12)
    payload["goal"].setdefault("media", "video")
    payload["goal"].setdefault("archetype", profile.get("default_archetype"))
    payload["assets"] = {
        "person": {
            "path": person,
            "authorization": (profile.get("person") or {}).get(
                "authorization", "unknown"),
        },
        "product": {"path": product},
    }
    c = payload["constraints"]
    c.setdefault("platform", (profile.get("constraints") or {}).get(
        "platform", "douyin"))
    c.setdefault("language", "zh")
    c.setdefault("claims_avoid", (profile.get("constraints") or {}).get(
        "claims_avoid", []))
    c.setdefault("compliance_notes", (profile.get("constraints") or {}).get(
        "compliance_notes", []))
    if not c.get("color_policy"):
        c["color_policy"] = profile.get("color_policy", "single")
    # 把 profile 已知事实并入，避免 LLM 漏掉
    have = {str(f.get("value")) for f in payload["facts"]
            if isinstance(f, dict)}
    for f in _profile_facts(profile):
        if f["value"] and f["value"] not in have:
            payload["facts"].append(f)
    # 测试版：不阻塞，显式假设
    assumptions = payload["assumptions"]
    if not any("价格" in str(x) or "price" in str(x).lower() for x in assumptions):
        assumptions.append(
            f"价格未提供；测试使用“{profile.get('offer', '活动价，点下方看')}”占位，"
            "正式使用需替换为真实价格")
    if not any("授权" in str(x) or "authorization" in str(x).lower()
               for x in assumptions):
        assumptions.append(
            f"人物授权状态：{(profile.get('person') or {}).get('authorization', 'unknown')}；"
            "正式使用需确认")
    if not any("颜色" in str(x) or "color" in str(x).lower() for x in assumptions):
        assumptions.append(
            f"颜色策略：{profile.get('color_policy', 'single')}；"
            "测试不主动扩展未确认的颜色")
    for u in payload["unknowns"]:
        if isinstance(u, dict):
            u["blocking"] = False
    return envelope(
        "brief", "v0", f"brief-{profile['product_id']}",
        "brief_synth/v0", payload,
        refs=[product, person],
        provenance={"profile": profile.get("product_id"),
                    "reference_id": profile.get("reference_id")})
