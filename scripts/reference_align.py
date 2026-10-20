#!/usr/bin/env python3
"""LLM 语义对齐：把 case 的叙事 beat_order 对到逐镜时间轴。

只处理 facet 里 alignment_method=none 的案例；结果写回：
    data/reference_alignments/{ref_id}.json   # 原始对齐结果（可追溯）
    data/reference_facets/{ref_id}.json       # structure.beat_shot_alignment + beats
    data/reference_facets/index.json          # 对齐状态汇总

约束：
- 单调对齐：后面的 beat 不能对到更早的镜头；
- 一个 beat 可跨多个连续镜头，每个镜头最多归属一个 beat；
- 无法在画面中落地的 beat 进 unmatched_beats，并说明原因。

用法：
    .venv/bin/python scripts/reference_align.py                 # 全部未对齐案例
    .venv/bin/python scripts/reference_align.py --refs ref-a,ref-b
    .venv/bin/python scripts/reference_align.py --include-unverified
    .venv/bin/python scripts/reference_align.py --force
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import config as C, llm  # noqa: E402
from orchestrator.app.jsonutil import extract_json  # noqa: E402

FACETS_DIR = ROOT / "data" / "reference_facets"
ALIGN_DIR = ROOT / "data" / "reference_alignments"
PROMPT_VERSION = "beat-align/v1"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _confidence_label(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "low"
    if v >= 0.8:
        return "high"
    if v >= 0.6:
        return "medium"
    return "low"


def _transcript_for(shot: dict, transcript: list[dict]) -> str:
    try:
        t0, t1 = float(shot["time"][0]), float(shot["time"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return ""
    parts = []
    for seg in transcript or []:
        try:
            s0, s1 = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if s1 > t0 and s0 < t1 and str(seg.get("text") or "").strip():
            parts.append(str(seg["text"]).strip())
    return " / ".join(parts)


def _prompt_payload(f: dict) -> dict:
    transcript = (f.get("text") or {}).get("transcript") or []
    return {
        "ref_id": f.get("ref_id"),
        "duration": (f.get("meta") or {}).get("duration"),
        "beats": [{
            "beat_index": b.get("index"),
            "text": b.get("text"),
            "time": b.get("time"),
        } for b in ((f.get("structure") or {}).get("beats") or [])],
        "shots": [{
            "shot_index": s.get("index"),
            "time": s.get("time"),
            "duration": s.get("duration"),
            "shot_size": s.get("shot_size"),
            "angle": s.get("angle"),
            "camera": s.get("camera"),
            "lighting": s.get("lighting"),
            "composition": s.get("composition"),
            "subject": s.get("subject"),
            "action": s.get("action"),
            "product": s.get("product"),
            "on_screen_text": s.get("on_screen_text"),
            "transcript": _transcript_for(s, transcript),
            "blueprint_prompt": (s.get("blueprint_prompt") or "")[:400],
        } for s in (f.get("timeline") or [])],
    }


def _build_prompt(f: dict) -> str:
    payload = json.dumps(_prompt_payload(f), ensure_ascii=False, indent=1)
    n_beats = len((f.get("structure") or {}).get("beats") or [])
    n_shots = len(f.get("timeline") or [])
    return f"""你是视频结构对齐助手。下面是一条参考视频的叙事 beat 列表和逐镜视觉事实。
请把每个 beat 对齐到它实际发生的镜头。

规则：
1. 允许一个 beat 跨越多个【连续】镜头；也允许一个镜头承载多个【连续】beat
   （例如一个长镜头里连续讲两个卖点）。
2. 必须保持时间顺序：后一个 beat 的 shot_indices 不能整体早于前一个 beat；
   即 beat 的起始镜头和结束镜头都必须单调不减。
3. 只根据给定事实判断，不要脑补；画面文字、逐镜口播转写（transcript）和
   blueprint_prompt 都可以作为证据。口播型 beat（痛点、功能、价格、CTA）
   应优先看 transcript，不要因为画面没字就判为未落地。
4. 只有在画面和口播都找不到证据时，才把 beat 放入 unmatched_beats，并说明原因。
5. 每个 beat 必须出现一次：要么在 alignments，要么在 unmatched_beats。
6. 本案例共 {n_beats} 个 beat、{n_shots} 个镜头。
7. 当 beat 数多于镜头数时，必然存在一个镜头承载多个连续 beat；
   不要以“镜头已被占用”为由把 beat 标为 unmatched。只有画面和口播都找不到
   任何证据时，才允许 unmatched。

