#!/usr/bin/env python3
"""重建可派生索引：reference_cases / fission_slices / plans。

这些索引永远可重建，不作为事实源；事实源是目录与各产物的 JSON。

用法：
    .venv/bin/python scripts/build_indexes.py --all
    .venv/bin/python scripts/build_indexes.py --cases
    .venv/bin/python scripts/build_indexes.py --slices
    .venv/bin/python scripts/build_indexes.py --plans
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "reference_cases"
SLICES = ROOT / "data" / "fission_slices"
PLANS = ROOT / "data" / "plans"
RUNS = ROOT / "data" / "reference_runs"
EXPORTS = ROOT / "outputs" / "fission"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def build_cases() -> dict:
    items = []
    for d in sorted(CASES.glob("ref-*")):
        if not d.is_dir():
            continue
        desc = _load(d / "descriptions.json")
        if not isinstance(desc, dict):
            continue
        ev = _load(d / "evidence.json") or {}
        meta = desc.get("meta") or {}
        items.append({
            "id": d.name,
            "ok": True,
            "shots": len(desc.get("shots") or []),
            "frames": len(ev.get("frames") or []),
            "transcript": len(desc.get("transcript") or []),
            "video": meta.get("path") or "",
        })
    index = {
        "generated_at": int(time.time()),
        "total": len(items),
        "ok": sum(1 for x in items if x["ok"]),
        "failed": sum(1 for x in items if not x["ok"]),
        "items": items,
    }
    _dump(CASES / "index.json", index)
    return index


def build_slices() -> dict:
    items = []
    for d in sorted(SLICES.glob("slice-*")):
        if not d.is_dir():
            continue
        c = _load(d / "contract.json")
        if not isinstance(c, dict):
            continue
        run = _load(d / "run.json") or {}
        video = run.get("video") or (
            _rel(d / "variant_contract.mp4")
            if (d / "variant_contract.mp4").exists() else None)
        items.append({
            "slice_id": c.get("slice_id") or d.name,
            "ref_id": (c.get("target") or {}).get("ref_id"),
            "direction": (c.get("structure") or {}).get("name"),
            "duration": ((c.get("target") or {}).get("format") or {}).get("duration"),
            "validation_ok": (c.get("_validation") or {}).get("ok"),
            "contract": _rel(d / "contract.json"),
            "prompt": (_rel(d / "prompt_h3.txt")
                       if (d / "prompt_h3.txt").exists() else None),
            "video": video,
            "review": run.get("review_path"),
            "run_status": run.get("status") or (
                "generated" if video else "contract_only"),
            "created_at": run.get("created_at") or int(
                (d / "contract.json").stat().st_mtime),
        })
    index = {
        "schema_version": "fission-slices-index/v1",
        "generated_at": int(time.time()),
        "total": len(items),
        "items": items,
    }
    _dump(SLICES / "index.json", index)
    return index


def _plan_run_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(RUNS.glob("*/plans.json")):
        plans = _load(p) or []
        if not isinstance(plans, list):
            continue
        for plan in plans:
            pid = (plan or {}).get("id")
            if pid:
                out[pid] = {"run_id": p.parent.name, "run_path": _rel(p)}
    for p in sorted(EXPORTS.glob("*/manifest.json")):
        man = _load(p) or {}
        for item in man.get("items") or []:
            pid = item.get("plan_id")
            if pid and pid not in out:
                out[pid] = {
                    "run_id": man.get("run_id") or p.parent.name,
                    "run_path": _rel(p),
                }
    return out


def _plan_review_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted((ROOT / "outputs" / "review").glob("*.json")):
        item = _load(p) or {}
        pid = item.get("plan_id")
        if pid:
            out[pid] = {
                "id": item.get("id") or p.stem,
                "title": item.get("title") or "",
                "status": item.get("status") or "",
            }
    return out


def _plan_job_map() -> dict[str, dict]:
    """从 jobs.db 找 plan_id 引用；用于区分历史任务 plan 与真正孤立的 plan。"""
    out: dict[str, dict] = {}
    db = ROOT / "data" / "jobs.db"
    if not db.exists():
        return out
    try:
        con = sqlite3.connect(db)
        rows = con.execute(
            "select id,type,status,params from jobs").fetchall()
        con.close()
    except Exception:
        return out
    for jid, jtype, status, params in rows:
        try:
            p = json.loads(params or "{}")
        except Exception:
            continue
        pid = p.get("plan_id")
        if not pid:
            continue
        d = out.setdefault(pid, {"count": 0, "statuses": [], "job_ids": []})
        d["count"] += 1
        d["statuses"].append(status)
        d["job_ids"].append(jid)
    return out


def build_plans() -> dict:
    run_map = _plan_run_map()
    review_map = _plan_review_map()
    job_map = _plan_job_map()
    items = []
    for p in sorted(PLANS.glob("pvplan-*.json")):
        plan = _load(p)
        if not isinstance(plan, dict):
            continue
        pid = plan.get("id") or p.stem
        meta = plan.get("meta") or {}
        owner = run_map.get(pid) or {}
        review = review_map.get(pid) or {}
        jobs = job_map.get(pid) or {}
        items.append({
            "plan_id": pid,
            "title": plan.get("title") or "",
            "file": _rel(p),
            "created_at": int(p.stat().st_mtime),
            "duration": meta.get("duration"),
            "generation_mode": meta.get("generation_mode")
            or plan.get("generation_mode"),
            "run_id": owner.get("run_id"),
            "run_path": owner.get("run_path"),
            "review_item": review.get("id"),
            "review_title": review.get("title"),
            "jobs": jobs.get("count", 0),
            "job_statuses": sorted(set(jobs.get("statuses") or [])),
            "owner": ("fission_run" if owner.get("run_id")
                      else "review_item" if review.get("id")
                      else "job_history" if jobs.get("count")
                      else "unlinked"),
        })
    index = {
        "schema_version": "plans-index/v1",
        "generated_at": int(time.time()),
        "total": len(items),
        "items": items,
    }
    _dump(PLANS / "plan_index.json", index)
    return index


def main():
    ap = argparse.ArgumentParser(description="重建派生索引")
    ap.add_argument("--cases", action="store_true")
    ap.add_argument("--slices", action="store_true")
    ap.add_argument("--plans", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    run_all = a.all or not (a.cases or a.slices or a.plans)
    out = {}
    if run_all or a.cases:
        idx = build_cases()
        out["cases"] = {"total": idx["total"], "index": _rel(CASES / "index.json")}
    if run_all or a.slices:
        idx = build_slices()
        out["slices"] = {"total": idx["total"], "index": _rel(SLICES / "index.json")}
    if run_all or a.plans:
        idx = build_plans()
        out["plans"] = {"total": idx["total"], "index": _rel(PLANS / "plan_index.json")}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
