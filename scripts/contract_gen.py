#!/usr/bin/env python3
"""兼容入口：pipelines.fission.contracts.build_contract_for_variant。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.contracts import build_contract_for_variant  # noqa: E402
from pipelines.fission.io import load_json  # noqa: E402
from pipelines.fission.pool import anchor_catalog, build_digest  # noqa: E402
from pipelines.fission.profiles import load_profile  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="variant_set -> contracts")
    ap.add_argument("--variants", required=True)
    ap.add_argument("--brief", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--profile", default="bra-milk-lace")
    ap.add_argument("--digest", default=None)
    a = ap.parse_args()
    vset = load_json(Path(a.variants))
    brief = load_json(Path(a.brief))
    profile, _ = load_profile(a.profile)
    digest = load_json(Path(a.digest)) if a.digest else build_digest()
    catalog = anchor_catalog(digest)
    root = Path(a.out_root)
    if not root.is_absolute():
        root = ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    made = []
    for i, v in enumerate(vset["payload"]["variants"], 1):
        info = build_contract_for_variant(
            v, brief, profile, catalog, root / f"v{i:02d}", i)
        made.append(info)
        print(json.dumps(info, ensure_ascii=False))
    print(json.dumps({"contracts": len(made),
                      "valid": sum(1 for x in made if x["valid"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
