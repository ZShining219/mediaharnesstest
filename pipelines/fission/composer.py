"""Composer：ProductAnchor × StyleSpec -> 可执行契约 / H3 prompt。

原则：
- anchor 是硬约束，style 不能改商品事实；
- style 缺字段直接失败，不回落“真人口播/客厅”默认值；
- 文案只允许改写 anchor.claim_atoms，不允许新增事实。
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from .io import load_json, save_json
from .jsonutil import extract_json
from .ports import ComposerDeps

ROOT = Path(__file__).resolve().parents[2]


def _deps(deps: ComposerDeps | None) -> ComposerDeps:
    if deps is not None:
        return deps
    from .harness.local import default_composer_deps
    return default_composer_deps()


def _norm(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip("。！？!?，,；;：:")


def _times(beats: list[dict], duration: float = 12.0) -> list[list[float]]:
    n = len(beats)
    out, cursor, ok = [], 0.0, True
    for b in beats:
        t = b.get("time")
        try:
            a, z = float(t[0]), float(t[1])
        except Exception:
            ok = False
            break
        if abs(a - cursor) > 1e-6 or z <= a:
            ok = False
            break
        out.append([a, z])
        cursor = z
    if not ok or abs(cursor - duration) > 1e-6:
        step = duration / n
        out = [[round(i * step, 3), round((i + 1) * step, 3)]
               for i in range(n)]
    return out


def _claim_window(anchor: dict, style: dict, i: int) -> list[str]:
    """给每个变体分配不同的 claim 子集，避免所有变体围绕同一组事实写。"""
    atoms = anchor.get("claim_atoms") or []
    pv = (style.get("visual") or {}).get("person_visibility")
    if pv in ("hands_only", "none"):
        atoms = [a for a in atoms if a.get("safe_for_no_person")]
    pool = list(atoms)
    if not pool:
        return []
    order = list(range(len(pool)))
    random.Random(20261020 + i).shuffle(order)
    pool = [pool[j] for j in order]
    size = min(4, len(pool))
    start = ((i - 1) * 3) % len(pool)
    return [pool[(start + j) % len(pool)]["id"] for j in range(size)]


def _pick_ref(style: dict, catalog: dict, fallback: str | None) -> str:
    for x in style.get("evidence_refs") or []:
        rid = str(x).split(":")[0]
        if rid in catalog:
            return rid
    if fallback in catalog:
        return fallback
    return next(iter(catalog))


def _facet_brief(facet: dict) -> str:
    st = facet.get("structure") or {}
    lines = [
        f"ref_id={facet.get('ref_id')}",
        f"hook={st.get('hook')}",
        f"beat_order={st.get('beat_order')}",
        f"proof={st.get('proof')}",
        f"cta={st.get('cta')}",
        "shots:",
    ]
    for s in (facet.get("timeline") or [])[:8]:
        lines.append(
            f"- shot {s.get('index')}: {s.get('shot_size')}/{s.get('camera')} "
            f"| {str(s.get('action') or '')[:60]} "
            f"| text={str(s.get('on_screen_text') or '')[:40]}")
    return "\n".join(lines)


def _prompt(anchor: dict, style: dict, facet: dict, previous: dict,
            errors: list[str] | None = None,
            world: dict | None = None,
            brief: dict | None = None) -> str:
    atom_lines = "\n".join(
        f"- {a['id']} [{a['kind']}]: {a['fact']}"
        for a in anchor.get("claim_atoms") or [])
    prev = json.dumps(previous, ensure_ascii=False, indent=1)[:4500]
    err = ""
    if errors:
        err = "\n上一次输出有问题，必须修正：\n- " + "\n- ".join(errors)
    world_block = ""
    if world:
        world_block = f"""
【创意世界｜不是商品事实，不能改成卖点清单】
标题：{world.get('title')}
前提：{world.get('premise')}
冲突：{world.get('tension')}
装置：{world.get('device')}
转折：{world.get('turn')}
落点：{world.get('payoff')}
场景：{world.get('scene')}；道具/母题：{json.dumps(world.get('props') or [], ensure_ascii=False)} / {json.dumps(world.get('visual_motifs') or [], ensure_ascii=False)}
证明仪式：{json.dumps(world.get('proof_rituals') or [], ensure_ascii=False)}

"""
    user_note = ""
    notes = str((((brief or {}).get("payload") or {}).get("goal") or {})
                .get("notes") or "").strip()
    if notes:
        user_note = f"""
【用户补充要求｜不得改变商品事实】
{notes[:2000]}
这些要求只影响场景、动作、叙事或文案语气；不能新增卖点、功效、价格或授权。

"""
    return f"""你是带货短视频的分镜/文案生成器。你只输出 JSON，不输出解释。

【商品锚点｜不可改变】
商品：{anchor.get('identity')}（{anchor.get('category')}）
必须出现：{json.dumps(anchor.get('must_show'), ensure_ascii=False)}
不得改变：{json.dumps(anchor.get('must_not_change'), ensure_ascii=False)}
可用事实原子（claim_id 必须从这里选）：
{atom_lines}
本变体优先使用的 claim_ids：{json.dumps(style.get('claim_ids') or [], ensure_ascii=False)}
禁用主张：{json.dumps(anchor.get('forbidden_claims'), ensure_ascii=False)}
人物：{json.dumps(anchor.get('person'), ensure_ascii=False)}
参考图：{json.dumps(anchor.get('references'), ensure_ascii=False)}
{world_block}{user_note}
【本次风格｜不可改成默认口播】
{json.dumps(style, ensure_ascii=False, indent=1)}

