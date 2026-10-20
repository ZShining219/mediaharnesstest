"""Variant Gen：brief + guidance + 动态锚点 -> N 个不同呈现车道的变体。

关键不是让 LLM “自由发挥”，而是先锁定 N 条互不重复的呈现车道
（真人口播 / 画外音手部 / 纯手部 ASMR / 静物 / 字幕卡 / 穿搭等），
再让每个变体在自己车道内写 beats。否则 LLM 会收敛成同一种口播讲解。
"""
from __future__ import annotations

import json

from orchestrator.app import reference_analysis as ra
from orchestrator.app.jsonutil import extract_json

from .io import envelope
from .pool import anchor_lines

LANE_KEYS = (
    "person_visibility", "presenter_mode", "camera_language", "scene",
    "proof_style", "narrative_device", "audio_design", "text_style",
)
LANE_WEIGHTS = {
    "person_visibility": 6, "presenter_mode": 6, "camera_language": 3,
    "scene": 2, "proof_style": 2, "narrative_device": 2,
    "audio_design": 1, "text_style": 1,
}


def _lane_value(lane: dict, key: str) -> str:
    return str(lane.get(key) or "").strip()


def _valid_lanes(guidance: dict) -> list[dict]:
    payload = guidance.get("payload") or guidance
    out = []
    for lane in payload.get("presentation_lanes") or []:
        if not isinstance(lane, dict) or not _lane_value(lane, "name"):
            continue
        if _lane_value(lane, "person_visibility") not in (
                "full", "partial", "hands_only", "none"):
            continue
        if _lane_value(lane, "presenter_mode") not in (
                "direct_speech", "voiceover", "ambient", "text_only"):
            continue
        out.append(lane)
    return out


def select_lanes(guidance: dict, n: int) -> list[dict]:
    """贪心选车道：优先覆盖没出现过的人物呈现/声音呈现/机位/场景。"""
    remaining = list(_valid_lanes(guidance))
    chosen: list[dict] = []
    seen: dict[str, set[str]] = {k: set() for k in LANE_KEYS}
    while remaining and len(chosen) < n:
        best, best_score = None, -1
        for lane in remaining:
            score = sum(
                weight for key, weight in LANE_WEIGHTS.items()
                if _lane_value(lane, key)
                and _lane_value(lane, key) not in seen[key])
            if score > best_score:
                best, best_score = lane, score
        if best is None:
            break
        chosen.append(best)
        remaining.remove(best)
        for key in LANE_KEYS:
            if _lane_value(best, key):
                seen[key].add(_lane_value(best, key))
    return chosen


def _diversity_audit(variants: list[dict]) -> dict:
    lanes = []
    for v in variants:
        fp = v.get("format_profile") or {}
        lanes.append({k: _lane_value(fp, k) for k in LANE_KEYS})
    signatures = [tuple(x[k] for k in LANE_KEYS) for x in lanes]
    names = [_lane_value(v.get("format_profile") or {}, "name")
             for v in variants]
    pairs = []
    for i in range(len(lanes)):
        for j in range(i + 1, len(lanes)):
            diff = [k for k in LANE_KEYS
                    if lanes[i].get(k) != lanes[j].get(k)]
            pairs.append({"a": i + 1, "b": j + 1,
                          "different_axes": diff,
                          "different_count": len(diff)})
    unique_names = len(set(x for x in names if x))
    return {
        "ok": unique_names == len(variants) and all(
            p["different_count"] >= 2 for p in pairs),
        "unique_lanes": unique_names,
        "variant_count": len(variants),
        "pairs": pairs,
        "lanes": lanes,
    }


def _lane_prompt_rows(lanes: list[dict]) -> str:
    rows = []
    for i, lane in enumerate(lanes, 1):
        rows.append(f"变体 v{i} 锁定车道：\n"
                    f"{json.dumps(lane, ensure_ascii=False, indent=1)}")
    return "\n\n".join(rows)


