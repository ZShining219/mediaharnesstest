"""裂变契约 v0：facet -> 显式 beat 契约 -> H3 prompt / 审计。

设计目标：
- 每个目标 beat 必须写明来源（reference facet 的 beat / shot / 字段）；
- 目标方向对参考的改写必须显式记录为 override，而不是静默丢失；
- 渲染时 beat 1:1 进入 prompt，不做关键词折叠或固定模块替换；
- 校验覆盖度，便于回答“这句提示词来自哪条案例的哪个字段”。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACETS_DIR = ROOT / "data" / "reference_facets"

SOURCE_FIELDS = {
    "shot_size", "angle", "camera", "lighting", "color", "composition",
    "subject", "action", "product", "product_visibility", "on_screen_text",
    "transition", "blueprint_prompt",
}
REQUIRED_BEAT_FIELDS = (
    "index", "function", "function_label", "time", "duration", "shot_size",
    "angle", "camera", "lighting", "composition", "action",
    "product_evidence", "transition", "source",
)


def load_facet(ref_id: str, facets_dir: Path | None = None) -> dict:
    p = (facets_dir or FACETS_DIR) / f"{ref_id}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _text(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _fmt_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:04.1f}"


def _references(target: dict) -> list[dict]:
    refs = target.get("references") or []
    return [r for r in refs
            if isinstance(r, dict) and r.get("index") is not None]


def _beat_index_set(facet: dict) -> set[int]:
    return {int(b.get("index") or 0)
            for b in ((facet.get("structure") or {}).get("beats") or [])}


def _shot_index_set(facet: dict) -> set[int]:
    return {int(s.get("index") or 0) for s in (facet.get("timeline") or [])}


def validate_contract(contract: dict, facet: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    beats = ((contract.get("structure") or {}).get("beats") or [])
    target = contract.get("target") or {}
    fmt = target.get("format") or {}
    duration = float(fmt.get("duration") or 0)

    if not beats:
        errors.append("structure.beats 为空")
        return {"ok": False, "errors": errors, "warnings": warnings}

    cursor = 0.0
    for b in beats:
        label = f"beat {b.get('index')}"
        missing = [k for k in REQUIRED_BEAT_FIELDS if b.get(k) in (None, "", [])]
        if missing:
            errors.append(f"{label} 缺字段: {','.join(missing)}")
        t = b.get("time")
        if not (isinstance(t, (list, tuple)) and len(t) == 2):
            errors.append(f"{label} time 必须是 [start,end]")
            continue
        try:
            t0, t1 = float(t[0]), float(t[1])
        except (TypeError, ValueError):
            errors.append(f"{label} time 不是数值")
            continue
        if t0 < cursor - 1e-6:
            errors.append(f"{label} 与前一个 beat 时间重叠")
        if t1 <= t0:
            errors.append(f"{label} time 结束必须大于开始")
        if abs((t1 - t0) - float(b.get("duration") or 0)) > 1e-6:
            errors.append(f"{label} duration 与 time 不一致")
        cursor = t1
        if not b.get("product_evidence"):
            errors.append(f"{label} product_evidence 为空")
        if b.get("on_screen_text") and not fmt.get("subtitles", False):
            warnings.append(f"{label} 有画面文字，但目标策略是无字幕")

        src = b.get("source") or {}
        if src.get("ref_id") != facet.get("ref_id"):
            errors.append(f"{label} source.ref_id 与 facet 不一致")
        bis = [int(x) for x in (src.get("beat_indices") or [])]
        sis = [int(x) for x in (src.get("shot_indices") or [])]
        if not bis:
            errors.append(f"{label} 没有 source.beat_indices")
        if not sis:
            errors.append(f"{label} 没有 source.shot_indices")
        unknown_b = [x for x in bis if x not in _beat_index_set(facet)]
        unknown_s = [x for x in sis if x not in _shot_index_set(facet)]
        if unknown_b:
            errors.append(f"{label} 引用不存在的参考 beat: {unknown_b}")
        if unknown_s:
            errors.append(f"{label} 引用不存在的参考镜头: {unknown_s}")
        used = list(src.get("fields_used") or [])
        if not used:
            errors.append(f"{label} 没有 source.fields_used")
        unknown_f = [x for x in used if x not in SOURCE_FIELDS]
        if unknown_f:
            warnings.append(f"{label} fields_used 含未知字段: {unknown_f}")
        # 来源 beat 的已对齐镜头应与 source.shot_indices 有交集
        pair_map = {int(p.get("beat_index")): p
                    for p in ((facet.get("structure") or {})
                              .get("beat_shot_alignment") or {}).get("pairs") or []}
        aligned = set()
        for bi in bis:
            aligned.update(int(x) for x in (pair_map.get(bi, {})
                                            .get("shot_indices") or []))
        if aligned and sis and not (aligned & set(sis)):
            warnings.append(
                f"{label} 的 shot_indices 与参考 beat 的对齐镜头无交集: "
                f"{sorted(aligned)} vs {sis}")

    if duration and abs(cursor - duration) > 1e-6:
        errors.append(f"beat 总时长 {cursor} 与 target.duration {duration} 不一致")

    hook = (contract.get("structure") or {}).get("hook") or {}
    ht = hook.get("time") or []
    if len(ht) != 2 or abs(float(ht[0])) > 1e-6:
        errors.append("structure.hook.time 必须从 0 开始")
    elif float(ht[1]) > 1.5:
        warnings.append("hook 结束时间超过 1.5 秒，可能弱化前 1 秒抓眼")

    refs = _references(target)
    if refs:
        idxs = [int(r["index"]) for r in refs]
        if len(set(idxs)) != len(idxs):
            errors.append("target.references 的 index 重复")
        if not any(r.get("kind") == "product" for r in refs):
            errors.append("target.references 缺少 kind=product 的商品参考图")
        for r in refs:
            if not _text(r.get("path")):
                errors.append(f"参考图{r.get('index')} 缺少 path")

    archetype = fmt.get("archetype")
    if archetype == "ugc_individual_seller":
        info = [b.get("information") or {} for b in beats]
        counts = {
            "claims": sum(1 for x in info if _text(x.get("claim"))),
            "proofs": sum(1 for x in info if _text(x.get("proof"))),
            "text_overlays": sum(1 for x in info if _text(x.get("text_overlay"))),
            "voiceovers": sum(1 for x in info if _text(x.get("voiceover"))),
            "personas": sum(1 for x in info if _text(x.get("persona"))),
            "contexts": len({_text(x.get("context")) for x in info
                             if _text(x.get("context"))}),
            "offer_cta": sum(1 for x in info if _text(x.get("offer_cta"))),
        }
        defaults = {"claims": 4, "proofs": 2, "text_overlays": 3,
                    "voiceovers": 3, "personas": 1, "contexts": 2,
                    "offer_cta": 1}
        budget = {**defaults, **(contract.get("information_budget") or {})}
        for key, minimum in budget.items():
            if counts.get(key, 0) < int(minimum):
                warnings.append(
                    f"信息密度不足：{key}={counts.get(key, 0)} < {minimum}")
        pv = ((fmt.get("presentation") or {})
              .get("person_visibility") or "full")
        need_person = pv in ("full", "partial")
        if counts["claims"] == 0 or counts["proofs"] == 0 \
                or (need_person and counts["personas"] == 0):
            errors.append(
                "ugc_individual_seller 缺少卖点/证明"
                + ("/人物信息" if need_person else "信息"))

    cov = contract.get("facet_coverage") or {}
    for key in ("used", "adapted", "waived"):
        if not isinstance(cov.get(key), list) or not cov.get(key):
            warnings.append(f"facet_coverage.{key} 为空")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def contract_stats(contract: dict, facet: dict) -> dict:
    beats = (contract.get("structure") or {}).get("beats") or []
    ref_beats: set[int] = set()
    ref_shots: set[int] = set()
    for b in beats:
        src = b.get("source") or {}
        ref_beats.update(int(x) for x in (src.get("beat_indices") or []))
        ref_shots.update(int(x) for x in (src.get("shot_indices") or []))
    total_shots = len(facet.get("timeline") or [])
    total_beats = len((facet.get("structure") or {}).get("beats") or [])
    hook_beat = next((b for b in beats if b.get("function") == "hook"), None)
    fields = ("shot_size", "angle", "camera", "lighting", "composition",
              "action", "product_evidence", "transition")
    info = [b.get("information") or {} for b in beats]
    info_counts = {
        "claims": sum(1 for x in info if _text(x.get("claim"))),
        "proofs": sum(1 for x in info if _text(x.get("proof"))),
        "text_overlays": sum(1 for x in info if _text(x.get("text_overlay"))),
        "voiceovers": sum(1 for x in info if _text(x.get("voiceover"))),
        "personas": sum(1 for x in info if _text(x.get("persona"))),
        "contexts": len({_text(x.get("context")) for x in info
                         if _text(x.get("context"))}),
        "offer_cta": sum(1 for x in info if _text(x.get("offer_cta"))),
    }
    return {
        "beat_count": len(beats),
        "beats_with_source": sum(1 for b in beats if b.get("source")),
        "reference_beats_used": sorted(ref_beats),
        "reference_beat_count": total_beats,
        "reference_beat_coverage": round(len(ref_beats) / total_beats, 3)
        if total_beats else 0,
        "reference_shots_used": sorted(ref_shots),
        "reference_shot_count": total_shots,
        "reference_shot_coverage": round(len(ref_shots) / total_shots, 3)
        if total_shots else 0,
        "hook_beat_index": hook_beat.get("index") if hook_beat else None,
        "hook_time": hook_beat.get("time") if hook_beat else None,
        "avg_fields_per_beat": round(
            sum(sum(1 for k in fields if b.get(k) not in (None, "", []))
                for b in beats) / len(beats), 2) if beats else 0,
        "information": info_counts,
    }


def render_h3_prompt(contract: dict) -> str:
    target = contract.get("target") or {}
    fmt = target.get("format") or {}
    prod = target.get("product") or {}
    st = contract.get("structure") or {}
    glob = contract.get("global") or {}
    parts: list[str] = []

    parts.append("【主体定义】")
    refs = _references(target)
    person = target.get("person") or {}
    if refs:
        prod_ref = next((r for r in refs if r.get("kind") == "product"), {})
        prod_idx = prod_ref.get("index", 1)
        if person:
            p_idx = person.get("reference_index") or next(
                (r.get("index") for r in refs if r.get("kind") == "person"), 1)
            parts.append(
                f"{person.get('symbol') or '<Person 1>'} = 参考图{p_idx}中的"
                f"{person.get('identity') or '人物'}。不可变特征："
                f"{'、'.join(person.get('immutable') or ['脸型', '发型', '体型', '肤色'])}。")
            if person.get("policy"):
                parts.append(person["policy"])
        parts.append(
            f"{prod.get('symbol') or '<Product 1>'} = 参考图{prod_idx}中的"
            f"{prod.get('identity') or '商品'}。不可变特征："
            f"{'、'.join(prod.get('must_not_change') or [])}。")
        for r in refs:
            if r.get("kind") == "product" and r.get("index") != prod_idx:
                parts.append(
                    f"参考图{r['index']} = {r.get('label') or '商品另一视角'}"
                    f"（{r.get('policy') or ''}）")
        legend = [
            f"参考图{r['index']} = {r.get('label') or r.get('kind')}"
            f"（{r.get('policy') or ''}）"
            for r in sorted(refs, key=lambda x: int(x["index"]))
        ]
        parts.append("参考图顺序：" + "；".join(legend) + "。")
    else:
        parts.append(
            f"{prod.get('symbol') or '<Product 1>'} = 参考图1中的"
            f"{prod.get('identity') or '商品'}。"
            f"不可变特征：{'、'.join(prod.get('must_not_change') or [])}。")
        if prod.get("reference_policy"):
            parts.append(prod["reference_policy"])
    parts.append("")

    world = st.get("creative_world") or {}
    if world:
        parts.append("【创意世界】")
        parts.append(f"标题：{world.get('title') or ''}")
        parts.append(f"前提：{world.get('premise') or ''}")
        parts.append(f"冲突：{world.get('tension') or ''}")
        parts.append(f"装置：{world.get('device') or ''}")
        parts.append(f"转折：{world.get('turn') or ''}")
        parts.append(f"落点：{world.get('payoff') or ''}")
        parts.append(f"场景：{world.get('scene') or ''}")
        if world.get("props"):
            parts.append("道具：" + "、".join(str(x) for x in world["props"]) + "。")
        rituals = world.get("proof_rituals") or []
        if rituals:
            parts.append("证明仪式：" + "；".join(
                f"{r.get('action')} → {r.get('evidence')}" for r in rituals) + "。")
        parts.append("")
    parts.append("【本条方向】")
    parts.append(f"{st.get('name') or ''}")
    parts.append(f"创意：{st.get('concept') or ''}")
    hook = st.get("hook") or {}
    ht = hook.get("time") or [0, 1]
    parts.append(f"钩子（{_fmt_time(ht[0])}-{_fmt_time(ht[1])}）："
                 f"{hook.get('description') or ''}")
    parts.append("")

    parts.append("【全局合同】")
    parts.append(
        f"时长 {fmt.get('duration')} 秒；{fmt.get('aspect_ratio') or '9:16'}；"
        f"{fmt.get('resolution') or '768P'}；节奏："
        f"{fmt.get('pacing') or '按分镜时间轴剪辑'}。")
    pres = fmt.get("presentation") or {}
    pv = pres.get("person_visibility")
    arch = {"ugc_individual_seller": "UGC 个体带货"}.get(
        fmt.get("archetype"), fmt.get("archetype") or "UGC 短视频")
    pv_label = {"full": "真人出镜", "partial": "部分真人出镜",
                "hands_only": "仅手部出镜", "none": "无人物"}.get(pv, pv or "")
    mode = pres.get("presenter_mode") or "direct_speech"
    mode_label = {"direct_speech": "同期声口播", "voiceover": "画外音",
                  "ambient": "仅环境音/音效", "text_only": "无口播/字幕"}.get(
                      mode, mode)
    if pv == "hands_only":
        parts.append("类型：UGC 商品手部演示。")
    elif pv == "none":
        parts.append("类型：UGC 商品静物展示。")
    elif fmt.get("archetype"):
        parts.append(f"范式：{arch}。")
    if pres:
        summary = str(pres.get("summary") or "").rstrip("。")
        parts.append(
            f"风格：{pres.get('name') or ''}——{summary}。")
        parts.append(f"人物：{pv_label}；声音：{mode_label}。")
    copy = st.get("copy_profile") or {}
    if copy:
        copy_person = {"first_person": "第一人称", "friend": "朋友口吻",
                       "reviewer": "评测者", "narrator": "旁白",
                       "none": "无"}.get(copy.get("person"),
                                         copy.get("person") or "")
        parts.append(
            f"文案风格：{copy.get('tone') or ''}；人称={copy_person}；"
            f"句式={copy.get('sentence_style') or ''}；"
            f"开场={copy.get('hook_type') or ''}；"
            f"CTA={copy.get('cta_style') or ''}。")
    parts.append(f"场景：{glob.get('scene') or ''}")
    parts.append(f"光线：{glob.get('lighting') or ''}")
    parts.append(f"机位：{glob.get('camera') or ''}")
    parts.append(f"人物：{glob.get('person_policy') or '无人物出镜，仅手部入画。'}")
    parts.append(f"声音：{glob.get('audio_policy') or '无口播、无台词；只有环境底噪与 BGM。'}")
    parts.append(f"文字：{glob.get('text_policy') or '无字幕、无贴纸、无品牌 logo。'}")
    parts.append("")

    parts.append("【商品硬约束】")
    parts.append("必须出现：" + "、".join(prod.get("must_show") or []) + "。")
    parts.append("不得改变：" + "、".join(prod.get("must_not_change") or []) + "。")
    if prod.get("wear_state"):
        parts.append(f"展示状态：{prod['wear_state']}。")
    if prod.get("matching"):
        parts.append(f"匹配：{prod['matching']}。")
    parts.append("")

    parts.append("【逻辑分镜时间轴】")
    parts.append("这是一条连续视频内的逻辑分镜，不是多个独立生成任务。"
                 "请按时间轴连续生成，在切镜处按切镜描述执行。")
    for b in st.get("beats") or []:
        t = b.get("time") or [0, 0]
        parts.append(f"[{_fmt_time(t[0])}-{_fmt_time(t[1])} | "
                     f"beat {b.get('index')} | {b.get('function_label')}]")
        parts.append(f"景别：{b.get('shot_size')}；角度：{b.get('angle')}。")
        parts.append(f"机位：{b.get('camera')}")
        parts.append(f"光线：{b.get('lighting')}")
        parts.append(f"构图：{b.get('composition')}")
        parts.append(f"动作：{b.get('action')}")
        info = b.get("information") or {}
        if info:
            pm = pres.get("presenter_mode")
            voice_label = ("口播（画外音，不需要口型同步）"
                           if pm == "voiceover"
                           else "口播（与画面同步生成）")
            labels = (
                ("claim", "卖点"), ("proof", "证明"),
                ("text_overlay", "字幕（后期叠加，不要生成在画面里）"),
                ("voiceover", voice_label),
                ("persona", "人物"), ("context", "场景"),
                ("offer_cta", "转化"),
            )
            bits = [f"{label}={_text(info[key])}" for key, label in labels
                    if _text(info.get(key))]
            if bits:
                parts.append("信息：" + "；".join(bits) + "。")
        parts.append("商品证据：" + "、".join(b.get("product_evidence") or []) + "。")
        if b.get("on_screen_text"):
            if fmt.get("subtitles"):
                parts.append(f"后期字幕：{b['on_screen_text']}"
                             "（不要生成在画面里）。")
            else:
                parts.append(f"画面文字：{b['on_screen_text']}。")
        else:
            parts.append("画面文字：无。")
        parts.append(f"转场：{b.get('transition')}。")
        parts.append("")

    parts.append("【负面约束】")
    merged = list(glob.get("negative") or [])
    merged.extend(contract.get("negative") or [])
    parts.append("；".join(dict.fromkeys(x for x in merged if x)) + "。")
    return "\n".join(parts).strip() + "\n"


def render_audit(contract: dict, facet: dict) -> str:
    stats = contract_stats(contract, facet)
    target = contract.get("target") or {}
    fmt = target.get("format") or {}
    cov = contract.get("facet_coverage") or {}
    lines: list[str] = []
    lines.append(f"# 契约审计：{contract.get('slice_id') or ''}")
    lines.append("")
    lines.append(f"- 参考案例：`{facet.get('ref_id')}`")
    lines.append(f"- 方向：{((contract.get('structure') or {}).get('name'))}")
    pres = fmt.get("presentation") or {}
    lines.append(
        f"- 目标：{fmt.get('duration')}s / {fmt.get('aspect_ratio')} / "
        f"{fmt.get('resolution')} / 口播="
        f"{'有' if fmt.get('voiceover') else '无'} / 字幕="
        f"{'有' if fmt.get('subtitles') else '无'}")
    if pres:
        lines.append(
            f"- 呈现车道：{pres.get('name') or ''} "
            f"({pres.get('person_visibility') or ''} / "
            f"{pres.get('presenter_mode') or ''})")
    lines.append(f"- 参考覆盖：beat {stats['reference_beat_coverage']:.0%} "
                 f"({len(stats['reference_beats_used'])}/{stats['reference_beat_count']})，"
                 f"镜头 {stats['reference_shot_coverage']:.0%} "
                 f"({len(stats['reference_shots_used'])}/{stats['reference_shot_count']})")
    info = stats.get("information") or {}
    lines.append(f"- 信息单元：卖点 {info.get('claims', 0)} / "
                 f"证明 {info.get('proofs', 0)} / 字幕 {info.get('text_overlays', 0)} / "
                 f"口播 {info.get('voiceovers', 0)} / 场景 {info.get('contexts', 0)} / "
                 f"CTA {info.get('offer_cta', 0)}")
    lines.append("")
    lines.append("## 分镜来源")
    lines.append("")
    lines.append("| beat | 时间 | 功能 | 景别/角度 | 动作 | 商品证据 | 来源 beat | 来源镜头 | 使用字段 | 覆盖/改写 |")
    lines.append("|---:|---|---|---|---|---|---|---|---|---|")
    for b in (contract.get("structure") or {}).get("beats") or []:
        src = b.get("source") or {}
        t = b.get("time") or [0, 0]
        lines.append(
            f"| {b.get('index')} | {_fmt_time(t[0])}-{_fmt_time(t[1])} | "
            f"{b.get('function_label')} | {b.get('shot_size')} / {b.get('angle')} | "
            f"{str(b.get('action') or '').replace('|', '／')} | "
            f"{'、'.join(b.get('product_evidence') or [])} | "
            f"{src.get('beat_indices')} | {src.get('shot_indices')} | "
            f"{'、'.join(src.get('fields_used') or [])} | "
            f"{'、'.join(src.get('overrides') or []) or '—'} |")
    lines.append("")
    lines.append("## 信息层")
    lines.append("")
    lines.append("| beat | 卖点 | 证明 | 字幕 | 口播 | 人物 | 场景 | 转化 |")
    lines.append("|---:|---|---|---|---|---|---|---|")
    for b in (contract.get("structure") or {}).get("beats") or []:
        info = b.get("information") or {}
        def cell(key):
            return str(info.get(key) or "").replace("|", "／")
        lines.append(f"| {b.get('index')} | {cell('claim')} | {cell('proof')} | "
                     f"{cell('text_overlay')} | {cell('voiceover')} | "
                     f"{cell('persona')} | {cell('context')} | {cell('offer_cta')} |")
    lines.append("")
    lines.append("## 参考槽位使用/改写/放弃")
    lines.append("")
    for key, title in (("used", "使用"), ("adapted", "改写"), ("waived", "放弃")):
        lines.append(f"### {title}")
        rows = cov.get(key) or []
        if not rows:
            lines.append("- 无")
        for r in rows:
            if isinstance(r, dict):
                facet_name = r.get("facet") or ""
                value = r.get("value") or r.get("to") or ""
                why = r.get("why") or r.get("note") or ""
                lines.append(f"- `{facet_name}` {value}" + (f" —— {why}" if why else ""))
            else:
                lines.append(f"- {r}")
        lines.append("")
    validation = contract.get("_validation") or {}
    lines.append("## 校验")
    lines.append("")
    lines.append(f"- 结果：{'PASS' if validation.get('ok') else 'FAIL'}")
    if validation.get("errors"):
        lines.append("- errors：" + "；".join(validation["errors"]))
    if validation.get("warnings"):
        lines.append("- warnings：" + "；".join(validation["warnings"]))
    lines.append("")
    return "\n".join(lines)
