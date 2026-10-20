#!/usr/bin/env python3
"""提交一条 fission contract 到 H3，并把成片放进审核队列。

用法：
    .venv/bin/python scripts/run_contract.py
    .venv/bin/python scripts/run_contract.py --force
    .venv/bin/python scripts/run_contract.py --contract data/fission_slices/xxx/contract.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import config as C, media, minimax, store  # noqa: E402

SLICE_DIR = ROOT / "data" / "fission_slices" / "slice-1471-direction1"


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def main():
    ap = argparse.ArgumentParser(description="H3 生成一条契约切片")
    ap.add_argument("--contract", default=str(SLICE_DIR / "contract.json"))
    ap.add_argument("--prompt", default=str(SLICE_DIR / "prompt_h3.txt"))
    ap.add_argument("--image", default=None)
    ap.add_argument("--out", default=str(SLICE_DIR))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    contract_path = Path(a.contract)
    prompt_path = Path(a.prompt)
    out = Path(a.out)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    prompt = prompt_path.read_text(encoding="utf-8")
    image = Path(a.image) if a.image else (
        ROOT / (contract.get("target", {}).get("product", {}).get("image") or ""))
    if not image.exists():
        raise SystemExit(f"商品图不存在: {image}")
    dst = out / "variant_contract.mp4"
    if dst.exists() and not a.force:
        print(f"已存在 {dst}；如需重跑加 --force")
        return

    fmt = contract.get("target", {}).get("format") or {}
    duration = int(fmt.get("duration") or 12)
    resolution = fmt.get("resolution") or "768P"
    ratio = fmt.get("aspect_ratio") or "9:16"
    slice_id = contract.get("slice_id") or "contract-slice"

    jid = store.job_create("fission_slice", {
        "slice_id": slice_id,
        "contract": str(contract_path),
        "prompt_chars": len(prompt),
        "image": str(image),
        "duration": duration,
        "resolution": resolution,
        "ratio": ratio,
    })
    store.job_update(jid, {"phase": "submitting"})
    print(f"[{time.strftime('%H:%M:%S')}] job={jid} submit "
          f"{duration}s {resolution} {ratio} image={image.name}", flush=True)

    mm = minimax.Minimax()
    content = [
        minimax.Minimax.part_text(prompt),
        minimax.Minimax.part_image(media.ref_image(image)),
    ]
    key = (f"{slice_id}-v{int(time.time())}" if a.force
           else f"{slice_id}-v1")
    try:
        tid = mm.video_generate_safe(
            content, duration=duration, resolution=resolution, ratio=ratio,
            idempotency_key=key)
        store.job_update(jid, {
            "provider_task": tid, "provider_via": mm.via,
            "phase": "generating",
        })
        print(f"[{time.strftime('%H:%M:%S')}] task={tid} via={mm.via}",
              flush=True)
        task = mm.video_wait(tid)
        raw = C.TMP_DIR / f"{jid}_raw.mp4"
        final = C.TMP_DIR / f"{jid}_final.mp4"
        mm.download(mm.video_url(task), raw)
        media.trim_silent(raw, final, duration)
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final, dst)

        beats = (contract.get("structure") or {}).get("beats") or []
        meta = {
            "title": "切片对比：方向一·指尖倒计时（契约版）",
            "desc": (contract.get("structure") or {}).get("concept") or "",
            "slice_id": slice_id,
            "generation_mode": "single",
            "prompt": prompt,
            "constraints": {
                "product": contract.get("target", {}).get("product") or {},
                "global": contract.get("target", {}).get("format") or {},
            },
            "inputs": [
                {"label": "商品图1", "kind": "image", "path": str(image)},
                {"label": "整条视频提示词", "kind": "text", "text": prompt},
                {"label": "契约", "kind": "text", "text": json.dumps({
                    "slice_id": slice_id,
                    "structure": contract.get("structure") or {},
                    "facet_coverage": contract.get("facet_coverage") or {},
                }, ensure_ascii=False)},
            ],
            "shots": [{
                "index": b.get("index"),
                "duration": b.get("duration"),
                "shot_function": b.get("function_label"),
                "product_evidence": b.get("product_evidence") or [],
                "prompt": b.get("action") or "",
            } for b in beats],
        }
        review_path = store.add_review_item(dst, "product_video", meta)
        shutil.copy2(review_path, dst)
        run_info = {
            "schema_version": "slice-run/v1",
            "status": "generated",
            "job": jid,
            "provider_task": tid,
            "provider_via": mm.via,
            "contract": _rel(contract_path),
            "prompt": _rel(prompt_path),
            "image": _rel(image),
            "review_path": _rel(review_path),
            "video": _rel(dst),
            "prompt_chars": len(prompt),
            "duration": duration,
            "resolution": resolution,
            "ratio": ratio,
            "created_at": int(time.time()),
        }
        (out / "run.json").write_text(
            json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8")
        store.job_finish(jid, "done", run_info)
        print(json.dumps(run_info, ensure_ascii=False, indent=2), flush=True)
    except Exception as e:
        try:
            store.job_finish(jid, "error", {"error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass
        print(f"FAILED {type(e).__name__}: {e}", flush=True)
        raise


if __name__ == "__main__":
    main()
