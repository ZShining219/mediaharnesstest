#!/usr/bin/env python3
"""兼容入口：pipelines.fission.variants.generate_variants。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.io import load_json, save_json  # noqa: E402
from pipelines.fission.variants import generate_variants  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="brief + guidance -> variants")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--guidance", required=True)
    ap.add_argument("--digest", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    brief = load_json(Path(a.brief))
    guidance = load_json(Path(a.guidance))
    digest = load_json(Path(a.digest))
    vset = generate_variants(brief, guidance, digest, a.n)
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    save_json(out, vset)
    print(json.dumps({"out": str(out),
                      "variants": len(vset["payload"]["variants"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
