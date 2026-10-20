#!/usr/bin/env python3
"""outputs 生命周期清理（默认 dry-run，不删任何东西）。

范围仅限：
  outputs/tmp      超过 --tmp-days 的文件
  outputs/failed   超过 --failed-days 的文件
  outputs/review   超过 --review-days 或超出 --review-max 的 pending 条目
                    （媒体与同名 sidecar 成对删除；非 pending 永不删除）

用法：
    .venv/bin/python scripts/cleanup_outputs.py
    .venv/bin/python scripts/cleanup_outputs.py --apply
    .venv/bin/python scripts/cleanup_outputs.py --json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
MEDIA_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".jpg", ".jpeg",
             ".png", ".webp", ".mp3", ".wav"}


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _age_days(ts: float) -> float:
    return (time.time() - float(ts)) / 86400.0


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _collect_by_age(root: Path, days: float) -> list[dict]:
    out = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file() or p.name in (".gitkeep", ".DS_Store"):
            continue
        if not _within(p, root):
            continue
        age = _age_days(p.stat().st_mtime)
        if age > days:
            out.append({"path": p, "age_days": round(age, 1),
                        "size": p.stat().st_size})
    return out


def _collect_review(review: Path, days: float, keep_max: int) -> list[dict]:
    """按 created_at 排序；保留最新 keep_max 条，其余只删 pending。"""
    items = []
    for side in review.glob("*.json"):
        d = _load(side)
        if not isinstance(d, dict):
            continue
        ts = d.get("created_at") or side.stat().st_mtime
        items.append({
            "id": d.get("id") or side.stem,
            "status": d.get("status") or "pending",
            "created_at": float(ts),
            "age_days": round(_age_days(ts), 1),
            "sidecar": side,
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    out = []
    for i, it in enumerate(items):
        if it["status"] != "pending":
            continue
        if i < keep_max and it["age_days"] <= days:
            continue
        media = []
        for p in review.glob(f"{it['id']}.*"):
            if p.is_file() and p.suffix.lower() in MEDIA_EXT:
                media.append(p)
        out.append({
            "id": it["id"],
            "age_days": it["age_days"],
            "status": it["status"],
            "sidecar": it["sidecar"],
            "media": media,
            "size": it["sidecar"].stat().st_size
            + sum(p.stat().st_size for p in media),
        })
    return out


def _delete(path: Path, apply: bool) -> bool:
    if not apply:
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def main():
    ap = argparse.ArgumentParser(description="outputs 生命周期清理")
    ap.add_argument("--apply", action="store_true",
                    help="真正删除；默认只打印")
    ap.add_argument("--tmp-days", type=float, default=7)
    ap.add_argument("--failed-days", type=float, default=30)
    ap.add_argument("--review-days", type=float, default=30)
    ap.add_argument("--review-max", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    tmp = _collect_by_age(OUTPUTS / "tmp", a.tmp_days)
    failed = _collect_by_age(OUTPUTS / "failed", a.failed_days)
    review = _collect_review(OUTPUTS / "review", a.review_days, a.review_max)

    report = {
        "apply": a.apply,
        "tmp": {"count": len(tmp),
                "mb": round(sum(x["size"] for x in tmp) / 1048576, 1),
                "threshold_days": a.tmp_days,
                "items": [str(x["path"].relative_to(ROOT)) for x in tmp[:20]]},
        "failed": {"count": len(failed),
                   "mb": round(sum(x["size"] for x in failed) / 1048576, 1),
                   "threshold_days": a.failed_days,
                   "items": [str(x["path"].relative_to(ROOT)) for x in failed[:20]]},
        "review": {"count": len(review),
                   "mb": round(sum(x["size"] for x in review) / 1048576, 1),
                   "threshold_days": a.review_days,
                   "keep_max": a.review_max,
                   "items": [x["id"] for x in review[:20]]},
    }

    if a.apply:
        for x in tmp + failed:
            _delete(x["path"], True)
        for x in review:
            _delete(x["sidecar"], True)
            for p in x["media"]:
                _delete(p, True)

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        mode = "APPLY" if a.apply else "DRY-RUN"
        print(f"[{mode}] tmp   {report['tmp']['count']} 个 / "
              f"{report['tmp']['mb']} MB（>{a.tmp_days:g} 天）")
        for x in report["tmp"]["items"]:
            print("  -", x)
        print(f"[{mode}] failed {report['failed']['count']} 个 / "
              f"{report['failed']['mb']} MB（>{a.failed_days:g} 天）")
        for x in report["failed"]["items"]:
            print("  -", x)
        print(f"[{mode}] review {report['review']['count']} 条 / "
              f"{report['review']['mb']} MB（>{a.review_days:g} 天，"
              f"且保留最新 {a.review_max} 条）")
        for x in report["review"]["items"]:
            print("  -", x)
        if not a.apply:
            print("\n未删除任何文件；确认后加 --apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