【参考结构｜只借镜头语法/节奏，不继承它的商品和文案】
{_facet_brief(facet)}

【已生成文案｜必须避开精确重复】
{prev}
{err}

输出：
{{
 "name": "本变体一句话方向",
 "concept": "为什么它和同批其它变体结构/风格不同",
 "beats": [
   {{"index":1, "time":[0,3.0], "function":"hook",
     "function_label":"",
     "shot_size":"", "angle":"", "camera":"", "lighting":"",
     "composition":"", "action":"",
     "product_evidence":[""],
     "claim_id":"claim_01", "claim":"该事实的口语化改写（不得新增事实）",
     "proof":"",
     "text_overlay":"",
     "voiceover":"",
     "persona":"",
     "context":"",
     "offer_cta":"",
     "transition":"硬切",
     "source_beats":[1], "source_shots":[1]}}
 ]
}}

硬规则：
1. 3-6 个 beat；time 从 0 开始连续，总和 12 秒。
2. 每个 beat 必须有 claim_id、claim、proof、text_overlay、context；
   claim_id 只能来自上面的原子；claim 可以换句式和语气，但不得新增事实。
3. 商品证据：每个 beat 的 product_evidence 至少 1 项，来自 must_show；
   front/back/inner 视角按 style.scene / proof_style 选择。
4. 严格按风格执行，不得改回默认：
   - person_visibility=full：真人在场；partial：只在部分 beat 出脸；
     hands_only：画面只有手和商品；none：画面只有商品与场景陈设；
   - presenter_mode=direct_speech：同期声；voiceover：画外音；
     ambient：voiceover 必须为空；text_only：voiceover 必须为空，信息靠 text_overlay；
   - camera/scene/lighting/pacing/text_style 服从 style.visual；
   - copy.tone/person/hook_type/sentence_style/cta_style/text_density 服从 style.copy。
5. 文案必须像人说话，不要照抄 profile 原句；同一批不得复用上一批的 hook/CTA/口播原句，
   也不得复用 6 字以上连续短语；同一事实要换词、换句式，不能只换语气词。
6. 最后一个 beat 必须有 offer_cta；每条 CTA 措辞不同，只能用“活动价/点下方看”语义，
   不写具体金额。
7. source_beats/source_shots 必须落在参考结构的合法范围内。
8. 只输出 JSON。"""


def _parse_plan(txt: str) -> dict:
    data = extract_json(txt) or {}
    if isinstance(data, dict) and isinstance(data.get("payload"), dict):
        data = data["payload"]
    return data if isinstance(data, dict) else {}


def _generate_plan(anchor: dict, style: dict, facet: dict,
                   previous: dict, world: dict | None = None,
                   brief: dict | None = None, llm=None) -> dict:
    if llm is None:
        from .harness.local import LocalLLM
        llm = LocalLLM()
    errors = []
    for attempt in range(2):
        prompt = _prompt(anchor, style, facet, previous, errors, world, brief)
        txt = llm.chat(prompt, max_tokens=9000, temperature=0.8,
                       json_mode=True)
        plan = _parse_plan(txt)
        beats = plan.get("beats") if isinstance(plan.get("beats"), list) else []
        errors = []
        if not (3 <= len(beats) <= 6):
            errors.append(f"beats 数量必须 3-6，当前 {len(beats)}")
        atoms = {a["id"]: a for a in anchor.get("claim_atoms") or []}
        for b in beats:
            cid = str(b.get("claim_id") or "")
            info = b.get("information") or {}
            cid = cid or str(info.get("claim_id") or "")
            if cid not in atoms:
                errors.append(f"beat {b.get('index')} claim_id 不在原子列表: {cid}")
                continue
            assigned = set(style.get("claim_ids") or [])
            if assigned and cid not in assigned:
                errors.append(
                    f"beat {b.get('index')} claim_id={cid} 不在本变体分配范围")
            atom = atoms[cid]
            if (style["visual"]["person_visibility"] in ("hands_only", "none")
                    and not atom.get("safe_for_no_person")):
                errors.append(
                    f"beat {b.get('index')} 选用了需要真人的 claim: {cid}")
            if not str(b.get("proof") or info.get("proof") or "").strip():
                errors.append(f"beat {b.get('index')} 缺 proof")
            if not str(b.get("text_overlay") or "").strip():
                errors.append(f"beat {b.get('index')} 缺 text_overlay")
        last = beats[-1] if beats else {}
        if not str(last.get("offer_cta") or "").strip():
            errors.append("最后一个 beat 缺 offer_cta")
        voice = style["visual"]["presenter_mode"]
        if voice in ("direct_speech", "voiceover"):
            for b in beats:
                if not str(b.get("voiceover") or "").strip():
                    errors.append(f"beat {b.get('index')} 缺 voiceover")
        if not errors:
            plan["_facet_id"] = facet.get("ref_id")
            return plan
    raise ValueError("; ".join(errors[:8]))


def _shingles(text: str, n: int = 8) -> set[str]:
    s = re.sub(r"[^一-鿿A-Za-z0-9]", "", str(text or ""))
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def _duplicate_texts(plan: dict, previous: dict) -> list[str]:
    prev = {
        "claims": {_norm(x) for x in previous.get("claims") or []},
        "hooks": {_norm(x) for x in previous.get("hooks") or []},
        "voiceovers": {_norm(x) for x in previous.get("voiceovers") or []},
        "ctas": {_norm(x) for x in previous.get("ctas") or []},
        "texts": {_norm(x) for x in previous.get("texts") or []},
    }
    prev_blob = "".join(
        str(x) for k in ("claims", "voiceovers", "texts", "ctas")
        for x in previous.get(k) or [])
    dup = []
    beats = plan.get("beats") or []
    if beats:
        hook = _norm(beats[0].get("claim") or beats[0].get("text_overlay"))
        if hook and hook in prev["hooks"]:
            dup.append(f"hook={hook}")
    for b in beats:
        for key, bucket in (("claim", "claims"), ("voiceover", "voiceovers"),
                            ("text_overlay", "texts"), ("offer_cta", "ctas")):
            val = _norm(b.get(key))
            if val and val in prev[bucket]:
                dup.append(f"{bucket}={val}")
            for sh in _shingles(val):
                if sh in prev_blob:
                    dup.append(f"phrase={sh}")
    return list(dict.fromkeys(dup))


def _paraphrase_field(text: str, field: str, style: dict,
                      previous: dict, llm=None) -> str:
    if llm is None:
        from .harness.local import LocalLLM
        llm = LocalLLM()
    avoid = []
    for k in ("claims", "voiceovers", "texts", "ctas"):
        avoid.extend(str(x) for x in previous.get(k) or [] if x)
    prompt = f"""只改写下面这一句中文，保持事实和文案风格，不新增功效/价格/授权。
