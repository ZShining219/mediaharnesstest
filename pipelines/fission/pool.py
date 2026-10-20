"""Pool Query：只读把视频池摊成多视角 digest + 动态锚点目录。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL = ROOT / "data" / "reference_pool.json"
CASES = ROOT / "data" / "reference_cases"
FACETS = ROOT / "data" / "reference_facets"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _anchor(ref_id: str) -> dict:
    f = _load(FACETS / f"{ref_id}.json") or {}
    beats = [int(b.get("index") or 0)
             for b in (f.get("structure") or {}).get("beats") or []]
    shots = [int(s.get("index") or 0) for s in (f.get("timeline") or [])]
    beats = [x for x in beats if x]
    shots = [x for x in shots if x]
    return {"beats": beats, "shots": shots,
            "beat_count": len(beats), "shot_count": len(shots)}


def compact_ref(ref: dict) -> dict:
    ref_id = ref["id"]
    d = _load(CASES / ref_id / "descriptions.json") or {}
    g = d.get("global") or {}
    bp = d.get("blueprint") or {}
    st = bp.get("structure") or {}
    roles = d.get("roles") or {}
    marketing = roles.get("marketing") or {}
    platform = roles.get("platform") or {}
    shots = [{
        "index": s.get("index"),
        "time": [s.get("start"), s.get("end")],
        "shot_size": s.get("shot_size"),
        "camera": s.get("camera"),
        "lighting": s.get("lighting"),
        "composition": s.get("composition"),
        "action": s.get("action"),
        "product": s.get("product"),
        "on_screen_text": s.get("on_screen_text"),
    } for s in (d.get("shots") or [])]
    transcript = "".join(str(x.get("text") or "")
                         for x in (d.get("transcript") or []))
    return {
        "ref_id": ref_id,
        "category": g.get("category"),
        "tags": ref.get("tags") or [],
        "duration": ref.get("duration"),
        "anchor": _anchor(ref_id),
        "global": {k: g.get(k) for k in (
            "scene", "visual_style", "lighting", "pacing",
            "camera_language", "on_screen_text_style", "product")},
        "structure": st,
        "marketing": {
            "observations": (marketing.get("observations") or [])[:6],
            "inferences": (marketing.get("inferences") or [])[:6],
        },
        "platform": {
            "observations": (platform.get("observations") or [])[:5],
            "inferences": (platform.get("inferences") or [])[:5],
        },
        "shots": shots,
        "transcript": transcript[:900],
    }


def build_digest() -> dict:
    pool = _load(POOL) or []
    refs = [compact_ref(x) for x in pool if isinstance(x, dict)]
    return {
        "type": "pool.digest",
        "version": "v0",
        "id": "pooldigest-local",
        "producer": "pool_query/v0",
        "payload": {"refs": refs},
        "refs": [x["ref_id"] for x in refs],
        "provenance": {"source": "data/reference_cases/*/descriptions.json"},
    }


def anchor_catalog(digest: dict) -> dict[str, dict]:
    return {r["ref_id"]: r.get("anchor") or {}
            for r in (digest.get("payload") or {}).get("refs") or []}


def anchor_lines(digest: dict) -> str:
    lines = []
    for r in (digest.get("payload") or {}).get("refs") or []:
        a = r.get("anchor") or {}
        lines.append(
            f"- {r['ref_id']}: beats {a.get('beats')}, shots {a.get('shots')}"
            f" | {r.get('category')} | {r.get('duration')}s")
    return "\n".join(lines)