输出 JSON（不要输出其他内容）：
{{
 "alignments": [
   {{"beat_index": 1, "shot_indices": [1], "confidence": 0.0,
     "evidence": "shot 1 的画面依据"}}
 ],
 "unmatched_beats": [
   {{"beat_index": 6, "reason": "该 beat 为口播/促销，画面无对应"}}
 ],
 "unmatched_shots": [
   {{"shot_index": 8, "reason": "该镜头未被任何 beat 覆盖"}}
 ],
 "overall_confidence": 0.0,
 "summary": "一句话总结对齐质量与主要不确定点"
}}

数据：
{payload}"""


def _validate(data: dict, n_beats: int, n_shots: int) -> list[str]:
    errs: list[str] = []
    al = data.get("alignments")
    if not isinstance(al, list) or not al:
        return ["alignments 为空或不是数组"]

    seen_beats: list[int] = []
    covered: list[int] = []
    prev_start = prev_end = 0
    for x in al:
        if not isinstance(x, dict):
            errs.append("alignments 项不是对象")
            continue
        try:
            bi = int(x.get("beat_index"))
        except (TypeError, ValueError):
            errs.append("beat_index 不是整数")
            continue
        try:
            sis = [int(s) for s in (x.get("shot_indices") or [])]
        except (TypeError, ValueError):
            errs.append(f"beat {bi} 的 shot_indices 不是整数数组")
            continue
        if not (1 <= bi <= n_beats):
            errs.append(f"beat_index={bi} 越界")
        if bi in seen_beats:
            errs.append(f"beat {bi} 重复")
        if not sis:
            errs.append(f"beat {bi} 没有 shot_indices")
        if any(not (1 <= s <= n_shots) for s in sis):
            errs.append(f"beat {bi} 的 shot_indices 越界: {sis}")
        if sis != sorted(set(sis)):
            errs.append(f"beat {bi} 的 shot_indices 未升序或重复: {sis}")
        if sis and sis != list(range(min(sis), max(sis) + 1)):
            errs.append(f"beat {bi} 的 shot_indices 不连续: {sis}")
        if sis and (min(sis) < prev_start or max(sis) < prev_end):
            errs.append(f"beat {bi} 破坏单调顺序")
        if sis:
            prev_start, prev_end = min(sis), max(sis)
        try:
            c = float(x.get("confidence"))
            if not (0 <= c <= 1):
                errs.append(f"beat {bi} confidence 越界")
        except (TypeError, ValueError):
            errs.append(f"beat {bi} confidence 非数值")
        seen_beats.append(bi)
        covered.extend(sis)

    ub = data.get("unmatched_beats") or []
    if not isinstance(ub, list):
        errs.append("unmatched_beats 不是数组")
        ub = []
    unmatched_ids = []
    for x in ub:
        try:
            unmatched_ids.append(int(x.get("beat_index")))
        except (TypeError, ValueError):
            errs.append("unmatched_beats 的 beat_index 不是整数")
    all_ids = set(seen_beats) | set(unmatched_ids)
    if all_ids != set(range(1, n_beats + 1)):
        missing = sorted(set(range(1, n_beats + 1)) - all_ids)
        extra = sorted(all_ids - set(range(1, n_beats + 1)))
        if missing:
            errs.append(f"beat 未覆盖: {missing}")
        if extra:
            errs.append(f"beat 越界: {extra}")
    if set(unmatched_ids) & set(seen_beats):
        errs.append("beat 同时出现在 alignments 和 unmatched_beats")

    us = data.get("unmatched_shots") or []
    if not isinstance(us, list):
        errs.append("unmatched_shots 不是数组")
    else:
        for x in us:
            try:
                si = int(x.get("shot_index"))
            except (TypeError, ValueError):
                errs.append("unmatched_shots 的 shot_index 不是整数")
                continue
            if si in covered:
                errs.append(f"shot {si} 同时被 beat 覆盖和标为未覆盖")
    return errs


def _normalize(data: dict, n_shots: int) -> dict:
    al = sorted((x for x in (data.get("alignments") or [])
                 if isinstance(x, dict)),
                key=lambda x: int(x.get("beat_index") or 0))
    for x in al:
        x["shot_indices"] = [int(s) for s in (x.get("shot_indices") or [])]
        try:
            x["confidence"] = round(float(x.get("confidence")), 3)
        except (TypeError, ValueError):
            x["confidence"] = 0.0
    ub = [x for x in (data.get("unmatched_beats") or [])
          if isinstance(x, dict)]
    us = [x for x in (data.get("unmatched_shots") or [])
          if isinstance(x, dict)]
    covered = {s for x in al for s in x["shot_indices"]}
    covered_reasons = {int(x.get("shot_index")): x.get("reason") or ""
                       for x in us}
    us = [{"shot_index": i,
           "reason": covered_reasons.get(i) or "未被任何 beat 覆盖"}
          for i in range(1, n_shots + 1) if i not in covered]
    try:
        overall = round(float(data.get("overall_confidence")), 3)
    except (TypeError, ValueError):
        overall = 0.0
    return {
        "alignments": al,
        "unmatched_beats": ub,
        "unmatched_shots": us,
        "overall_confidence": max(0.0, min(1.0, overall)),
        "summary": str(data.get("summary") or "").strip(),
    }


def _call_llm(f: dict, model: str) -> dict:
    client = llm.LLM(model=model, timeout=180)
    prompt = _build_prompt(f)
    last_err = None
    for attempt in range(2):
        user = prompt
        if attempt:
            user += ("\n\n上一次输出未通过校验："
                     + "; ".join(last_err or [])
                     + "\n请修正并只输出合法 JSON。")
        txt = client.chat(user, max_tokens=4000,
                          temperature=0.1 if attempt == 0 else 0.0,
                          json_mode=True)
        data = extract_json(txt)
        if not isinstance(data, dict):
            last_err = ["JSON 解析失败"]
            continue
        n_beats = len((f.get("structure") or {}).get("beats") or [])
        n_shots = len(f.get("timeline") or [])
        errs = _validate(data, n_beats, n_shots)
        if not errs:
            return _normalize(data, n_shots)
        last_err = errs
    raise RuntimeError("对齐校验失败: " + "; ".join(last_err or []))


def _apply(f: dict, result: dict) -> dict:
    st = f.setdefault("structure", {})
    old = st.get("beat_shot_alignment") or {}
    if old.get("method") != "llm_monotonic":
        st["beat_shot_alignment_auto"] = old
    pair_by_beat = {int(x["beat_index"]): x for x in result["alignments"]}
    unmatched = {int(x.get("beat_index")): x
                 for x in result.get("unmatched_beats") or []}
    for b in st.get("beats") or []:
        bi = int(b.get("index") or 0)
        x = pair_by_beat.get(bi)
        if x:
            b["shot_index"] = x["shot_indices"][0]
            b["shot_indices"] = x["shot_indices"]
            b["alignment"] = "llm_monotonic"
            b["confidence"] = x.get("confidence")
            b["evidence"] = x.get("evidence") or ""
            b.pop("reason", None)
        else:
            b["shot_index"] = None
            b["shot_indices"] = []
            b["alignment"] = "unmatched"
            b["confidence"] = 0
            b["reason"] = (unmatched.get(bi) or {}).get("reason") or ""
    st["beat_shot_alignment"] = {
        "method": "llm_monotonic",
        "confidence": _confidence_label(result.get("overall_confidence")),
        "overall_confidence": result.get("overall_confidence"),
        "pairs": [{
            "beat_index": x["beat_index"],
            "shot_indices": x["shot_indices"],
            "confidence": x.get("confidence"),
            "evidence": x.get("evidence") or "",
        } for x in result["alignments"]],
        "unmatched_beats": result.get("unmatched_beats") or [],
        "unmatched_shots": result.get("unmatched_shots") or [],
        "note": result.get("summary") or "",
        "model": result.get("model"),
        "prompt_version": PROMPT_VERSION,
        "generated_at": result.get("generated_at"),
    }
    return f


def _update_index(updates: dict[str, dict]):
    path = FACETS_DIR / "index.json"
    idx = _load(path)
    if not idx:
        return
    items = idx.get("items") or []
    for it in items:
        rid = it.get("ref_id")
        if rid not in updates:
            continue
        r = updates[rid]
        it["alignment_method"] = "llm_monotonic"
        it["alignment_confidence"] = _confidence_label(r.get("overall_confidence"))
        it["alignment_llm_confidence"] = r.get("overall_confidence")
        warns = [w for w in (it.get("warnings") or [])
                 if "beat 与镜头" not in w]
        if r.get("unmatched_beats"):
            warns.append(f"{len(r['unmatched_beats'])} 个 beat 无画面对应")
        if float(r.get("overall_confidence") or 0) < 0.6:
            warns.append("LLM 对齐置信度偏低")
        it["warnings"] = warns
    by_alignment: dict[str, int] = {}
    for it in items:
        m = it.get("alignment_method") or "none"
        by_alignment[m] = by_alignment.get(m, 0) + 1
    idx["by_alignment"] = by_alignment
    cov = idx.setdefault("coverage", {})
    cov["cases_with_beat_alignment"] = sum(
        1 for it in items if it.get("alignment_method") != "none")
    cov["cases_alignment_time_verified"] = sum(
        1 for it in items if it.get("alignment_method") == "time_overlap")
    cov["cases_alignment_llm"] = sum(
        1 for it in items if it.get("alignment_method") == "llm_monotonic")
    cov["cases_alignment_llm_high"] = sum(
        1 for it in items if it.get("alignment_method") == "llm_monotonic"
        and it.get("alignment_confidence") == "high")
    cov.pop("cases_alignment_verified", None)
    _dump(path, idx)


def main():
    ap = argparse.ArgumentParser(description="LLM beat -> shot 语义对齐")
    ap.add_argument("--refs", default=None, help="逗号分隔的 reference id")
    ap.add_argument("--include-unverified", action="store_true",
                    help="同时重做 index_by_count 的暂对齐")
    ap.add_argument("--force", action="store_true",
                    help="已有 llm 对齐也重做")
    ap.add_argument("--model", default=C.env("REFERENCE_LLM_MODEL", "deepseek-chat"))
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()

    ids = {x.strip() for x in (a.refs or "").split(",") if x.strip()}
    files = sorted(FACETS_DIR.glob("ref-*.json"))
    targets = []
    for p in files:
        f = _load(p)
        if not f:
            continue
        if ids and f.get("ref_id") not in ids:
            continue
        align = (f.get("structure") or {}).get("beat_shot_alignment") or {}
        method = align.get("method")
        if method == "llm_monotonic" and not a.force:
            continue
        if method == "none" or ids or a.include_unverified or a.force:
            targets.append((p, f))
    if ids:
        targets = [(p, f) for p, f in targets
                   if f.get("ref_id") in ids]

    print(f"targets={len(targets)} model={a.model}")
    updates: dict[str, dict] = {}

    def work(p: Path, f: dict):
        rid = f.get("ref_id") or p.stem
        t0 = time.time()
        result = _call_llm(f, a.model)
        result.update({
            "ref_id": rid,
            "model": a.model,
            "prompt_version": PROMPT_VERSION,
            "generated_at": int(time.time()),
            "source_sha256": (f.get("provenance") or {}).get("source_sha256"),
        })
        _dump(ALIGN_DIR / f"{rid}.json", result)
        f2 = _apply(f, result)
        _dump(p, f2)
        return rid, result, time.time() - t0

    if a.workers <= 1:
        for p, f in targets:
            try:
                rid, r, dt = work(p, f)
                updates[rid] = r
                print(f"OK  {rid} conf={r.get('overall_confidence')} "
                      f"beats={len(r['alignments'])}/{len(r.get('unmatched_beats') or [])} "
                      f"{dt:.1f}s")
            except Exception as e:
                print(f"BAD {p.stem}: {type(e).__name__}: {e}")
    else:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(work, p, f): (p, f) for p, f in targets}
            for fut in as_completed(futs):
                p, f = futs[fut]
                try:
                    rid, r, dt = fut.result()
                    updates[rid] = r
                    print(f"OK  {rid} conf={r.get('overall_confidence')} "
                          f"beats={len(r['alignments'])}/{len(r.get('unmatched_beats') or [])} "
                          f"{dt:.1f}s")
                except Exception as e:
                    print(f"BAD {p.stem}: {type(e).__name__}: {e}")

    _update_index(updates)
    print(f"\nupdated={len(updates)}/{len(targets)} alignments={ALIGN_DIR}")


if __name__ == "__main__":
    main()