字段：{field}
原句：{text}
文案风格：{json.dumps(style.get('copy') or {}, ensure_ascii=False)}
必须避开这些已用句子/短语（不能原样复用）：
{json.dumps(avoid[-30:], ensure_ascii=False)}
要求：换词序、换喻体或换句式，不要只替换一两个词；只输出 JSON：{{"text":"..."}}"""
    for _ in range(3):
        txt = llm.chat(prompt, max_tokens=300, temperature=1.0,
                       json_mode=True)
        data = extract_json(txt) or {}
        out = str((data or {}).get("text") or "").strip()
        if out and _norm(out) != _norm(text) and _norm(out) not in {
                _norm(x) for x in avoid}:
            return out
    return text


def _rewrite_copy(plan: dict, style: dict, anchor: dict,
                  previous: dict, errors: list[str], llm=None) -> dict:
    if llm is None:
        from .harness.local import LocalLLM
        llm = LocalLLM()
    """只重写文案字段；首次生成已包含 claim_id/结构，避免整条重来。"""
    atoms = "\n".join(
        f"- {a['id']}: {a['fact']}"
        for a in anchor.get("claim_atoms") or [])
    prompt = f"""你只重写下面分镜里的文案，不改分镜结构、claim_id、商品证据、proof、机位/时间。

【必须避开的已用文本】
{json.dumps(previous, ensure_ascii=False, indent=1)[:5000]}

【要修正的问题】
- """ + "\n- ".join(errors[:8]) + f"""

【事实原子】
{atoms}

【文案风格】
{json.dumps(style.get('copy') or {}, ensure_ascii=False)}

【原分镜】
{json.dumps(plan, ensure_ascii=False, indent=1)[:12000]}

要求：
1. 保留每个 beat 的 index/time/claim_id/proof/product_evidence/机位/场景/动作；
2. 只改 claim / voiceover / text_overlay / offer_cta；
3. 每句都要换说法，不能与“已用文本”精确重复，也不能复用其中 6 字以上连续短语；
   不要只改一两个字，要换词序/换喻体/换句式；
4. claim 仍然只能表达对应 claim_id 的事实，不得新增功效/价格/授权；
5. 保持文案风格：tone/person/sentence_style/hook_type/cta_style；
6. 最后 beat 的 offer_cta 必须保留且改写成不同措辞；
7. 只输出完整 JSON，结构同原分镜。"""
    txt = llm.chat(prompt, max_tokens=9000, temperature=0.9,
                   json_mode=True)
    out = _parse_plan(txt)
    return out if out.get("beats") else plan


_CTA_FALLBACK = {
    "痛点否定": ["别纠结了，活动价点下方看", "先别急着买，点下方看活动价",
                 "看完再决定，活动价在下方"],
    "朋友安利": ["姐妹，活动价在下方，点开看", "喜欢就点下方，活动价自己看",
                 "下方有活动价，点开看看"],
    "结构评测": ["参数看完，活动价点下方", "细节都在这，活动价看下方",
                 "结构看完，点下方看活动价"],
    "价格直给": ["活动价在下方，点开看", "下方直接看活动价",
                 "价格放在下方，点开看"],
}


def _fix_exact_copy(plan: dict, style: dict, previous: dict,
                    llm=None) -> dict:
    beats = plan.get("beats") or []
    used = {
        "claims": {_norm(x) for x in previous.get("claims") or []},
        "voiceovers": {_norm(x) for x in previous.get("voiceovers") or []},
        "texts": {_norm(x) for x in previous.get("texts") or []},
    }
    for b in beats:
        for field, bucket in (("claim", "claims"), ("voiceover", "voiceovers"),
                              ("text_overlay", "texts")):
            val = _norm(b.get(field))
            if val and val in used[bucket]:
                b[field] = _paraphrase_field(
                    str(b.get(field) or ""), field, style, previous, llm)
    plan = dict(plan)
    plan["beats"] = beats
    return plan


def _rewrite_cta(plan: dict, style: dict, previous: dict,
                 llm=None) -> dict:
    if llm is None:
        from .harness.local import LocalLLM
        llm = LocalLLM()
    beats = plan.get("beats") or []
    if not beats:
        return plan
    used = {_norm(x) for x in previous.get("ctas") or []}
    tone = (style.get("copy") or {}).get("tone") or "产品说明"
    cta = ""
    for _ in range(3):
        prompt = f"""只写一条中文带货 CTA，20 字以内。
