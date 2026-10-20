"""Guidance Synth：brief + 全池 digest -> 本次临时 guidance。"""
from __future__ import annotations

import json

from orchestrator.app import reference_analysis as ra
from orchestrator.app.jsonutil import extract_json

from .io import envelope


def _ref_block(r: dict) -> str:
    g = r.get("global") or {}
    st = r.get("structure") or {}
    m = r.get("marketing") or {}
    lines = [
        f"### {r.get('ref_id')} | {r.get('category')} | {r.get('duration')}s",
        f"global: 场景={g.get('scene')}；风格={g.get('visual_style')}；"
        f"节奏={g.get('pacing')}；机位={g.get('camera_language')}；"
        f"商品={g.get('product')}",
        f"structure: hook={st.get('hook')}；beats={st.get('beat_order')}；"
        f"proof={st.get('proof')}；cta={st.get('cta')}",
        f"marketing: {'; '.join((m.get('observations') or [])[:3])}",
    ]
    shots = []
    for s in (r.get("shots") or [])[:8]:
        shots.append(f"{s.get('index')}: {s.get('shot_size')}/"
                     f"{s.get('camera')} | {str(s.get('action') or '')[:60]} | "
                     f"字幕:{str(s.get('on_screen_text') or '')[:50]}")
    lines.append("shots: " + " || ".join(shots))
    lines.append("transcript: " + str(r.get("transcript") or "")[:350])
    return "\n".join(lines)


def synthesize_guidance(brief: dict, digest: dict) -> dict:
    refs = (digest.get("payload") or {}).get("refs") or []
    context = "\n\n".join(_ref_block(r) for r in refs)
    bp = brief.get("payload") or brief
    n = int((bp.get("goal") or {}).get("deliverables") or 3)
    lane_count = max(8, min(12, n + 3))
    prompt = f"""视频池是整体指导，不是“找同类/找同风格”。请基于下面的商品 brief
和全部参考案例，归纳这次可用的 patterns、呈现车道和候选方向。

商品 brief：
{json.dumps(bp, ensure_ascii=False, indent=1)[:6000]}

参考案例（全池，按 ref_id 排列）：
{context[:24000]}

要求：
1. patterns 自由命名，不要用固定枚举；要可执行，不要形容词。
2. 每一条 pattern 写清楚：做什么、为什么、证据来自哪个 ref/shot/role、置信度。
3. presentation_lanes 是“同一条素材可以怎么拍”的呈现车道，不是内容方向。
   请从全池归纳 {lane_count} 条互不重复的车道，必须覆盖不同的人物呈现和声音呈现，
   不能全部写成“真人手持口播讲解”。
   - person_visibility 只能是 full / partial / hands_only / none；
   - presenter_mode 只能是 direct_speech / voiceover / ambient / text_only；
     其中 ambient=只有环境音/音效，text_only=无口播、主要靠字幕；
   - 每条车道写清机位、场景、证明方式、叙事装置、声音设计、字幕风格、节奏；
   - 每条车道必须有 evidence_refs（ref:shot），不要凭空发明品类。
4. 人物资产是可选手段：full/partial 才使用固定人物；hands_only/none 不得出现人脸。
   不要把所有车道都收敛成同一人物、同一场景、同一口播。
5. candidate_directions 给 3 个，必须落在不同车道上（开头/证明/人物/声音/场景至少两项不同）。
6. 不要编造商品事实、价格、功效；缺信息就写 open_questions。
7. 只输出 JSON：
{{
 "patterns": [{{"name":"", "description":"", "why":"",
                "evidence_refs":["ref-...:shot:3"], "confidence":0.0}}],
 "presentation_lanes": [
   {{"name":"", "summary":"",
     "person_visibility":"full|partial|hands_only|none",
     "presenter_mode":"direct_speech|voiceover|ambient|text_only",
     "camera_language":"", "scene":"", "lighting":"",
     "proof_style":"", "narrative_device":"", "audio_design":"",
     "text_style":"", "pacing":"",
     "evidence_refs":["ref-...:shot:3"], "confidence":0.0}}
 ],
 "candidate_directions": [{{"hypothesis":"", "rationale":"",
                            "evidence_refs":[]}}],
 "constraints": [],
 "open_questions": []
}}"""
    txt = ra._ref_llm(timeout=240).chat(
        prompt, max_tokens=9000, temperature=0.7, json_mode=True)
    data = extract_json(txt) or {}
    payload = {
        "brief_id": brief.get("id"),
        "patterns": data.get("patterns") or [],
        "presentation_lanes": data.get("presentation_lanes") or [],
        "candidate_directions": data.get("candidate_directions") or [],
        "constraints": data.get("constraints") or [],
        "open_questions": data.get("open_questions") or [],
    }
    return envelope(
        "guidance", "v0", f"guid-{brief.get('id', 'brief')}",
        "guidance_synth/v0", payload,
        refs=[brief.get("id"), digest.get("id")],
        provenance={"pool_refs": [r.get("ref_id") for r in refs]})
