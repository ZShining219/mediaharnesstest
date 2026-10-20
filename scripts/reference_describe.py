#!/usr/bin/env python3
"""批量描述参考视频池。

用法:
    .venv/bin/python scripts/reference_describe.py --limit 3 --no-transcribe
    .venv/bin/python scripts/reference_describe.py --ids ref-xxx,ref-yyy
    .venv/bin/python scripts/reference_describe.py --force
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import reference_analysis, reference_retrieval  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="参考视频池 -> 多角色描述/蓝图")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", default=None, help="逗号分隔的 reference id")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-transcribe", action="store_true")
    ap.add_argument("--no-index", action="store_true")
    a = ap.parse_args()
    ids = [x.strip() for x in (a.ids or "").split(",") if x.strip()] or None
    res = reference_analysis.analyze_pool(
        limit=a.limit, ids=ids, force=a.force,
        transcribe_audio=not a.no_transcribe)
    if not a.no_index:
        idx = reference_retrieval.build_index()
        res["index"] = idx
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