语义必须是“活动价/点下方看”，不能写具体金额，不能新增功效。
文案风格：{tone}。
必须避开这些已用 CTA（精确/近似）：
{json.dumps(sorted(used), ensure_ascii=False)}
只输出 JSON：{{"cta":"..."}}"""
        txt = llm.chat(prompt, max_tokens=200, temperature=1.0,
                       json_mode=True)
        data = extract_json(txt) or {}
        cta = str((data or {}).get("cta") or "").strip()
        if cta and _norm(cta) not in used:
            break
    if not cta or _norm(cta) in used:
        pool = _CTA_FALLBACK.get(tone) or ["活动价在下方，点开看",
                                           "点下方看看活动价"]
        cta = next((x for x in pool if _norm(x) not in used), pool[0])
    last = dict(beats[-1])
    last["offer_cta"] = cta
    if last.get("text_overlay"):
        last["text_overlay"] = cta
    beats[-1] = last
    plan = dict(plan)
    plan["beats"] = beats
    return plan


def _source_map(facet: dict, beat: dict, i: int) -> tuple[list[int], list[int]]:
    beats = [int(x.get("index") or 0)
             for x in (facet.get("structure") or {}).get("beats") or []]
    shots = [int(x.get("index") or 0) for x in (facet.get("timeline") or [])]
    pair = {}
    for p in ((facet.get("structure") or {})
              .get("beat_shot_alignment") or {}).get("pairs") or []:
        try:
            pair[int(p.get("beat_index"))] = [
                int(x) for x in (p.get("shot_indices") or [])]
        except Exception:
            continue
    sb = [int(x) for x in (beat.get("source_beats") or []) if int(x) in beats]
    if not sb:
        sb = [beats[i % len(beats)]] if beats else [1]
    aligned = []
    for bi in sb:
        aligned.extend(pair.get(bi) or [])
    aligned = [x for x in aligned if x in shots]
    ss = [int(x) for x in (beat.get("source_shots") or []) if int(x) in shots]
    if not ss:
        ss = aligned or ([shots[i % len(shots)]] if shots else [1])
    elif aligned and not (set(ss) & set(aligned)):
        ss = aligned
    return sb, ss


def _person_policy(style: dict, anchor: dict) -> tuple[str, str, set[int]]:
    v = style["visual"]
    pv = v["person_visibility"]
    person = anchor.get("person") or {}
    ident = person.get("identity") or "固定人物"
    scene = v.get("scene") or "场景"
    if pv == "full":
        policy = (f"真人在场：{ident}；{scene}；不要出现第二个人；"
                  "服装与场景按本次风格执行。")
    elif pv == "partial":
        policy = (f"只在部分 beat 真人出镜：{ident}；"
                  "其余 beat 只出现手部/商品，不出现脸；不要出现第二个人。")
    elif pv == "hands_only":
        policy = ("画面自始至终是手部商品特写：一双手在场景中操作商品，"
                  "镜头保持在手和商品；不要切到真人。")
    else:
        policy = ("画面自始至终是商品静物：商品在场景中陈列，"
                  "镜头保持在商品与陈设；不要切到真人或手部。")
    return policy, pv, set()


def _audio_policy(style: dict, person_beats: set[int] | None = None) -> str:
    v = style["visual"]
    mode = v["presenter_mode"]
    audio = v.get("audio_design") or ""
    if (mode == "direct_speech" and v.get("person_visibility") == "partial"
            and person_beats):
        base = ("H3 原生音频：有真人出镜的 beat 与台词口型同步；"
                "无人物 beat 为画外音；中文普通话；不要后期 TTS。")
    elif mode == "direct_speech":
        base = "H3 原生同步音频：真人与台词口型同步，中文普通话；不要后期 TTS。"
    elif mode == "voiceover":
        base = "H3 原生音频：画外音中文普通话；画面动作与台词节奏对齐，不强行生成口型；不要后期 TTS。"
    elif mode == "ambient":
        base = "H3 原生音频：声音只有环境底噪、操作音、轻音乐；不要口播、不要对白；不要后期 TTS。"
    else:
        base = "H3 原生音频：声音只有低音量 BGM 与操作音效；信息由后期字幕承载；不要后期 TTS。"
    return f"{base} 声音设计：{audio}。" if audio else base


def _text_policy(style: dict) -> tuple[bool, str]:
    v = style["visual"]
    density = v.get("text_density") or style["copy"].get("text_density")
    subtitles = True
    policy = (f"字幕密度 {density}；后期白字黑边、大字号、居中偏下，"
              "不要生成在画面里；无品牌 logo、无平台水印。")
    return subtitles, policy


def _negative(style: dict, anchor: dict) -> list[str]:
    v = style["visual"]
    pv = v["person_visibility"]
    pacing = v.get("pacing") or ""
    out = ["不要纯白影棚", "不要影楼背景", "不要产品目录感",
           "不要固定对称广告机位", "不要品牌logo", "不要平台水印",
           "商品不变形", "商品不变色", "不要简化商品结构/花纹/配色",
           "不要镜像漂移"]
    if "慢" not in pacing and "asmr" not in pacing.lower():
        out.append("不要慢动作")
    if pv == "full":
        out.extend(["不要无人物", "不要只有手部"])
    elif pv == "partial":
        out.append("不要全程真人")
    elif pv == "hands_only":
        out.append("镜头保持在桌面手部，不要切到真人")
    else:
        out.append("镜头保持在商品静物，不要切到真人")
    if anchor.get("color_policy") == "single":
        out.append(f"不要出现 {anchor.get('identity')} 之外的颜色/款式")
    return out


def _build_contract(anchor: dict, style: dict, plan: dict,
                    facet: dict, idx: int, brief: dict,
                    codec=None) -> dict:
    if codec is None:
        from .harness.local import LocalCodec
        codec = LocalCodec()
    v = style["visual"]
    c = style["copy"]
    pv = v["person_visibility"]
    mode = v["presenter_mode"]
    beats_in = plan.get("beats") or []
    if not (3 <= len(beats_in) <= 6):
        raise ValueError("beats 数量必须 3-6")
    atoms = {a["id"]: a for a in anchor.get("claim_atoms") or []}
    times = _times(beats_in)
    n = len(beats_in)
    person = anchor.get("person") or {}
    ident = person.get("identity") or "固定人物"
    person_hints = ("真人", "女性", "女主", "模特", "试穿", "上身",
                    "出镜", "面对镜头", "侧身", "背影")
    auto_person = set()
    for j, b in enumerate(beats_in, 1):
        info = b.get("information") or {}
        visual_text = " ".join(str(x or "") for x in (
            b.get("function_label"), b.get("action"), b.get("composition")))
        persona = str(b.get("persona") or info.get("persona") or "")
        if any(x in visual_text for x in person_hints):
            auto_person.add(j)
        elif (persona and any(x in persona for x in ("真人出镜", "女性出镜",
                                                     "模特出镜"))
              and not any(x in persona for x in ("画外音", "无人物"))):
            auto_person.add(j)
    if pv == "full":
        person_beats = set(range(1, n + 1))
    elif pv == "partial":
        person_beats = auto_person or {1, n}
    else:
        person_beats = set()
    beats = []
    for i, b in enumerate(beats_in):
        cid = str(b.get("claim_id") or (b.get("information") or {}).get(
            "claim_id") or "")
        atom = atoms.get(cid)
        if not atom:
            raise ValueError(f"beat {i + 1} claim_id 不在原子列表")
        if style.get("claim_ids") and cid not in style["claim_ids"]:
            raise ValueError(f"beat {i + 1} claim_id 不在本变体分配范围")
        if pv in ("hands_only", "none") and not atom.get("safe_for_no_person"):
            raise ValueError(f"beat {i + 1} 选用了需要真人的 claim")
        claim = str(b.get("claim") or atom["fact"]).strip()
        proof = str(b.get("proof") or (b.get("information") or {}).get("proof")
                    or (anchor.get("proof_points") or ["商品结构展示"])[i % max(1, len(anchor.get("proof_points") or ["商品结构展示"]))])
        text = str(b.get("text_overlay") or "").strip()
        if not text:
            raise ValueError(f"beat {i + 1} 缺 text_overlay")
        voice = str(b.get("voiceover") or "").strip()
        if mode in ("ambient", "text_only"):
            voice = ""
        elif not voice:
            raise ValueError(f"beat {i + 1} 缺 voiceover")
        if pv in ("hands_only", "none"):
            persona = ("画外音（画面只有手和商品）" if mode == "voiceover"
                       else "手部特写（画面只有手和商品）" if pv == "hands_only"
                       else "画外音（静物展示）" if mode == "voiceover"
                       else "静物展示（画面只有商品与陈设）")
        elif pv == "partial" and (i + 1) not in person_beats:
            persona = "画外音（画面只有手和商品）"
        else:
            persona = ident
        info = {
            "claim_id": cid,
            "claim": claim,
            "proof": proof,
            "text_overlay": text[:30],
            "voiceover": voice,
            "persona": persona,
            "context": str(b.get("context") or v.get("scene") or ""),
            "offer_cta": str(b.get("offer_cta") or "").strip(),
        }
        if i == n - 1 and not info["offer_cta"]:
            raise ValueError("最后一个 beat 缺 offer_cta")
        sb, ss = _source_map(facet, b, i)
        shot_map = {"close_up": "特写", "close": "近景", "medium": "中景",
                    "medium_close_up": "中近景", "full": "全景",
                    "wide": "全景", "extreme_close_up": "大特写",
                    "long": "远景"}
        cam_map = {"handheld": "手机竖屏手持，轻微晃动",
                   "static": "固定机位", "fixed": "固定机位",
                   "tripod": "三脚架固定机位",
                   "tabletop": "固定俯拍桌面", "macro": "微距特写",
                   "moving": "缓慢推拉/跟拍", "multi": "多机位交替"}
        raw_shot = str(b.get("shot_size") or "medium")
        raw_cam = str(b.get("camera") or "").lower()
        cam_key = next((k for k in cam_map if raw_cam.startswith(k)), None)
        beats.append({
            "index": i + 1,
            "function": str(b.get("function") or (
                "hook" if i == 0 else "cta" if i == n - 1 else "proof")),
            "function_label": str(b.get("function_label") or (
                "开场钩子" if i == 0 else "收尾/CTA" if i == n - 1 else "信息/证明")),
            "time": times[i],
            "duration": round(times[i][1] - times[i][0], 3),
            "shot_size": shot_map.get(raw_shot, raw_shot),
            "angle": str(b.get("angle") or "平视"),
            "camera": (v.get("camera") if cam_key
                       else b.get("camera") or v.get("camera") or ""),
            "lighting": str(b.get("lighting") or v.get("lighting") or ""),
            "composition": str(b.get("composition") or ""),
            "action": str(b.get("action") or ""),
            "product_evidence": list(b.get("product_evidence") or
                                     anchor.get("must_show")[:3]),
            "on_screen_text": text,
            "transition": str(b.get("transition") or "硬切"),
            "information": info,
            "source": {
                "ref_id": facet.get("ref_id"),
                "beat_indices": sb, "shot_indices": ss,
                "fields_used": ["shot_size", "camera", "action",
                                "on_screen_text"],
                "overrides": ["商品锚点", "风格规格", "文案改写"],
                "note": "只借参考结构；商品事实来自 anchor，风格来自 style",
            },
        })

    refs = []
    product_start = 2 if pv in ("full", "partial") else 1
    if pv in ("full", "partial"):
        refs.append({"index": 1, "kind": "person", "label": "固定人物照片1",
                     "path": person.get("image"),
                     "policy": "只保留人物身份；忽略原服装、背景；按风格更换。"})
    for j, r in enumerate(anchor.get("references") or []):
        refs.append({
            "index": product_start + j, "kind": "product",
            "label": f"{r.get('label')}（{r.get('view')}）",
            "path": r["path"], "policy": r.get("policy") or ""})
    target = {
        "ref_id": anchor.get("reference_id"),
        "references": refs,
        "product": {
            "symbol": "<Product 1>",
            "reference_index": product_start,
            "identity": anchor.get("identity"),
            "description": anchor.get("description"),
            "image": anchor.get("references")[0]["path"],
            "reference_policy": anchor.get("references")[0].get("policy") or "",
            "must_show": anchor.get("must_show") or [],
            "must_not_change": anchor.get("must_not_change") or [],
            "wear_state": anchor.get("wear_state") or (
                "第一人称手部拿持/翻转" if pv == "hands_only"
                else "商品静物陈列" if pv == "none"
                else "真人手持/上身展示，服装与场景按本次风格执行"),
            "matching": "不新增商品图之外的服装部件。",
        },
        "format": {
            "duration": 12, "aspect_ratio": "9:16", "resolution": "768P",
            "pacing": v.get("pacing") or "",
            "archetype": anchor.get("archetype") or "ugc_individual_seller",
            "voiceover": mode in ("direct_speech", "voiceover"),
            "subtitles": True,
            "native_audio": True,
            "presentation": {
                "name": plan.get("name") or style.get("name"),
                "summary": plan.get("concept") or plan.get("name") or "",
                **{k: v.get(k) for k in (
                    "person_visibility", "presenter_mode", "camera",
                    "camera_family", "scene", "scene_family", "lighting",
                    "pacing", "pacing_bucket", "text_style", "text_density",
                    "proof_style", "narrative_device", "audio_design")},
                "person_beats": sorted(person_beats),
            },
            "copy": dict(c),
        },
    }
    if pv in ("full", "partial"):
        target["person"] = {
            "symbol": "<Person 1>", "reference_index": 1,
            "identity": ident,
            "immutable": person.get("immutable") or
            ["脸型", "发型", "体型", "肤色"],
            "policy": person.get("policy") or "",
        }
    person_policy, _, _ = _person_policy(style, anchor)
    audio_policy = _audio_policy(style, person_beats)
    subtitles, text_policy = _text_policy(style)
    ctxs = {str((b.get("information") or {}).get("context") or "")
            for b in beats}
    counts = {
        "claims": sum(1 for b in beats if (b["information"].get("claim"))),
        "proofs": sum(1 for b in beats if (b["information"].get("proof"))),
        "text_overlays": sum(1 for b in beats if (b["information"].get("text_overlay"))),
        "voiceovers": sum(1 for b in beats if (b["information"].get("voiceover"))),
        "personas": sum(1 for b in beats if (b["information"].get("persona"))),
        "contexts": max(1, len(ctxs)),
        "offer_cta": sum(1 for b in beats if (b["information"].get("offer_cta"))),
    }
    contract = {
        "schema_version": "fission-contract/v1-p0",
        "slice_id": f"{anchor['product_id']}-p0-v{idx:02d}-{style['id']}",
        "target": target,
        "structure": {
            "creative_world": style.get("creative_world"),
            "name": str(plan.get("name") or style.get("name"))[:40],
            "concept": str(plan.get("concept") or ""),
            "hook": {"time": [times[0][0], min(1.5, times[0][1])],
                     "description": beats[0]["action"] or beats[0]["information"]["claim"]},
            "copy_profile": dict(c),
            "style_id": style["id"],
            "beats": beats,
        },
        "global": {
            "scene": f"{v.get('scene')}；不要纯白影棚、不要影楼背景。",
            "lighting": f"{v.get('lighting')}；保持 UGC 实拍质感，不过度磨皮。",
            "camera": f"{v.get('camera')}；机位/运动按本次风格执行。",
            "person_policy": person_policy,
            "audio_policy": audio_policy,
            "text_policy": text_policy,
            "negative": _negative(style, anchor),
        },
        "information_budget": counts,
        "facet_coverage": {
            "used": [
                {"facet": f"{facet.get('ref_id')}.structure",
                 "value": "镜头语法/结构", "why": "风格采样到的主参考"},
                {"facet": "anchor.claim_atoms", "value": "商品事实"},
                {"facet": "style_atlas", "value": style.get("name"),
                 "why": "视觉/文案风格属性"},
            ],
            "adapted": [
                {"facet": "pool.copy", "value": c.get("tone"),
                 "why": "文案风格从池子采样，不照抄原句"},
            ],
            "waived": [
                {"facet": "price", "value": "具体金额",
                 "why": "未提供真实价格，只用占位 CTA"},
            ],
        },
        "negative": [],
        "provenance": {
            "anchor": anchor["product_id"],
            "style_id": style["id"],
            "style_parents": style.get("parents"),
            "facet": f"data/reference_facets/{facet.get('ref_id')}.json",
            "brief": brief.get("id"),
        },
    }
    val = codec.validate(contract, facet)
    contract["_validation"] = val
    if not val["ok"]:
        raise ValueError("契约校验失败: " + "; ".join(val["errors"]))
    return contract


def _write(out: Path, contract: dict, facet: dict, codec=None) -> None:
    if codec is None:
        from .harness.local import LocalCodec
        codec = LocalCodec()
    out.mkdir(parents=True, exist_ok=True)
    save_json(out / "contract.json", contract)
    (out / "prompt_h3.txt").write_text(
        codec.render_prompt(contract), encoding="utf-8")
    (out / "prompt_audit.md").write_text(
        codec.render_audit(contract, facet), encoding="utf-8")
    fmt = contract["target"]["format"]
    info = [b["information"] for b in contract["structure"]["beats"]]
    voice = "。".join(
        str(x.get("voiceover") or "").strip().rstrip("。")
        for x in info if x.get("voiceover"))
    voice = (voice + "。") if voice and fmt.get("voiceover") else ""
    if voice:
        (out / "voiceover.txt").write_text(voice + "\n", encoding="utf-8")
    else:
        (out / "voiceover.txt").unlink(missing_ok=True)
    text = voice or "。".join(
        str(x.get("text_overlay") or "").strip().rstrip("。")
        for x in info if x.get("text_overlay"))
    codec.text_to_srt(text, float(fmt.get("duration") or 12),
                      out / "subtitles.srt")


def diversify_copy(contracts: list[dict], anchor: dict, plan: dict,
                   out_root: Path, deps: ComposerDeps | None = None) -> list[dict]:
    deps = _deps(deps)
    """批量文案编辑：看到全部变体后统一去重，保留事实与每条风格。"""
    if len(contracts) < 2:
        return contracts
    payload = []
    for i, c in enumerate(contracts, 1):
        payload.append({
            "id": f"v{i:02d}",
            "style": (c.get("structure") or {}).get("copy_profile"),
            "world": (c.get("structure") or {}).get("creative_world"),
            "beats": [
                {"index": b.get("index"),
                 "claim_id": (b.get("information") or {}).get("claim_id"),
                 "claim": (b.get("information") or {}).get("claim"),
                 "voiceover": (b.get("information") or {}).get("voiceover"),
                 "text_overlay": (b.get("information") or {}).get("text_overlay"),
                 "offer_cta": (b.get("information") or {}).get("offer_cta")}
                for b in (c.get("structure") or {}).get("beats") or []
            ],
        })
    prompt = f"""你是同一批带货素材的文案编辑。下面 {len(contracts)} 条变体的画面/风格已经不同，
