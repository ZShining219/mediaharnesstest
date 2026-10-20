#!/usr/bin/env python3
"""参考案例 -> 约束模板 -> N 条裂变素材（H3）。

用法:
    # 只检索+泛化+生成方案，不生成视频
    .venv/bin/python scripts/reference_fission.py --no-generate

    # 完整链路，生成 5 条
    .venv/bin/python scripts/reference_fission.py --n 5
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import reference_fission  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="参考视频池裂变")
    ap.add_argument("--ref-id", default="ref-1792419234-1471",
                    help="用于提取商品图的参考视频 ID")
    ap.add_argument("--time", type=float, default=8.0,
                    help="提取商品图的秒数")
    ap.add_argument("--person", default="assets/persons/半身照.png")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--bgm", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="只输出方向和模板，不建方案")
    ap.add_argument("--no-generate", action="store_true",
                    help="生成 DirectorPlan，但不调用 H3")
    a = ap.parse_args()
    res = reference_fission.run_full(
        ref_id=a.ref_id, product_time=a.time, person=a.person,
        n=a.n, bgm=a.bgm, dry_run=a.dry_run,
        no_generate=a.no_generate)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
