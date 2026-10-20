#!/usr/bin/env python3
"""兼容入口：pipelines.fission.pool.build_digest。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.io import save_json  # noqa: E402
from pipelines.fission.pool import build_digest  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="视频池只读 digest")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    digest = build_digest()
    save_json(out, digest)
    print(json.dumps({"out": str(out),
                      "refs": len(digest["payload"]["refs"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