但文案可能复用同一套句式。请只重写文案，让每条听起来像不同的人、不同栏目。

【商品事实原子｜不可新增/改写事实】
{json.dumps(anchor.get('claim_atoms'), ensure_ascii=False)}

【必须保留】
- 每条变体的 claim_id、beat 数、时间、证明、商品证据、画面动作、创意世界不变；
- 每条变体的 copy 风格（tone/person/hook_type/sentence_style/cta_style）不变；
- 商品名/结构名词（蕾丝、包边、四排扣、肩带、内里软支撑）可以复用；
- 精确句子不得跨变体复用；6 字以上通用句式/口头禅也不得复用。

【当前文案】
{json.dumps(payload, ensure_ascii=False, indent=1)[:18000]}

要求：
1. 每条都用不同的开场公式、句长和用词；不能只把“姐妹”换成“宝子”；
2. 每条 CTA 措辞不同；
3. 只输出 JSON：
{{"variants":[{{"id":"v01","beats":[{{"index":1,"claim":"","voiceover":"","text_overlay":"","offer_cta":""}}]}}]}}"""
    txt = deps.llm.chat(prompt, max_tokens=14000, temperature=0.95,
                        json_mode=True)
    data = extract_json(txt) or {}
    rows = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return contracts
    by_id = {str(r.get("id")): r for r in rows if isinstance(r, dict)}
    for i, c in enumerate(contracts, 1):
        row = by_id.get(f"v{i:02d}")
        if not row:
            continue
        new_beats = {int(b.get("index")): b for b in row.get("beats") or []
                     if isinstance(b, dict) and b.get("index") is not None}
        for b in (c.get("structure") or {}).get("beats") or []:
            nb = new_beats.get(int(b.get("index")))
            if not nb:
                continue
            info = b.setdefault("information", {})
            for key in ("claim", "voiceover", "text_overlay", "offer_cta"):
                if key in nb and nb.get(key) is not None:
                    info[key] = str(nb.get(key)).strip()
            text = info.get("text_overlay") or info.get("claim") or ""
            b["on_screen_text"] = text
        ref = ((c.get("provenance") or {}).get("facet") or "")
        rid = Path(ref).stem if ref else None
        if rid:
            facet = deps.facets.get(rid)
            fmt = (c.get("target") or {}).get("format") or {}
            if not fmt.get("voiceover"):
                for b in (c.get("structure") or {}).get("beats") or []:
                    (b.setdefault("information", {}))["voiceover"] = ""
            c["_validation"] = deps.codec.validate(c, facet)
            _write(out_root / f"v{i:02d}", c, facet, deps.codec)
    return contracts


def compose_batch(anchor: dict, brief: dict, plan: dict, catalog: dict,
                  out_root: Path, deps: ComposerDeps | None = None) -> list[dict]:
    deps = _deps(deps)
    out_root.mkdir(parents=True, exist_ok=True)
    save_json(out_root / "anchor.json", anchor)
    save_json(out_root / "brief.json", brief)
    save_json(out_root / "style_plan.json", plan)
    previous = {"hooks": [], "claims": [], "voiceovers": [], "ctas": [],
                "texts": []}
    contracts = []
    for i, style in enumerate(plan["styles"], 1):
        style = dict(style)
        world = style.get("creative_world")
        assigned = _claim_window(anchor, style, i)
        if world and world.get("claim_ids"):
            world_ids = [x for x in world["claim_ids"]
                         if x in {a["id"] for a in anchor.get("claim_atoms") or []}]
            if style["visual"]["person_visibility"] in ("hands_only", "none"):
                safe = {a["id"] for a in anchor.get("claim_atoms") or []
                        if a.get("safe_for_no_person")}
                world_ids = [x for x in world_ids if x in safe]
            assigned = list(dict.fromkeys(world_ids + assigned))
        style["claim_ids"] = assigned[:4]
        rid = _pick_ref(style, catalog, anchor.get("reference_id"))
        facet = deps.facets.get(rid)
        last_err = None
        for attempt in range(2):
            try:
                p = _generate_plan(anchor, style, facet, previous, world,
                                   brief, deps.llm)
                dups = _duplicate_texts(p, previous)
                if dups:
                    p = _rewrite_copy(p, style, anchor, previous, dups,
                                      deps.llm)
                    dups = _duplicate_texts(p, previous)
                if any(not x.startswith("phrase=") for x in dups):
                    p = _fix_exact_copy(p, style, previous, deps.llm)
                    dups = _duplicate_texts(p, previous)
                if any(x.startswith("ctas=") for x in dups):
                    p = _rewrite_cta(p, style, previous, deps.llm)
                    dups = _duplicate_texts(p, previous)
                if any(not x.startswith("phrase=") for x in dups):
                    raise ValueError("文案仍重复: " + "; ".join(dups[:5]))
                c = _build_contract(anchor, style, p, facet, i, brief,
                                    deps.codec)
                out = out_root / f"v{i:02d}"
                _write(out, c, facet, deps.codec)
                contracts.append(c)
                info = [b["information"] for b in c["structure"]["beats"]]
                previous["hooks"].append(info[0].get("claim"))
                previous["claims"].extend(x.get("claim") for x in info)
                previous["voiceovers"].extend(x.get("voiceover") for x in info)
                previous["texts"].extend(x.get("text_overlay") for x in info)
                previous["ctas"].extend(x.get("offer_cta") for x in info
                                        if x.get("offer_cta"))
                for k in previous:
                    previous[k] = list(dict.fromkeys(
                        str(x) for x in previous[k] if x))[-20:]
                break
            except Exception as e:
                last_err = e
        else:
            raise RuntimeError(f"style {style['id']} 生成失败: {last_err}")
    save_json(out_root / "contracts.json", {
        "schema_version": "p0-contract-set/v0",
        "count": len(contracts),
        "contracts": [f"v{i:02d}/contract.json" for i in range(1, len(contracts) + 1)],
    })
    return contracts
