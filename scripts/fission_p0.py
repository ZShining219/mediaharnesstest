#!/usr/bin/env python3
"""P0 裂变链路：商品锚定 + 风格采样 + 契约/提示词；--generate 才生成视频。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.p0_runner import run_p0  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="P0 裂变（默认契约；--generate 跑 H3）")
    ap.add_argument("--profile", default="bra-milk-lace")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--text", default=None)
    ap.add_argument("--out-root", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--atlas-dir", default=None)
    ap.add_argument("--person", default=None, help="覆盖 profile 人物图")
    ap.add_argument("--product-image", default=None,
                    help="覆盖 profile 正面商品图（同款另一张照片）")
    ap.add_argument("--prepare-materials", action="store_true",
                    help="先补齐 reference descriptions/facets/alignments")
    ap.add_argument("--refresh-materials", action="store_true",
                    help="强制重读全部参考素材（耗时/有模型成本）")
    ap.add_argument("--generate", action="store_true",
                    help="逐条提交 H3 生成视频")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.refresh_materials:
        a.prepare_materials = True
    res = run_p0(
        a.profile, a.text, a.n, a.out_root, a.seed, a.atlas_dir,
        person=a.person, product_image=a.product_image,
        prepare_materials=a.prepare_materials,
        refresh_materials=a.refresh_materials,
        generate=a.generate,
    )
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"run_dir: {res['run_dir']}")
        print(f"contracts: {len(res['contracts'])}")
        print(f"videos: {len(res.get('videos') or [])}")
        print(f"status: {res['manifest'].get('status')}")
        print(f"audit.ok: {res['audit'].get('ok')}")
        print(json.dumps(res["manifest"].get("audit"), ensure_ascii=False,
                         indent=2))


if __name__ == "__main__":
    main()
