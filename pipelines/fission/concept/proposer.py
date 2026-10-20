"""CreativeWorld Proposer：让 LLM 发散候选世界，而不是直接写卖点。"""
from __future__ import annotations

import json

from ..jsonutil import extract_json


def _ops_text(operators: list[dict]) -> str:
    return "\n".join(
        f"- {o.get('name')}: {o.get('description')}" for o in operators)


def _default_llm():
    from orchestrator.app import reference_analysis as ra
    return ra._ref_llm(timeout=300)


def propose_worlds(anchor: dict, n_candidates: int,
                   operators: list[dict], llm=None) -> list[dict]:
    atoms = "\n".join(
        f"- {a['id']}: {a['fact']}" for a in anchor.get("claim_atoms") or [])
    prompt = f"""你是短视频创意总监。请为下面的商品提出 {n_candidates} 个
“创意世界”（CreativeWorld），不是卖点清单，也不是广告口号。

【商品锚点｜不可新增事实】
商品：{anchor.get('identity')}
品类：{anchor.get('category')}
必须出现：{json.dumps(anchor.get('must_show'), ensure_ascii=False)}
不得改变：{json.dumps(anchor.get('must_not_change'), ensure_ascii=False)}
可用事实原子（proof_rituals/claim_ids 只能引用这些）：
{atoms}
禁用主张：{json.dumps(anchor.get('forbidden_claims'), ensure_ascii=False)}

【生成算子｜只作灵感，不是固定分类】
{_ops_text(operators)}

每个世界输出：
{{
 "title": "一句话世界名",
 "premise": "谁/在哪/什么情境，发生什么",
 "tension": "旧做法/旧物/误区的代价或矛盾",
 "device": "让这个世界成立的具体装置/游戏/仪式/实验/角色关系",
 "turn": "中段发生什么变化或揭示",
 "payoff": "最后回到什么新的行为/感受",
 "scene": "一个可拍的场景",
 "props": ["最多 3 个道具"],
 "visual_motifs": ["2-3 个可重复的视觉母题"],
 "person_need": "on_body|hands|any",
 "proof_rituals": [
   {{"action":"可拍动作", "evidence":"对应商品证据", "claim_ids":["claim_01"]}}
 ],
 "claim_ids": ["claim_01", "feature_01"],
 "semantic": {{
   "social_frame": "2-8字，谁和谁/什么身份关系，要具体",
   "core_device": "2-12字，本世界最核心的装置/游戏名，必须是区分点",
   "core_action": "2-15字，最有辨识度的可拍动作",
   "proof_form": "2-10字，证明商品的方式",
   "visual_motif": "2-10字，反复出现的视觉母题",
   "turn_type": "2-12字，中段转折类型"
 }},
 "world_tags": ["自由标签"],
 "operator": "主要使用的算子名"
}}

硬要求：
1. 每个 world 必须是一个完整的小世界：premise → tension → device → turn → payoff；
2. 不能是“先讲卖点 A，再讲卖点 B”的换皮；商品只能通过 proof_rituals 出现；
3. 2-4 个 proof_rituals，每个动作必须可拍，且绑定 claim_id；
4. 至少 2 个 world 使用不同 operator；标题/前提不能互相近似；
5. 不能新增功效、价格、授权或治疗类表述；
6. person_need：需要真人上身用 on_body，只用桌面/手部用 hands，均可 any；
7. 不要写具体视频时长/字幕/机位，这些由后面的 StyleSpec 决定；
8. semantic 六个字段必须由你根据每个 world 生成，不能照抄示例、不能留空；
   core_device 在本批内必须彼此不同，不要用“展示/测试/使用”这类泛词；
   semantic 只描述创意结构，不要写商品卖点、功效或价格；
9. 只输出 JSON：{{"worlds":[...]}}"""
    llm = llm or _default_llm()
    for attempt in range(2):
        txt = llm.chat(
            prompt, max_tokens=16000, temperature=1.0, json_mode=True)
        data = extract_json(txt) or {}
        if isinstance(data, list):
            data = {"worlds": data}
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            data = data["payload"]
        worlds = [x for x in (data.get("worlds") or []) if isinstance(x, dict)]
        if worlds:
            return worlds
    return []
