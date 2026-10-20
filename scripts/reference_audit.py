#!/usr/bin/env python3
"""审计参考案例描述的结构完整性，可选重跑异常案例。

用法:
    .venv/bin/python scripts/reference_audit.py
    .venv/bin/python scripts/reference_audit.py --reanalyze-bad
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import reference_analysis, reference_pool  # noqa: E402

CASES = ROOT / "data" / "reference_cases"


def audit_one(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"id": path.parent.name, "ok": False, "error": f"json: {e}"}
    issues = []
    shots = d.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append("shots 为空")
    roles = d.get("roles")
    if not isinstance(roles, dict):
        issues.append("roles 不是 dict")
    else:
        for r, v in roles.items():
            if not isinstance(v, dict):
                issues.append(f"role {r} 不是 dict")
            elif not (v.get("observations") or v.get("inferences")):
                issues.append(f"role {r} 为空")
    bp = d.get("blueprint")
    if not isinstance(bp, dict):
        issues.append("blueprint 不是 dict")
    elif not bp.get("global_style") and not bp.get("shot_prompts"):
        issues.append("blueprint 为空")
    return {
        "id": d.get("ref_id") or path.parent.name,
        "ok": not issues,
        "shots": len(shots) if isinstance(shots, list) else 0,
        "roles_nonempty": sum(
            1 for v in (roles or {}).values()
            if isinstance(v, dict)
            and (v.get("observations") or v.get("inferences"))),
        "transcript": len(d.get("transcript") or []),
        "issues": issues,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reanalyze-bad", action="store_true")
    a = ap.parse_args()
    rows = [audit_one(p) for p in sorted(CASES.glob("*/descriptions.json"))]
    for r in rows:
        flag = "OK " if r.get("ok") else "BAD"
        print(f"{flag} {r.get('id')} shots={r.get('shots')} "
              f"roles={r.get('roles_nonempty')} asr={r.get('transcript')} "
              f"{' '.join(r.get('issues') or [])}")
    bad = [r["id"] for r in rows if not r.get("ok")]
    missing = [x["id"] for x in reference_pool.list_items()
               if x["id"] not in {r["id"] for r in rows}]
    print(f"\n total={len(rows)} ok={sum(1 for r in rows if r.get('ok'))} "
          f"bad={len(bad)} missing={len(missing)}")
    if missing:
        print(" missing:", ", ".join(missing))
    if a.reanalyze_bad and (bad or missing):
        ids = sorted(set(bad + missing))
        print(" reanalyze:", ", ".join(ids))
        res = reference_analysis.analyze_pool(ids=ids, force=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
