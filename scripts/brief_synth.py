#!/usr/bin/env python3
"""兼容入口：pipelines.fission.brief.synthesize_brief。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.brief import synthesize_brief  # noqa: E402
from pipelines.fission.io import save_json  # noqa: E402
from pipelines.fission.profiles import load_profile  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="商品图 -> 动态 brief")
    ap.add_argument("--profile", default="bra-milk-lace")
    ap.add_argument("--product-image", default=None)
    ap.add_argument("--person-image", default=None)
    ap.add_argument("--text", default=None)
    ap.add_argument("--deliverables", type=int, default=3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    profile, _ = load_profile(a.profile)
    if a.product_image:
        profile["image"] = a.product_image
    text = a.text or (f"商品是{profile.get('category')}，人物用固定人物图，"
                      f"产出{a.deliverables}条裂变素材")
    brief = synthesize_brief(profile, text, a.deliverables, a.person_image)
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    save_json(out, brief)
    print(json.dumps({"out": str(out),
                      "facts": len(brief["payload"].get("facts") or []),
                      "unknowns": len(brief["payload"].get("unknowns") or []),
                      "assumptions": len(brief["payload"].get("assumptions") or [])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
