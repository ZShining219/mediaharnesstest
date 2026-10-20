#!/usr/bin/env python3
"""从已有案例描述抽取裂变可用的 facet 契约（v0）。

原则：
- 只做确定性投影，不重新解读、不新增描述；
- 每个字段都能回溯到 descriptions.json / prompt_blueprint.json；
- beat_order 与 shots 的对齐只在可验证时建立，否则显式标 null。

输出：
    data/reference_facets/{ref_id}.json
    data/reference_facets/index.json

用法：
    .venv/bin/python scripts/reference_facets.py
    .venv/bin/python scripts/reference_facets.py --refs ref-a,ref-b
    .venv/bin/python scripts/reference_facets.py --dry-run
    .venv/bin/python scripts/reference_facets.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = ROOT / "data" / "reference_cases"
OUT_DIR = ROOT / "data" / "reference_facets"
SCHEMA_VERSION = "fission-facets/v0"

_TIME_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|~|–|—|至|到)\s*(\d+(?:\.\d+)?)\s*秒")

_SHOT_FIELDS = (
    "shot_size", "angle", "camera", "lighting", "color", "composition",
    "subject", "action", "product", "product_visibility", "on_screen_text",
    "transition", "confidence",
)
_GLOBAL_FIELDS = (
    "category", "scene", "visual_style", "lighting", "color_palette",
    "pacing", "camera_language", "on_screen_text_style", "product",
)
_BLUEPRINT_FIELDS = (
    "global_style", "shot_prompts", "camera_language", "lighting", "pacing",
    "on_screen_text_style", "negative", "invariants", "variables",
    "hard_constraints", "soft_constraints", "reference_role_map", "structure",
)


def _text(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _items(v) -> list:
    if not v:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _category_key(meta: dict, global_d: dict) -> str:
    tags = [str(x) for x in (meta.get("tags") or [])]
    if "文胸" in tags:
        return "文胸"
    if "内裤" in tags:
        return "内裤"
    category = _text(global_d.get("category"))
    if "文胸" in category:
        return "文胸"
    if "内裤" in category:
        return "内裤"
    return "其他"


def _parse_time_range(text: str):
    m = _TIME_RANGE.search(_text(text))
    if not m:
        return None
    try:
        return [float(m.group(1)), float(m.group(2))]
    except ValueError:
        return None


def _shot_prompt_map(blueprint: dict) -> dict[int, dict]:
    out = {}
    for i, item in enumerate(blueprint.get("shot_prompts") or [], 1):
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        try:
            idx = int(idx) if idx is not None else i
        except (TypeError, ValueError):
            idx = i
        out[idx] = item
    return out


def _align_beats(beats: list, shots: list) -> dict:
    """把叙事 beat 对齐到镜头；只在可验证时给出 pairs。"""
    if not beats or not shots:
        return {"method": "none", "confidence": "none", "pairs": [],
                "note": "beat_order 或 shots 为空"}

    timed = [_parse_time_range(b) for b in beats]
    if any(timed):
        pairs = []
        for bi, (beat, tr) in enumerate(zip(beats, timed), 1):
            if not tr:
                continue
            best_i, best_overlap = None, 0.0
            for s in shots:
                s0 = float(s.get("start") or 0)
                s1 = float(s.get("end") or 0)
                overlap = max(0.0, min(tr[1], s1) - max(tr[0], s0))
                if overlap > best_overlap:
                    best_i, best_overlap = int(s.get("index") or 0), overlap
            if best_i:
                pairs.append({"beat_index": bi, "shot_index": best_i,
                              "beat_time": tr, "overlap_sec": round(best_overlap, 3)})
        return {"method": "time_overlap", "confidence": "high", "pairs": pairs,
                "note": "beat 文本含显式时间区间，按时间重叠对齐"}

    if len(beats) == len(shots):
        pairs = [{"beat_index": i, "shot_index": int(s.get("index") or i)}
                 for i, s in enumerate(shots, 1)]
        return {"method": "index_by_count", "confidence": "unverified",
                "pairs": pairs,
                "note": "beat 数与镜头数一致，按顺序暂对齐；语义未校验"}

    return {"method": "none", "confidence": "none", "pairs": [],
            "note": f"beat 数 {len(beats)} ≠ 镜头数 {len(shots)}，未自动对齐"}


def build_facets(case: dict, blueprint_file: dict | None = None,
                 evidence_file: dict | None = None,
                 source_path: Path | None = None) -> dict:
    ref_id = case.get("ref_id") or (source_path.parent.name if source_path else "")
    meta = dict(case.get("meta") or {})
    global_d = dict(case.get("global") or {})
    blueprint = dict(case.get("blueprint") or blueprint_file or {})
    shots = [dict(s) for s in (case.get("shots") or [])]
    roles = dict(case.get("roles") or {})
    transcript = list(case.get("transcript") or [])
    structure = dict(blueprint.get("structure") or {})
    beats = [_text(b) for b in (structure.get("beat_order") or []) if _text(b)]
    prompt_map = _shot_prompt_map(blueprint)

    timeline = []
    for s in shots:
        idx = int(s.get("index") or len(timeline) + 1)
        start = float(s.get("start") or 0)
        end = float(s.get("end") or start)
        bp_shot = prompt_map.get(idx) or {}
        row = {
            "index": idx,
            "time": [start, end],
            "duration": round(max(0.0, end - start), 3),
            **{k: s.get(k) for k in _SHOT_FIELDS},
            "blueprint_prompt": _text(bp_shot.get("prompt")),
        }
        timeline.append(row)

    alignment = _align_beats(beats, shots)
    beat_rows = []
    pair_by_beat = {p["beat_index"]: p for p in alignment.get("pairs") or []}
    for bi, beat in enumerate(beats, 1):
        tr = _parse_time_range(beat)
        pair = pair_by_beat.get(bi) or {}
        beat_rows.append({
            "index": bi,
            "text": beat,
            "time": tr,
            "shot_index": pair.get("shot_index"),
            "alignment": ("time_overlap" if tr and pair else
                          "index_by_count" if pair else "none"),
        })

    product_by_shot = [{
        "index": r["index"],
        "product": r.get("product") or "",
        "product_visibility": r.get("product_visibility") or "",
    } for r in timeline]

    text_by_shot = [{
        "index": r["index"],
        "on_screen_text": r.get("on_screen_text") or "",
    } for r in timeline]

    platform = roles.get("platform") if isinstance(roles.get("platform"), dict) else {}
    platform_notes = []
    for key in ("observations", "inferences", "key_moments"):
        platform_notes.extend(_text(x) for x in _items(platform.get(key)) if _text(x))

    source_sha = ""
    if source_path and source_path.exists():
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

    category_key = _category_key(meta, global_d)
    return {
        "schema_version": SCHEMA_VERSION,
        "ref_id": ref_id,
        "meta": {
            "title": _text(meta.get("title")),
            "category": _text(global_d.get("category")),
            "category_key": category_key,
            "tags": meta.get("tags") or [],
            "duration": meta.get("duration"),
            "source_url": _text(meta.get("source_url")),
            "video": _text(meta.get("path")),
            "shot_count": len(timeline),
            "beat_count": len(beat_rows),
        },
        "structure": {
            "hook": _text(structure.get("hook")),
            "beat_order": beats,
            "beats": beat_rows,
            "proof": _text(structure.get("proof")),
            "cta": _text(structure.get("cta")),
            "beat_shot_alignment": alignment,
        },
        "timeline": timeline,
        "style": {
            "visual_style": _text(global_d.get("visual_style")),
            "global_style": _text(blueprint.get("global_style")),
            "pacing": _text(global_d.get("pacing")),
            "camera_language": _text(global_d.get("camera_language")),
            "lighting": _text(global_d.get("lighting")),
            "color_palette": global_d.get("color_palette") or [],
            "on_screen_text_style": _text(global_d.get("on_screen_text_style")),
        },
        "scene": {
            "description": _text(global_d.get("scene")),
            "reference": _text((blueprint.get("reference_role_map") or {}).get("scene")),
        },
        "product": {
            "description": _text(global_d.get("product")),
            "reference": _text((blueprint.get("reference_role_map") or {}).get("product")),
            "by_shot": product_by_shot,
        },
        "text": {
            "has_transcript": bool(transcript),
            "on_screen_text_style": _text(global_d.get("on_screen_text_style")),
            "reference": _text((blueprint.get("reference_role_map") or {}).get("text")),
            "by_shot": text_by_shot,
            "transcript": transcript,
        },
        "roles": roles,
        "compliance": {"platform_notes": platform_notes},
        "slots": {
            "invariants": [_text(x) for x in
                           _items(blueprint.get("invariants")) if _text(x)],
            "variables": [_text(x) for x in
                          _items(blueprint.get("variables")) if _text(x)],
            "hard_constraints": [_text(x) for x in
                                 _items(blueprint.get("hard_constraints")) if _text(x)],
            "soft_constraints": [_text(x) for x in
                                 _items(blueprint.get("soft_constraints")) if _text(x)],
            "negative": [_text(x) for x in
                         _items(blueprint.get("negative")) if _text(x)],
            "reference_role_map": blueprint.get("reference_role_map") or {},
        },
        "provenance": {
            "descriptions": (str(source_path.relative_to(ROOT))
                             if source_path and source_path.exists() else ""),
            "blueprint": (f"data/reference_cases/{ref_id}/prompt_blueprint.json"),
            "evidence": (f"data/reference_cases/{ref_id}/evidence.json"),
            "source_sha256": source_sha,
            "generated_at": int(time.time()),
        },
    }


def audit_facets(f: dict) -> dict:
    """结构审计：只报事实缺口，不做质量判断。"""
    issues = []
    shots = f.get("timeline") or []
    if not shots:
        issues.append("timeline 为空")
    for s in shots:
        missing = [k for k in _SHOT_FIELDS if s.get(k) in (None, "")]
        if missing:
            issues.append(f"shot {s.get('index')} 缺字段: {','.join(missing)}")
    for k in ("hook", "proof", "cta"):
        if not _text((f.get("structure") or {}).get(k)):
            issues.append(f"structure.{k} 为空")
    if not f.get("structure", {}).get("beat_order"):
        issues.append("structure.beat_order 为空")
    if not f.get("style", {}).get("global_style"):
        issues.append("style.global_style 为空")
    if not f.get("slots", {}).get("invariants"):
        issues.append("slots.invariants 为空")
    alignment = (f.get("structure") or {}).get("beat_shot_alignment") or {}
    warnings = []
    if alignment.get("method") == "none":
        warnings.append("beat 与镜头未对齐")
    elif alignment.get("confidence") == "unverified":
        warnings.append("beat 与镜头按数量暂对齐，语义未校验")
    if not (f.get("text") or {}).get("has_transcript"):
        warnings.append("无 ASR 转写")
    return {"ok": not issues, "issues": issues, "warnings": warnings}


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="案例描述 -> fission facets")
    ap.add_argument("--refs", default=None, help="逗号分隔的 reference id")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="只审计现有 facets，不重建")
    a = ap.parse_args()

    out_dir = Path(a.out)
    ids = [x.strip() for x in (a.refs or "").split(",") if x.strip()] or None
    files = sorted(CASES.glob("*/descriptions.json"))
    if ids:
        files = [p for p in files if p.parent.name in set(ids)]

    if a.check:
        rows = []
        for p in sorted(out_dir.glob("ref-*.json")):
            f = _load_json(p)
            if not f:
                rows.append({"ref_id": p.stem, "ok": False,
                             "issues": ["JSON 解析失败"], "warnings": []})
                continue
            rows.append({"ref_id": f.get("ref_id") or p.stem,
                         **audit_facets(f)})
        bad = [r for r in rows if not r["ok"]]
        warn = [r for r in rows if r["warnings"]]
        for r in rows:
            flag = "OK " if r["ok"] else "BAD"
            print(f"{flag} {r['ref_id']} "
                  f"{' '.join(r['issues'] + r['warnings'])}")
        print(f"\n total={len(rows)} ok={len(rows) - len(bad)} "
              f"bad={len(bad)} warning={len(warn)}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    total_shots = 0
    complete_shots = 0
    for p in files:
        case = _load_json(p)
        if not case:
            print(f"SKIP {p}: JSON 解析失败")
            continue
        ref_id = case.get("ref_id") or p.parent.name
        bp = _load_json(p.parent / "prompt_blueprint.json")
        ev = _load_json(p.parent / "evidence.json")
        f = build_facets(case, bp, ev, p)
        existing = _load_json(out_dir / f"{ref_id}.json")
        if existing and (
                (existing.get("provenance") or {}).get("source_sha256")
                == (f.get("provenance") or {}).get("source_sha256")):
            old_align = (existing.get("structure") or {}).get(
                "beat_shot_alignment") or {}
            if old_align.get("method") == "llm_monotonic":
                # 描述未变时保留已完成的 LLM 语义对齐，避免重建覆盖
                f["structure"] = existing["structure"]
        audit = audit_facets(f)
        total_shots += len(f["timeline"])
        complete_shots += sum(
            1 for s in f["timeline"]
            if all(s.get(k) not in (None, "") for k in _SHOT_FIELDS))
        if not a.dry_run:
            (out_dir / f"{ref_id}.json").write_text(
                json.dumps(f, ensure_ascii=False, indent=2), encoding="utf-8")
        alignment = f["structure"]["beat_shot_alignment"]["method"]
        items.append({
            "ref_id": ref_id,
            "category_key": f["meta"]["category_key"],
            "category": f["meta"]["category"],
            "tags": f["meta"]["tags"],
            "duration": f["meta"]["duration"],
            "shot_count": f["meta"]["shot_count"],
            "beat_count": f["meta"]["beat_count"],
            "alignment_method": alignment,
            "alignment_confidence": f["structure"]["beat_shot_alignment"]["confidence"],
            "has_transcript": f["text"]["has_transcript"],
            "ok": audit["ok"],
            "issues": audit["issues"],
            "warnings": audit["warnings"],
            "path": f"data/reference_facets/{ref_id}.json",
            "source_sha256": f["provenance"]["source_sha256"],
        })
        print(f"{'OK ' if audit['ok'] else 'BAD'} {ref_id} "
              f"shots={f['meta']['shot_count']} beats={f['meta']['beat_count']} "
              f"align={alignment} {','.join(audit['warnings'])}")

    by_category: dict[str, int] = {}
    by_alignment: dict[str, int] = {}
    for it in items:
        by_category[it["category_key"]] = by_category.get(it["category_key"], 0) + 1
        by_alignment[it["alignment_method"]] = \
            by_alignment.get(it["alignment_method"], 0) + 1
    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": int(time.time()),
        "total": len(items),
        "by_category": by_category,
        "by_alignment": by_alignment,
        "coverage": {
            "cases_ok": sum(1 for it in items if it["ok"]),
            "cases_with_transcript": sum(
                1 for it in items if it["has_transcript"]),
            "cases_with_beat_alignment": sum(
                1 for it in items if it["alignment_method"] != "none"),
            "cases_alignment_time_verified": sum(
                1 for it in items
                if it["alignment_method"] == "time_overlap"),
            "cases_alignment_llm": sum(
                1 for it in items
                if it["alignment_method"] == "llm_monotonic"),
            "cases_alignment_llm_high": sum(
                1 for it in items
                if it["alignment_method"] == "llm_monotonic"
                and it["alignment_confidence"] == "high"),
            "total_shots": total_shots,
            "shots_with_complete_fields": complete_shots,
        },
        "items": items,
    }
    if not a.dry_run:
        (out_dir / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: index[k] for k in
                      ("schema_version", "total", "by_category",
                       "by_alignment", "coverage")},
                     ensure_ascii=False, indent=2))
    if a.dry_run:
        print("dry-run: 未写文件")


if __name__ == "__main__":
    main()
