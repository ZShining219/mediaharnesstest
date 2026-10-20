#!/usr/bin/env python3
"""兼容入口：pipelines.fission.guidance.synthesize_guidance。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.guidance import synthesize_guidance  # noqa: E402
from pipelines.fission.io import load_json, save_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="brief + pool -> guidance")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--digest", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    brief = load_json(Path(a.brief))
    digest = load_json(Path(a.digest))
    guidance = synthesize_guidance(brief, digest)
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    save_json(out, guidance)
    print(json.dumps({"out": str(out),
                      "patterns": len(guidance["payload"]["patterns"]),
                      "directions": len(guidance["payload"]["candidate_directions"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
