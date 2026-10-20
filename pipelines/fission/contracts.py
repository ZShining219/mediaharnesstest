"""Contract 构建与落盘：variant -> 可执行契约 + prompt + 口播 + 字幕。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.app import media, reference_contract as rc

from .adapters import choose_primary_ref, get_adapter
from .io import load_json, save_json


def build_contract_for_variant(variant: dict, brief: dict, profile: dict,
                               catalog: dict[str, dict], out_dir: Path,
                               idx: int) -> dict:
    payload = brief.get("payload") or brief
    archetype = ((payload.get("goal") or {}).get("archetype")
                 or profile.get("default_archetype")
                 or "ugc_individual_seller")
    adapter = get_adapter(archetype)
    rid = choose_primary_ref(variant, catalog,
                             fallback=profile.get("reference_id"))
    facet = rc.load_facet(rid)
    contract = adapter.build_contract(variant, brief, profile, facet, idx)
    val = rc.validate_contract(contract, facet)
    contract["_validation"] = val
    if not val["ok"]:
        raise ValueError(f"契约校验失败: {val['errors']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    save_json(out_dir / "contract.json", contract)
    (out_dir / "prompt_h3.txt").write_text(
        rc.render_h3_prompt(contract), encoding="utf-8")
    (out_dir / "prompt_audit.md").write_text(
        rc.render_audit(contract, facet), encoding="utf-8")
    fmt = (contract.get("target") or {}).get("format") or {}
    speech = bool(fmt.get("voiceover"))
    subtitles = bool(fmt.get("subtitles"))
    info = [b.get("information") or {}
            for b in contract["structure"]["beats"]]
    parts = [str(x.get("voiceover") or "").strip().rstrip("。")
             for x in info]
    voice = "。".join(p for p in parts if p) + "。" if speech else ""
    voice_path = out_dir / "voiceover.txt"
    if voice:
        voice_path.write_text(voice + "\n", encoding="utf-8")
    elif voice_path.exists():
        voice_path.unlink()
    srt_path = out_dir / "subtitles.srt"
    if subtitles:
        text = voice or "。".join(
            str(x.get("text_overlay") or "").strip().rstrip("。")
            for x in info if x.get("text_overlay"))
        if text:
            media.text_to_srt(
                text, float(fmt.get("duration") or 12), srt_path)
        elif srt_path.exists():
            srt_path.unlink()
    elif srt_path.exists():
        srt_path.unlink()
    return {
        "dir": str(out_dir), "primary_ref": rid, "adapter": adapter.name,
        "valid": val["ok"], "errors": val["errors"],
        "warnings": val["warnings"],
    }


def load_contract(path: Path | str) -> dict:
    return load_json(Path(path))
