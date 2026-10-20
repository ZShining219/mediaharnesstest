#!/usr/bin/env python3
"""提交一条 fission contract 到 H3，并把成片放进审核队列。

支持：
- target.references 多参考图（人物 + 商品），按 index 顺序提交；
- 如果 contract 目录有 voiceover.txt：自动 MiniMax TTS + 字幕烧录；
- 无 voiceover 时退回无声成片。

用法：
    # 产品说明片
    .venv/bin/python scripts/run_contract.py

    # 个体带货切片（人物 + 商品 + 口播 + 字幕）
    .venv/bin/python scripts/run_contract.py \
      --contract data/fission_slices/slice-1471-ugc-direction1/contract.json \
      --prompt data/fission_slices/slice-1471-ugc-direction1/prompt_h3.txt \
      --out data/fission_slices/slice-1471-ugc-direction1 \
      --name variant_ugc.mp4
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
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


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p


def _image_refs(contract: dict, fallback: Path | None) -> list[dict]:
    target = contract.get("target") or {}
    refs = target.get("references") or []
    out = []
    if refs:
        for r in sorted(refs, key=lambda x: int(x.get("index") or 0)):
            p = _resolve(str(r.get("path") or ""))
            if not p.exists():
                raise SystemExit(f"参考图不存在: {p}")
            out.append({"index": r.get("index"), "kind": r.get("kind"),
                        "label": r.get("label") or p.name, "path": p})
    elif fallback and fallback.exists():
        out.append({"index": 1, "kind": "product", "label": "商品图1",
                    "path": fallback})
    if not out:
        raise SystemExit("没有可提交的参考图")
    return out


def _fit_audio(tts: Path, duration: int, out: Path) -> Path:
    dur = media.ffprobe_duration(tts) or duration
    if dur > duration:
        tempo = min(1.4, dur / max(0.1, duration))
        af = f"atempo={tempo:.4f},apad"
    else:
        af = "apad"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(tts), "-af", af,
         "-t", str(duration), "-c:a", "aac", "-ar", "44100", str(out)],
        check=True)
    return out


def _add_voice_and_subs(video: Path, contract_dir: Path, duration: int,
                        out_dir: Path, voice: str, model: str,
                        font_size: int, margin_v: int,
                        backend: str = "auto", say_voice: str = "Tingting",
                        say_rate: int = 240) -> dict:
    voice_file = contract_dir / "voiceover.txt"
    if not voice_file.exists():
        return {"voiceover": False, "subtitles": False,
                "note": "无 voiceover.txt，保留无声成片"}
    text = voice_file.read_text(encoding="utf-8").strip()
    if not text:
        return {"voiceover": False, "subtitles": False,
                "note": "voiceover.txt 为空"}
    tts_path = C.TMP_DIR / f"{video.stem}_tts.mp3"
    audio_path = C.TMP_DIR / f"{video.stem}_voice.m4a"
    muxed = C.TMP_DIR / f"{video.stem}_voice.mp4"
    subbed = C.TMP_DIR / f"{video.stem}_sub.mp4"
    used_backend = backend
    tts_source = tts_path
    if backend == "minimax":
        mm = minimax.Minimax.official()
        mm.tts(text, voice, tts_path, model=model, emotion="happy", speed=1.08)
    elif backend == "say":
        aiff = C.TMP_DIR / f"{video.stem}_tts.aiff"
        subprocess.run(["say", "-v", say_voice, "-r", str(say_rate),
                        "-o", str(aiff), text], check=True)
        tts_source = aiff
    else:  # auto: 先 MiniMax，失败降级 macOS say
        try:
            mm = minimax.Minimax.official()
            mm.tts(text, voice, tts_path, model=model, emotion="happy",
                   speed=1.08)
        except Exception as e:
            print(f"MiniMax TTS 失败，降级 say: {e}", flush=True)
            used_backend = "say"
            aiff = C.TMP_DIR / f"{video.stem}_tts.aiff"
            subprocess.run(["say", "-v", say_voice, "-r", str(say_rate),
                            "-o", str(aiff), text], check=True)
            tts_source = aiff
    _fit_audio(tts_source, duration, audio_path)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(audio_path),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-shortest", "-t", str(duration), str(muxed)],
        check=True)
    srt = contract_dir / "subtitles.srt"
    if not srt.exists():
        media.text_to_srt(text, duration, srt)
    try:
        media.burn_subtitles_pil(muxed, srt, subbed, font_size=font_size,
                                 margin_v=margin_v, stroke=3)
    except Exception as e:
        print(f"PIL 硬字幕失败，退回软字幕: {e}", flush=True)
        media.burn_subtitles(muxed, srt, subbed, font_size=font_size,
                             margin_v=margin_v, outline=3)
    return {"voiceover": True, "subtitles": True,
            "voiceover_text": text, "tts": _rel(tts_source),
            "tts_backend": used_backend,
            "srt": _rel(srt), "output": subbed}


def _add_subs_only(video: Path, srt: Path, font_size: int,
                   margin_v: int) -> Path:
    out = C.TMP_DIR / f"{video.stem}_sub.mp4"
    media.burn_subtitles_pil(video, srt, out, font_size=font_size,
                             margin_v=margin_v, stroke=3)
    return out


def main():
    ap = argparse.ArgumentParser(description="H3 生成一条契约切片")
    ap.add_argument("--contract", default=str(SLICE_DIR / "contract.json"))
    ap.add_argument("--prompt", default=str(SLICE_DIR / "prompt_h3.txt"))
    ap.add_argument("--image", default=None,
                    help="无 target.references 时的商品图 fallback")
    ap.add_argument("--out", default=str(SLICE_DIR))
    ap.add_argument("--name", default="variant_contract.mp4")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--no-native-audio", action="store_true",
                    help="不保留 H3 原生音轨，改走 TTS")
    ap.add_argument("--tts-voice", default=None)
    ap.add_argument("--tts-model", default=None)
    ap.add_argument("--tts-backend", choices=["auto", "minimax", "say"],
                    default="auto")
    ap.add_argument("--say-voice", default="Tingting")
    ap.add_argument("--say-rate", type=int, default=240)
    ap.add_argument("--font-size", type=int, default=42)
    ap.add_argument("--margin-v", type=int, default=92)
    a = ap.parse_args()

    contract_path = Path(a.contract)
    prompt_path = Path(a.prompt)
    out = Path(a.out)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    prompt = prompt_path.read_text(encoding="utf-8")
    target = contract.get("target") or {}
    fmt = target.get("format") or {}
    duration = int(fmt.get("duration") or 12)
    resolution = fmt.get("resolution") or "768P"
    ratio = fmt.get("aspect_ratio") or "9:16"
    slice_id = contract.get("slice_id") or "contract-slice"
    archetype = fmt.get("archetype") or "product_demo"

    fallback = Path(a.image) if a.image else (
        ROOT / (target.get("product", {}).get("image") or ""))
    refs = _image_refs(contract, fallback if fallback.exists() else None)
    dst = out / a.name
    if dst.exists() and not a.force:
        print(f"已存在 {dst}；如需重跑加 --force")
        return

    dh = C.section("digital_human") or {}
    tts_voice = a.tts_voice or dh.get("default_voice_id") or "female-shaonv"
    tts_model = a.tts_model or dh.get("minimax_tts_model") or "speech-2.6-hd"
    voice_file = contract_path.parent / "voiceover.txt"
    native_flag = fmt.get("native_audio")
    native_audio = (
        bool(native_flag) if native_flag is not None
        else bool(fmt.get("voiceover"))) and not a.no_native_audio
    use_tts = (not native_audio and not a.no_tts and voice_file.exists()
               and bool(fmt.get("voiceover")))

    jid = store.job_create("fission_slice", {
        "slice_id": slice_id,
        "archetype": archetype,
        "contract": str(contract_path),
        "prompt_chars": len(prompt),
        "references": [{"label": r["label"], "kind": r["kind"],
                        "path": _rel(r["path"])} for r in refs],
        "duration": duration,
        "resolution": resolution,
        "ratio": ratio,
        "voiceover": bool(fmt.get("voiceover")) or use_tts,
        "native_audio": native_audio,
    })
    store.job_update(jid, {"phase": "submitting"})
    print(f"[{time.strftime('%H:%M:%S')}] job={jid} submit "
          f"{duration}s {resolution} {ratio} refs={len(refs)} "
          f"tts={use_tts}", flush=True)

    mm = minimax.Minimax()
    content = [minimax.Minimax.part_text(prompt)]
    for r in refs:
        content.append(minimax.Minimax.part_image(media.ref_image(r["path"])))
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
        silent = C.TMP_DIR / f"{jid}_final.mp4"
        mm.download(mm.video_url(task), raw)
        if native_audio:
            media.trim_keep_audio(raw, silent, duration)
        else:
            media.trim_silent(raw, silent, duration)

        voice_info = {"voiceover": False, "subtitles": False}
        final = silent
        if native_audio:
            voice_info = {"voiceover": bool(fmt.get("voiceover")),
                          "subtitles": False, "native_audio": True,
                          "tts_backend": "h3_native",
                          "note": "保留 H3 原生音频"}
            if voice_file.exists():
                voice_info["voiceover_text"] = voice_file.read_text(
                    encoding="utf-8").strip()
            norm = C.TMP_DIR / f"{jid}_native_norm.mp4"
            media.loudnorm(silent, norm)
            final = norm
            srt = contract_path.parent / "subtitles.srt"
            if fmt.get("subtitles") and srt.exists():
                store.job_update(jid, {"phase": "subtitles"})
                print(f"[{time.strftime('%H:%M:%S')}] hard subtitles",
                      flush=True)
                try:
                    final = _add_subs_only(
                        final, srt, a.font_size, a.margin_v)
                    voice_info["subtitles"] = True
                    voice_info["srt"] = _rel(srt)
                except Exception as e:
                    voice_info["subtitle_error"] = f"{type(e).__name__}: {e}"
                    print(f"硬字幕失败，保留原生音轨: {e}", flush=True)
        elif use_tts:
            store.job_update(jid, {"phase": "tts"})
            print(f"[{time.strftime('%H:%M:%S')}] TTS + subtitles", flush=True)
            try:
                voice_info = _add_voice_and_subs(
                    silent, contract_path.parent, duration, out,
                    tts_voice, tts_model, a.font_size, a.margin_v,
                    backend=a.tts_backend, say_voice=a.say_voice,
                    say_rate=a.say_rate)
                final = voice_info.get("output") or silent
            except Exception as e:
                voice_info = {"voiceover": False, "subtitles": False,
                              "tts_error": f"{type(e).__name__}: {e}"}
                print(f"TTS/字幕失败，保留无声成片: {e}", flush=True)

        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final, dst)

        beats = (contract.get("structure") or {}).get("beats") or []
        meta = {
            "title": (contract.get("structure") or {}).get("name")
            or "契约切片",
            "desc": (contract.get("structure") or {}).get("concept") or "",
            "slice_id": slice_id,
            "archetype": archetype,
            "lane": (fmt.get("presentation") or {}).get("name"),
            "generation_mode": "single",
            "prompt": prompt,
            "voiceover": voice_info.get("voiceover", False),
            "subtitles": voice_info.get("subtitles", False),
            "constraints": {
                "product": target.get("product") or {},
                "global": fmt,
            },
            "inputs": [
                *[{"label": r["label"], "kind": "image",
                   "path": _rel(r["path"])} for r in refs],
                {"label": "整条视频提示词", "kind": "text", "text": prompt},
                *([{"label": "口播文稿", "kind": "text",
                    "text": voice_info.get("voiceover_text", "")}]
                  if voice_info.get("voiceover") else []),
                {"label": "契约", "kind": "text", "text": json.dumps({
                    "slice_id": slice_id,
                    "archetype": archetype,
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
                "information": b.get("information") or {},
            } for b in beats],
        }
        review_path = store.add_review_item(dst, "fission_slice", meta)
        shutil.copy2(review_path, dst)
        run_info = {
            "schema_version": "slice-run/v1",
            "status": "generated",
            "job": jid,
            "provider_task": tid,
            "provider_via": mm.via,
            "contract": _rel(contract_path),
            "prompt": _rel(prompt_path),
            "references": [{"label": r["label"], "kind": r["kind"],
                            "path": _rel(r["path"])} for r in refs],
            "review_path": _rel(review_path),
            "video": _rel(dst),
            "archetype": archetype,
            "native_audio": native_audio,
            "voiceover": voice_info.get("voiceover", False),
            "subtitles": voice_info.get("subtitles", False),
            "tts_backend": voice_info.get("tts_backend"),
            "voiceover_text": voice_info.get("voiceover_text"),
            "tts_error": voice_info.get("tts_error"),
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
