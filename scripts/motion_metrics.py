#!/usr/bin/env python3
"""对比参考视频与裂变成片的“动感”指标。

指标：
- duration / shot_count / avg_shot / cuts_per_min（参考用描述镜头数，生成用场景检测）
- motion_mean / motion_p90 / active_ratio（帧间灰度差，0-255）
- text_shots / text_ratio / transcript_chars_per_sec（参考）
- camera_types / shot_sizes（参考）

用法：
    .venv/bin/python scripts/motion_metrics.py --refs bra
    .venv/bin/python scripts/motion_metrics.py --refs all --out data/motion.json
    .venv/bin/python scripts/motion_metrics.py --video path/to/a.mp4 --video path/to/b.mp4
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "data" / "reference_pool.json"
CASES = ROOT / "data" / "reference_cases"
SCENE_RE = re.compile(r"pts_time:([0-9.]+)")


def _probe(path: Path) -> dict:
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=duration:stream=width,height,codec_type",
           "-of", "json", str(path)]
    data = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {"duration": duration, "width": v.get("width"),
            "height": v.get("height"), "has_audio": has_audio}


def _motion(path: Path, fps: float = 12.0, width: int = 160) -> dict:
    p = _probe(path)
    w, h = p.get("width"), p.get("height")
    if not w or not h:
        return {"motion_mean": None, "motion_p90": None,
                "active_ratio": None}
    sh = max(2, round(width * h / w / 2) * 2)
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
           f"fps={fps},scale={width}:{sh},format=gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    frame_size = width * sh
    n = len(raw) // frame_size
    if n < 2:
        return {"motion_mean": None, "motion_p90": None,
                "active_ratio": None}
    arr = np.frombuffer(raw[:n * frame_size], dtype=np.uint8)
    frames = arr.reshape(n, sh, width).astype(np.int16)
    diffs = np.abs(frames[1:] - frames[:-1]).mean(axis=(1, 2))
    return {
        "motion_mean": round(float(diffs.mean()), 2),
        "motion_p90": round(float(np.percentile(diffs, 90)), 2),
        "active_ratio": round(float((diffs > 3.0).mean()), 3),
        "fps_sampled": fps,
    }


def _scene_cuts(path: Path, threshold: float = 0.18) -> list[float]:
    cmd = ["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
           f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True).stderr
    return [round(float(x), 3) for x in SCENE_RE.findall(out)]


def _desc_metrics(ref_id: str) -> dict:
    d = json.loads((CASES / ref_id / "descriptions.json").read_text(
        encoding="utf-8"))
    try:
        ev = json.loads((CASES / ref_id / "evidence.json").read_text(
            encoding="utf-8"))
    except Exception:
        ev = {}
    meta = d.get("meta") or {}
    shots = d.get("shots") or []
    transcript = d.get("transcript") or []
    text = "".join(str(x.get("text") or "") for x in transcript)
    duration = float(meta.get("duration") or 0)
    cameras = Counter(str(s.get("camera") or "") for s in shots)
    sizes = Counter(str(s.get("shot_size") or "") for s in shots)
    text_shots = sum(1 for s in shots if str(s.get("on_screen_text") or "").strip())
    return {
        "duration": round(duration, 2),
        "shots": len(shots),
        "avg_shot": round(duration / len(shots), 2) if shots else None,
        "text_shots": text_shots,
        "text_ratio": round(text_shots / len(shots), 2) if shots else None,
        "transcript_chars": len(text),
        "chars_per_sec": round(len(text) / duration, 2) if duration else None,
        "cameras": dict(cameras),
        "shot_sizes": dict(sizes),
        "has_audio": bool((ev.get("audio") or {}).get("has_audio")),
    }


def ref_metrics(item: dict) -> dict:
    rid = item["id"]
    path = ROOT / item["path"] if not Path(item["path"]).is_absolute() else Path(item["path"])
    dm = _desc_metrics(rid)
    mm = _motion(path)
    cuts = dm["shots"]
    return {
        "ref_id": rid,
        "title": (item.get("title") or "")[:40],
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        **dm, **mm,
        "cuts": cuts,
        "cuts_per_min": round(cuts / dm["duration"] * 60, 2) if dm["duration"] else None,
    }


def video_metrics(path: Path, label: str | None = None) -> dict:
    p = _probe(path)
    cuts = _scene_cuts(path)
    mm = _motion(path)
    return {
        "label": label or path.name,
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "duration": round(p["duration"], 2),
        "scene_cuts": cuts,
        "cuts": len(cuts),
        "cuts_per_min": round(len(cuts) / p["duration"] * 60, 2)
        if p["duration"] else None,
        "has_audio": p["has_audio"],
        **mm,
    }


def main():
    ap = argparse.ArgumentParser(description="动感指标对比")
    ap.add_argument("--refs", default="bra",
                    help="bra | all | comma-separated ref ids")
    ap.add_argument("--video", action="append", default=[],
                    help="额外视频，可重复")
    ap.add_argument("--out", default=None)
    ap.add_argument("--scene-threshold", type=float, default=0.18)
    a = ap.parse_args()

    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if a.refs == "all":
        items = pool
    elif a.refs == "bra":
        items = [x for x in pool if "文胸" in (x.get("tags") or [])]
    else:
        ids = {x.strip() for x in a.refs.split(",") if x.strip()}
        items = [x for x in pool if x["id"] in ids]

    rows = [ref_metrics(x) for x in items]
    videos = [video_metrics(ROOT / v if not Path(v).is_absolute() else Path(v))
              for v in a.video]

    if a.out:
        out = Path(a.out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"refs": rows, "videos": videos},
                                  ensure_ascii=False, indent=2),
                       encoding="utf-8")

    print(f"{'label':42} {'dur':>6} {'shots':>5} {'cut/m':>6} "
          f"{'motion':>7} {'p90':>6} {'active':>6} {'text%':>6} {'aud':>4}")
    for r in rows:
        print(f"{r['ref_id']:42} {r['duration']:6.1f} {r['shots']:5d} "
              f"{r['cuts_per_min'] or 0:6.1f} {r['motion_mean'] or 0:7.2f} "
              f"{r['motion_p90'] or 0:6.2f} {r['active_ratio'] or 0:6.3f} "
              f"{(r['text_ratio'] or 0)*100:5.0f}% "
              f"{'Y' if r.get('has_audio') else '-':>4}")
    for r in videos:
        print(f"{r['label'][:42]:42} {r['duration']:6.1f} {r['cuts']:5d} "
              f"{r['cuts_per_min'] or 0:6.1f} {r['motion_mean'] or 0:7.2f} "
              f"{r['motion_p90'] or 0:6.2f} {r['active_ratio'] or 0:6.3f} "
              f"{'-':>6} {'Y' if r['has_audio'] else '-':>4}")


if __name__ == "__main__":
    main()
