"""Contract adapters：把 variant 变成可执行契约。

通用 contract 只有 beats/attributes/constraints；这里 UGC adapter 解释
claim/proof/text/voice/persona/context/CTA。
商品常量全部来自 profile，不再写死在代码里。
"""
from __future__ import annotations

from .io import load_json

ROOT = None  # 由调用方传入 facet；避免循环 import


def _has_person(beat: dict) -> bool:
    persona = str((beat.get("information") or {}).get("persona") or "")
    if any(k in persona for k in ("无人物", "手部", "产品特写")):
        return False
    return any(k in persona for k in ("真人", "主播", "人物", "女性"))


def _valid_indices(facet: dict) -> tuple[list[int], list[int]]:
    beats = [int(b.get("index") or 0)
             for b in (facet.get("structure") or {}).get("beats") or []]
    shots = [int(s.get("index") or 0) for s in (facet.get("timeline") or [])]
    return [x for x in beats if x], [x for x in shots if x]


def choose_primary_ref(variant: dict, catalog: dict[str, dict],
                       fallback: str | None = None) -> str:
    candidates = []
    for x in (variant.get("evidence_refs") or []):
        candidates.append(str(x).split(":")[0])
    if variant.get("primary_ref"):
        candidates.append(str(variant["primary_ref"]).split(":")[0])
    for rid in candidates:
        if rid in catalog:
            return rid
    if fallback and fallback in catalog:
        return fallback
    return next(iter(catalog))


class Adapter:
    name = "generic/v0"

    def build_contract(self, variant: dict, brief: dict, profile: dict,
                       facet: dict, idx: int) -> dict:
        raise NotImplementedError


