#!/usr/bin/env python3
"""兼容入口：调用 pipelines.fission.runner。

推荐：
    .venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --n 3
    .venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --skip-generate
    .venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --resume \
      --out-root data/runs/fission-bra-milk-lace-...
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.runner import main  # noqa: E402

if __name__ == "__main__":
    main()
