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


def _fmt_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:04.1f}"


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
        if b.get("on_screen_text"):
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
    }


def render_h3_prompt(contract: dict) -> str:
    target = contract.get("target") or {}
    fmt = target.get("format") or {}
    prod = target.get("product") or {}
    st = contract.get("structure") or {}
    glob = contract.get("global") or {}
    parts: list[str] = []

    parts.append("【主体定义】")
    parts.append(
        f"{prod.get('symbol') or '<Product 1>'} = 参考图1中的"
        f"{prod.get('identity') or '商品'}。"
        f"不可变特征：{'、'.join(prod.get('must_not_change') or [])}。")
    if prod.get("reference_policy"):
        parts.append(prod["reference_policy"])
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
        f"{fmt.get('resolution') or '768P'}；快节奏硬切。")
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
        parts.append("商品证据：" + "、".join(b.get("product_evidence") or []) + "。")
        parts.append(f"画面文字：{b.get('on_screen_text') or '无'}。")
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
    lines.append(f"- 目标：{fmt.get('duration')}s / {fmt.get('aspect_ratio')} / "
                 f"{fmt.get('resolution')} / 无口播 / 无字幕")
    lines.append(f"- 参考覆盖：beat {stats['reference_beat_coverage']:.0%} "
                 f"({len(stats['reference_beats_used'])}/{stats['reference_beat_count']})，"
                 f"镜头 {stats['reference_shot_coverage']:.0%} "
                 f"({len(stats['reference_shots_used'])}/{stats['reference_shot_count']})")
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