class UGCIndividualSellerAdapter(Adapter):
    name = "ugc_individual_seller/v0"

    def _normalize_beats(self, variant: dict, facet: dict,
                         profile: dict) -> list[dict]:
        beats = [b for b in (variant.get("beats") or [])
                 if isinstance(b, dict)][:5]
        if not beats:
            beats = [{"information": {"claim": (profile.get("claims") or [""])[i % max(1, len(profile.get("claims") or [""]))]}}
                     for i in range(3)]
        n = len(beats)
        times = []
        cursor = 0.0
        ok = True
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
            times.append([a, z])
            cursor = z
        if not ok or abs(cursor - 12.0) > 1e-6:
            step = 12.0 / n
            times = [[round(i * step, 3), round((i + 1) * step, 3)]
                     for i in range(n)]
        vbeats, vshots = _valid_indices(facet)
        pair_map = {}
        for p in ((facet.get("structure") or {})
                  .get("beat_shot_alignment") or {}).get("pairs") or []:
            try:
                pair_map[int(p.get("beat_index"))] = [
                    int(x) for x in (p.get("shot_indices") or [])]
            except Exception:
                continue
        shots = facet.get("timeline") or []
        claims = profile.get("claims") or ["商品结构展示"]
        proofs = profile.get("proofs") or ["手部展示"]
        must_show = profile.get("must_show") or []
        person = profile.get("person") or {}
        identity = person.get("identity") or "真人女主播"

        lane = variant.get("format_profile") or {}
        pv = str(lane.get("person_visibility") or "full")
        presenter = str(lane.get("presenter_mode") or "direct_speech")
        # 无人物车道不可能有“同期声”，自动退化为画外音
        if pv not in ("full", "partial") and presenter == "direct_speech":
            presenter = "voiceover"
        has_voice = presenter in ("direct_speech", "voiceover")
        person_beats = set()
        for x in lane.get("person_beats") or []:
            try:
                person_beats.add(int(x))
            except Exception:
                continue
        if pv == "partial" and not person_beats:
            person_beats = {1}
        lane_scene = str(lane.get("scene") or "")
        lane_camera = str(lane.get("camera_language") or "")
        lane_light = str(lane.get("lighting") or "")

        def default_persona(visible: bool) -> str:
            if visible:
                return identity
            if pv == "none":
                return ("静物展示（画面只有商品与桌面）" if not has_voice
                        else "画外女声（画面只有商品与桌面）")
            return ("手部特写（画面只有手和商品）" if not has_voice
                    else "画外女声（画面只有手和商品）")

        body_terms = ("小胸", "聚拢", "胸型", "穿出", "上身", "穿着",
                      "穿戴", "贴身", "试穿")
        safe_claims = [c for c in claims
                       if not any(t in str(c) for t in body_terms)] or claims

        out = []
        for i, b in enumerate(beats):
            t = times[i]
            idx = i + 1
            base = shots[i % len(shots)] if shots else {}
            info = dict(b.get("information") or {})
            claim = str(info.get("claim") or claims[i % len(claims)])
            if pv in ("hands_only", "none"):
                claim = str(safe_claims[i % len(safe_claims)])
            proof = str(info.get("proof") or proofs[i % len(proofs)])
            text = str(info.get("text_overlay") or claim)[:24]
            visible = pv == "full" or (pv == "partial" and idx in person_beats)
            persona = str(info.get("persona") or "").strip()
            # 车道优先级高于 LLM 的 persona，防止把无人物镜头又写成真人
            if pv in ("hands_only", "none"):
                persona = default_persona(False)
            elif pv == "partial" and not visible:
                persona = default_persona(False)
            elif pv == "full":
                persona = identity
            elif not persona:
                persona = default_persona(visible)
            voice = str(info.get("voiceover") or "")
            if not voice and has_voice:
                voice = claim
            if not has_voice:
                voice = ""
            context = str(info.get("context") or lane_scene or "室内场景")
            offer = str(info.get("offer_cta") or "")
            if i == n - 1 and not offer:
                offer = profile.get("offer") or "点下方看活动价"
            info.update({
                "claim": claim, "proof": proof, "text_overlay": text,
                "voiceover": voice, "persona": persona,
                "context": context, "offer_cta": offer,
            })
            sb = b.get("source_beats") or [vbeats[i % len(vbeats)]
                                           if vbeats else 1]
            sb = [x for x in (int(y) for y in sb) if x in vbeats] or [vbeats[0]]
            aligned = []
            for bi in sb:
                aligned.extend(pair_map.get(bi) or [])
            aligned = [x for x in aligned if x in vshots]
            ss = aligned or b.get("source_shots") or [
                vshots[i % len(vshots)] if vshots else 1]
            ss = [x for x in (int(y) for y in ss) if x in vshots] or [vshots[0]]
            function = str(b.get("function") or (
                "hook" if i == 0 else ("cta" if i == n - 1 else "proof")))
            label = str(b.get("function_label") or "").strip()
            if not label:
                label = {"hook": "开场钩子", "cta": "收尾/CTA"}.get(
                    function, "信息/证明")
            out.append({
                "index": idx, "function": function,
                "function_label": label, "time": t,
                "duration": round(t[1] - t[0], 3),
                "shot_size": b.get("shot_size") or base.get("shot_size") or "medium",
                "angle": b.get("angle") or base.get("angle") or "平视",
                "camera": b.get("camera") or lane_camera
                or base.get("camera") or "固定机位",
                "lighting": b.get("lighting") or lane_light
                or base.get("lighting") or "自然光",
                "composition": b.get("composition") or base.get("composition") or "",
                "action": b.get("action") or base.get("action") or "",
                "product_evidence": b.get("product_evidence") or must_show[:3],
                "on_screen_text": b.get("on_screen_text") or text,
                "transition": b.get("transition") or "硬切",
                "information": info,
                "source": {
                    "ref_id": facet.get("ref_id"),
                    "beat_indices": sb, "shot_indices": ss,
                    "fields_used": ["shot_size", "composition", "action",
                                    "on_screen_text"],
                    "overrides": ["商品卖点", "呈现车道", "人物", "场景",
                                  "字幕", "声音", "CTA"],
                    "note": "结构/镜头语法参考；呈现车道按 variant.format_profile 执行",
                },
            })
        return out

    def build_contract(self, variant: dict, brief: dict, profile: dict,
                       facet: dict, idx: int) -> dict:
        payload = brief.get("payload") or brief
        beats = self._normalize_beats(variant, facet, profile)
        n = len(beats)
        flags = [_has_person(b) for b in beats]
        person = dict(profile.get("person") or {})
        must_show = profile.get("must_show") or []
        # 本次 run 指定的人物图优先于 profile 默认图
        brief_person = (((payload.get("assets") or {}).get("person") or {})
                        .get("path"))
        if brief_person:
            person["image"] = brief_person
        lane = variant.get("format_profile") or {}
        pv = str(lane.get("person_visibility") or "full")
        presenter = str(lane.get("presenter_mode") or "direct_speech")
        if pv not in ("full", "partial") and presenter == "direct_speech":
            presenter = "voiceover"
        has_voice = presenter in ("direct_speech", "voiceover")
        show_person = pv in ("full", "partial") and any(flags)
        visible_beats = [b["index"] for b, f in zip(beats, flags) if f]
        lane_name = str(lane.get("name") or "真人手持口播")
        lane_summary = str(lane.get("summary") or "")
        scene = str(lane.get("scene") or "室内居家场景")
        camera = str(lane.get("camera_language") or "手机竖屏手持")
        lighting = str(lane.get("lighting") or "自然光 + 室内暖光")
        text_style = str(lane.get("text_style") or "硬字幕")
        pacing = str(lane.get("pacing") or "fast")
        audio_design = str(lane.get("audio_design") or "")

        if pv == "full" and show_person:
            person_policy = (
                f"真人女主播出镜，{person.get('identity') or '短发亚洲女性'}；"
                f"{lane_summary or '面对镜头自然表达'}；不要出现第二个人；"
                "服装按场景正常穿着，不暴露。")
        elif pv == "partial" and show_person:
            person_policy = (
                f"只在 beat {visible_beats or [1]} 真人出镜，"
                f"人物为{person.get('identity') or '固定人物'}；"
                "其余 beat 只出现手部或商品，不出现脸；不要出现第二个人。")
        elif pv == "hands_only":
            person_policy = (
                "画面自始至终是桌面商品特写：一双手在浅色桌面上操作文胸，"
                "镜头固定在桌面；画面里只有手和商品。")
        elif pv == "none":
            person_policy = (
                "画面自始至终是桌面商品静物：文胸平铺在浅色桌面，"
                "镜头固定俯拍；画面里只有商品和桌面陈设。")
        else:
            person_policy = "画面里只有手部与商品；画外女声口播。"

        if presenter == "direct_speech":
            audio_policy = (
                "H3 原生同步音频：真人与台词口型同步，中文普通话，"
                f"{pacing}节奏；每个 beat 的 voiceover 就是台词；不要后期 TTS。")
        elif presenter == "voiceover":
            audio_policy = (
                "H3 原生音频：画外女声中文普通话口播，人物不必出镜；"
                "画面动作与台词节奏对齐，但不要强行生成口型；不要后期 TTS。")
        elif presenter == "ambient":
            audio_policy = (
                "H3 原生音频：声音只有轻音乐、室内环境底噪、"
                "布料摩擦、按压、翻扣与切镜声；不要后期 TTS。")
        else:
            audio_policy = (
                "H3 原生音频：声音只有低音量 BGM 和操作音效；"
                "信息由后期字幕承载；不要后期 TTS。")
        if audio_design:
            audio_policy = f"{audio_policy} 声音设计：{audio_design}。"

        hyp = str(variant.get("hypothesis") or f"变体 {idx}")
        concept = str(variant.get("rationale") or hyp)
        fmt = (payload.get("goal") or {})
        duration = int(fmt.get("duration_seconds") or 12)
        archetype = fmt.get("archetype") or profile.get(
            "default_archetype", "ugc_individual_seller")
        color_policy = (payload.get("constraints") or {}).get(
            "color_policy") or profile.get("color_policy", "single")
        subtitles = "无字幕" not in text_style and text_style.lower() != "none"
        negative = ["不要纯白影棚", "不要影楼背景", "不要产品目录感",
                    "不要固定对称广告机位", "不要品牌logo",
                    "不要平台水印", "商品不变形", "商品不变色",
                    "不要光面基础款", "不要省略花卉蕾丝/金色包边/蝴蝶结",
                    "不要暴露/低俗", "不要镜像漂移"]
        if subtitles:
            negative.append("不要画面内生成字幕/文字/贴纸")
        if "慢" not in pacing and "asmr" not in pacing.lower():
            negative.append("不要慢动作")
        if pv == "full":
            negative.extend(["不要无人物", "不要只有手部"])
        elif pv == "partial":
            negative.extend(["不要全程真人", "不要第二个人"])
        elif pv == "hands_only":
            negative.extend(["镜头保持在桌面，不要切到真人"])
        elif pv == "none":
            negative.extend(["镜头保持在静物桌面，不要切到真人"])
        if color_policy == "single":
            negative.append(f"不要出现 {profile.get('identity')} 之外的颜色/款式")
        # 侧身/背影车道容易把商品拍成光面基础款：用正面近景定帧 + 末镜回正面
        lane_l = lane_name.lower()
        side_lane = (("侧" in lane_name or "背" in lane_name)
                     or "side" in lane_l or "back" in lane_l)
        front_evidence = [
            x for x in must_show
            if any(k in str(x) for k in ("正面", "蕾丝", "金色", "蝴蝶结"))]
        if side_lane and beats:
            b0 = beats[0]
            b0["shot_size"] = "close_up"
            b0["angle"] = "3/4 侧前方平视"
            b0["camera"] = "固定机位，3/4 侧前方近景"
            b0["composition"] = (
                "人物侧身 45 度，文胸正面罩杯、花卉蕾丝、金色包边与"
                "前中蝴蝶结完整入画，侧比同时可见")
            b0["action"] = (
                "人物侧身 45 度，手轻拉开衫，先让文胸正面蕾丝、金色包边、"
                "蝴蝶结与侧比完整入画")
            b0["product_evidence"] = (front_evidence or must_show)[:4]
            last = beats[-1]
            last["composition"] = (
                f"{last.get('composition') or ''}；文胸正面花卉蕾丝、"
                "金色包边与蝴蝶结清晰可见").strip("；")
            last["product_evidence"] = list(dict.fromkeys(
                (front_evidence or []) + (last.get("product_evidence") or [])))

        refs = []
        product_index = 2 if show_person else 1
        person_image = person.get("image")
        default_person = (profile.get("person") or {}).get("image")
        if (side_lane and person.get("side_image")
                and (not brief_person or brief_person == default_person)):
            person_image = person["side_image"]
        if pv == "hands_only":
            product_policy = (
                f"参考图{product_index}只负责商品本身；忽略原背景与文字；"
                "画面中可有一双自然手部操作商品。")
        elif pv == "none":
            product_policy = (
                f"参考图{product_index}只负责商品本身；忽略图中的手、背景、文字；"
                "画面只保留商品与桌面陈设。")
        else:
            product_policy = (profile.get("reference_policy")
                              or "只负责商品本身；忽略图中的手、背景、文字。")
            if not show_person:
                product_policy = product_policy.replace(
                    "参考图2", f"参考图{product_index}")
        if show_person:
            refs.append({"index": 1, "kind": "person",
                         "label": "固定人物照片1", "path": person_image,
                         "policy": "只保留人物身份；忽略原服装、背景；服装/场景按本变体车道更换。"})
        refs.append({"index": product_index, "kind": "product",
                     "label": f"商品图{product_index}（正面）",
                     "path": profile.get("image"),
                     "policy": product_policy})
        if side_lane and profile.get("back_image"):
            refs.append({
                "index": product_index + 1, "kind": "product",
                "label": f"商品图{product_index + 1}（背面）",
                "path": profile["back_image"],
                "policy": "只负责背面结构与四排扣；忽略图中的手、背景、文字。"})
        presentation = {
            "name": lane_name, "summary": lane_summary,
            "person_visibility": pv, "presenter_mode": presenter,
            "camera_language": camera, "scene": scene, "lighting": lighting,
            "proof_style": str(lane.get("proof_style") or ""),
            "narrative_device": str(lane.get("narrative_device") or ""),
            "audio_design": audio_design, "text_style": text_style,
            "pacing": pacing, "person_beats": visible_beats,
            "evidence_refs": lane.get("evidence_refs") or [],
        }
        if pv == "hands_only":
            wear_state = "第一人称手部拿持/翻转/按压/平铺，画面只有手和商品。"
        elif pv == "none":
            wear_state = "商品静物摆放/桌面平铺/转台/微距，画面只有商品和桌面陈设。"
        else:
            wear_state = ("真人手持/平铺展示；真人上身时外搭衬衫/针织开衫，"
                          "只露肩带与领口，不暴露。")
        target = {
            "ref_id": profile.get("reference_id"),
            "references": refs,
            "product": {
                "symbol": "<Product 1>", "reference_index": product_index,
                "identity": profile.get("identity"),
                "description": profile.get("description") or "",
                "image": profile.get("image"),
                "reference_policy": product_policy,
                "must_show": profile.get("must_show") or [],
                "must_not_change": profile.get("must_not_change") or [],
                "wear_state": wear_state,
                "matching": "不新增商品图之外的服装部件。",
            },
            "format": {
                "duration": duration, "aspect_ratio": "9:16",
                "resolution": "768P", "pacing": pacing,
                "archetype": archetype,
                "voiceover": bool(has_voice and any(
                    str((b.get("information") or {}).get("voiceover") or "").strip()
                    for b in beats)),
                "subtitles": subtitles,
                "native_audio": True,
                "presentation": presentation,
            },
        }
        if show_person:
            target["person"] = {
                "symbol": "<Person 1>", "reference_index": 1,
                "identity": person.get("identity"),
                "immutable": person.get("immutable") or
                ["脸型", "发型", "体型", "肤色"],
                "policy": person.get("policy") or "",
            }
        return {
            "schema_version": "fission-contract/v1-ugc",
            "slice_id": f"{profile['product_id']}-v{idx:02d}-{variant.get('id') or idx}",
            "target": target,
            "structure": {
                "name": (lane_name if pv in ("hands_only", "none")
                         else hyp[:30]),
                "concept": (lane_summary if pv in ("hands_only", "none")
                            and lane_summary else concept),
                "hook": {"time": [0.0, 1.5],
                         "description": beats[0]["action"]
                         or beats[0]["information"]["claim"]},
                "beats": beats,
            },
            "global": {
                "scene": f"{scene}；不要纯白影棚、不要影楼背景。",
                "lighting": f"{lighting}；不要过度磨皮，保持 UGC 实拍质感。",
                "camera": f"{camera}；机位与运动按呈现车道执行，不要固定对称广告机位。",
                "person_policy": person_policy,
                "audio_policy": audio_policy,
                "text_policy": (
                    f"{text_style}；字幕后期叠加（白字黑边、大字号、居中偏下），"
                    "不要生成在画面里；无品牌 logo、无平台水印。"
                    if subtitles else
                    "无字幕；不要生成画面文字、贴纸、品牌 logo 或平台水印。"),
                "negative": negative,
            },
            "information_budget": {
                "claims": min(4, n), "proofs": min(2, n),
                "text_overlays": n if subtitles else 0,
                "voiceovers": n if target["format"]["voiceover"] else 0,
                "personas": 1 if show_person else 0,
                "contexts": max(1, min(2, len({
                    str((b.get("information") or {}).get("context") or "")
                    for b in beats}))),
                "offer_cta": 1,
            },
            "facet_coverage": {
                "used": [
                    {"facet": f"{facet.get('ref_id')}.structure.beats",
                     "value": "结构/镜头语法", "why": "本变体的主参考结构"},
                    {"facet": f"{facet.get('ref_id')}.marketing",
                     "value": "卖点/证明顺序", "why": "信息密度参考"},
                    {"facet": f"{profile.get('reference_id')}.product",
                     "value": "商品不可变特征", "why": "商品保真"},
                ],
                "adapted": [
                    {"facet": "brief.facts", "value": "商品卖点/场景",
                     "why": "按本次商品 brief 改写"},
                    {"facet": "pool.patterns", "value": "全池归纳",
                     "why": "guidance 的临时模式，不一比一复制"},
                    {"facet": "pool.presentation_lanes",
                     "value": lane_name,
                     "why": lane_summary or "本变体选择的呈现车道"},
                ],
                "waived": [
                    {"facet": "primary_ref.category_claims",
                     "value": "与本品无关的品类卖点", "why": "避免跨品类错误迁移"},
                    {"facet": "price", "value": "具体金额",
                     "why": "未提供真实价格，用活动价占位"},
                ],
            },
            "negative": [],
            "provenance": {
                "facet": f"data/reference_facets/{facet.get('ref_id')}.json",
                "alignment": f"data/reference_alignments/{facet.get('ref_id')}.json",
                "reference_refs": [facet.get("ref_id"),
                                   profile.get("reference_id")],
                "variant_id": variant.get("id"),
                "profile": profile.get("product_id"),
                "presentation_lane": lane_name,
                "person_visibility": pv,
                "presenter_mode": presenter,
            },
        }


ADAPTERS = {
    "ugc_individual_seller": UGCIndividualSellerAdapter(),
}


def get_adapter(archetype: str) -> Adapter:
    if archetype not in ADAPTERS:
        raise ValueError(
            f"没有 adapter: {archetype}；已注册: {sorted(ADAPTERS)}")
    return ADAPTERS[archetype]