def generate_variants(brief: dict, guidance: dict, digest: dict,
                      n: int = 3) -> dict:
    payload = brief.get("payload") or brief
    lanes = select_lanes(guidance, n)
    lane_rows = _lane_prompt_rows(lanes) if lanes else (
        "guidance 没有结构化 presentation_lanes：请自行创建 "
        f"{n} 条互不重复的呈现车道，并写进每个变体的 format_profile。")
    prompt = f"""根据 brief + guidance，生成 {n} 个真正不同的裂变变体。
本批已经预先选定呈现车道；每个变体必须锁定自己的车道，不得全部收敛成
“真人手持口播讲解”。

商品 brief：
{json.dumps(payload, ensure_ascii=False, indent=1)[:6000]}

guidance：
{json.dumps(guidance.get("payload") or guidance, ensure_ascii=False, indent=1)[:9000]}

{lane_rows}

可用 primary_ref（动态来自池子；source_beats / source_shots 必须落在对应范围内）：
{anchor_lines(digest)[:12000]}

每个变体输出：
{{
 "id": "v1",
 "hypothesis": "这个变体赌什么（一句话）",
 "rationale": "为什么可能有效",
 "differentiators": ["与其它变体不同的地方"],
 "primary_ref": "ref-...",
 "format_profile": {{
   "name": "车道名", "summary": "这条怎么拍",
   "person_visibility": "full|partial|hands_only|none",
   "presenter_mode": "direct_speech|voiceover|ambient|text_only",
   "camera_language": "", "scene": "", "lighting": "",
   "proof_style": "", "narrative_device": "", "audio_design": "",
   "text_style": "", "pacing": "",
   "person_beats": [1]
 }},
 "plan": {{"deliverable_type":"video", "duration_seconds":12,
           "dynamic_attributes": {{}}}},
 "beats": [
   {{"index":1, "time":[0,2.5], "function":"hook",
     "function_label":"",
     "shot_size":"medium", "angle":"平视",
     "camera":"", "lighting":"", "composition":"", "action":"",
     "product_evidence":[],
     "on_screen_text":"", "transition":"硬切",
     "information":{{"claim":"", "proof":"", "text_overlay":"",
                     "voiceover":"", "persona":"", "context":"",
                     "offer_cta":""}},
     "source_beats":[1], "source_shots":[1]}}
 ],
 "evidence_refs":[]
}}

硬要求：
1. 每个变体 3-5 个 beat；time 从 0 开始、连续、总和 12 秒。
2. 每个 beat 必须有 claim/proof/text_overlay/context；最后一个 beat 必须有 offer_cta。
3. 口播严格按车道：
   - direct_speech：真人同期声，voiceover 写台词；
   - voiceover：画外女声，voiceover 写台词，人物可以不出镜；
   - ambient：只保留环境音/操作音/BGM，voiceover 必须是空字符串；
   - text_only：无口播，voiceover 空字符串，信息由 text_overlay 承载。
4. persona 严格按车道：
   - full/partial：写固定人物身份；partial 用 person_beats 指定哪几个 beat 出脸；
   - hands_only：写“无人物（仅手部）”，不得出现脸/身体；
   - none：写“无人物（静物）”，不得出现人物或手部；
   - 画外音车道可写“画外女声”。
5. 人物资产只在 full/partial 使用；hands_only/none 不得为了“收尾”强行加真人。
6. 每个变体必须与同批其它变体在车道、开头、证明方式、机位、场景、声音中
   至少 3 项不同；differentiators 要逐条写清。
7. 商品颜色按 brief.constraints.color_policy；不要编造功效、价格、授权；
   CTA 只能用“活动价/点下方看”这类占位，不写具体金额。
8. primary_ref 必须来自上面的动态列表；source_beats/source_shots 必须在范围内。
9. 只输出 JSON：{{"variants":[...]}}"""
    def _parse(text: str) -> list[dict]:
        data = extract_json(text) or {}
        if isinstance(data, list):
            data = {"variants": data}
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            data = data["payload"]
        return [v for v in (data.get("variants")
                            or data.get("items") or [])
                if isinstance(v, dict)][:n]

    max_tokens = min(30000, 6000 + n * 3000)
    txt = ra._ref_llm(timeout=300).chat(
        prompt, max_tokens=max_tokens, temperature=0.85, json_mode=True)
    variants = _parse(txt)
    if not variants:
        print("[variants] empty parse; raw head:", txt[:2000], flush=True)
        txt = ra._ref_llm(timeout=300).chat(
            prompt, max_tokens=max_tokens, temperature=0.55, json_mode=True)
        variants = _parse(txt)
    if not variants:
        print("[variants] retry raw head:", txt[:2000], flush=True)
        raise ValueError("variant gen 返回 0 个变体；检查 LLM JSON/长度限制")
    # 强制锁定预先选好的车道，避免 LLM 又把所有变体写成同一种口播
    for i, v in enumerate(variants):
        if i >= len(lanes):
            continue
        fp = dict(v.get("format_profile") or {})
        for key in ("name", "summary", *LANE_KEYS):
            if lanes[i].get(key):
                fp[key] = lanes[i][key]
        if "person_beats" in lanes[i]:
            fp["person_beats"] = lanes[i].get("person_beats")
        if lanes[i].get("evidence_refs"):
            fp["evidence_refs"] = lanes[i]["evidence_refs"]
        v["format_profile"] = fp
    audit = _diversity_audit(variants)
    out = {
        "brief_id": brief.get("id"),
        "guidance_id": guidance.get("id"),
        "variants": variants,
        "presentation_lanes": lanes,
        "diversity": {"method": "lane_plan+llm",
                      "audit": audit,
                      "notes": "按呈现车道生成；audit 为确定性检查"},
    }
    return envelope("variant_set", "v0", f"varset-{brief.get('id', 'brief')}",
                    "variant_gen/v1", out,
                    refs=[brief.get("id"), guidance.get("id")])
