"""B 线执行: DirectorPlan -> H3 生成 -> BGM -> 审核队列。

generation_mode=single: 整条视频一次 H3 请求，逻辑分镜只存在于 prompt 时间轴。
旧方案没有该字段时仍走逐镜生成/拼接，保持兼容。

硬约束: 纯带货链路不向视频模型提交 reference_video。
content 只包含文本 + 人物/商品/背景参考图。
"""
import json
import logging
import time
from pathlib import Path

from orchestrator.app import config as C, media, minimax, store
from . import plan as pvplan
from .compiler import compile_shot, compile_video

log = logging.getLogger("product_video")


def _path(p: str) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else C.ROOT / pp


def _generate_shot(prompt: str, refs: list[str], out: Path,
                   duration: int, resolution: str, ratio: str,
                   jid: str, client: minimax.Minimax | None = None,
                   idempotency_key: str | None = None) -> Path:
    mm = client or minimax.Minimax()
    content = [minimax.Minimax.part_text(prompt)]
    for p in refs:
        content.append(minimax.Minimax.part_image(media.ref_image(_path(p))))
    tid = mm.video_generate_safe(
        content, duration=max(4, min(15, int(duration))),
        resolution=resolution, ratio=ratio, idempotency_key=idempotency_key)
    store.job_update(jid, {"provider_task": tid, "provider_via": mm.via})
    task = mm.video_wait(tid)
    mm.download(mm.video_url(task), out)
    return out


def _concat(videos: list[Path], out: Path):
    try:
        media.concat(videos, out)
        if out.exists() and out.stat().st_size > 0:
            return out
    except Exception:
        pass
    media.concat_reencode(videos, out)
    return out


def _shot_status(shots: list[dict]) -> list[dict]:
    return [{"index": s["index"], "status": s.get("status", "pending")}
            for s in shots]


def _run_single(plan: dict, plan_id: str, jid: str,
                bgm: str | None = None):
    """整条视频一次 H3 生成；逻辑分镜只在 prompt 时间轴里。"""
    shots = plan.get("shots") or []
    if not shots:
        raise ValueError("方案没有分镜")
    try:
        prompt, refs = compile_video(plan)
        plan["prompt"] = prompt
        plan["refs"] = refs
        for shot in shots:
            shot["status"] = "running"
        store.job_update(jid, {
            "generation_mode": "single",
            "shots": _shot_status(shots),
            "current": 1,
            "total": 1,
            "phase": "generating",
        })
        total = sum(float(s.get("duration") or 0) for s in shots)
        duration = max(4, min(15, int(round(total))))
        resolution = plan["meta"].get("resolution", "768P")
        ratio = plan["meta"].get("aspect_ratio", "9:16")
        content = [minimax.Minimax.part_text(prompt)]
        for p in refs:
            content.append(minimax.Minimax.part_image(
                media.ref_image(_path(p))))
        mm = minimax.Minimax()
        tid = mm.video_generate_safe(
            content, duration=duration, resolution=resolution, ratio=ratio,
            idempotency_key=f"{jid}-video")
        store.job_update(jid, {"provider_task": tid, "provider_via": mm.via})
        task = mm.video_wait(tid)
        raw = C.TMP_DIR / f"{jid}_raw.mp4"
        final = C.TMP_DIR / f"{jid}_final.mp4"
        mm.download(mm.video_url(task), raw)
        media.trim_silent(raw, final, duration)

        bgm = bgm or plan.get("bgm")
        if bgm:
            bgm_path = C.ASSETS / "bgm" / Path(bgm).name
            if bgm_path.exists():
                try:
                    mixed = C.TMP_DIR / f"{jid}_bgm.mp4"
                    media.mix_bgm_fade(final, bgm_path, mixed, volume=0.35)
                    norm = C.TMP_DIR / f"{jid}_norm.mp4"
                    media.loudnorm(mixed, norm)
                    final = norm
                except Exception as e:
                    log.warning("BGM 混入失败，保留静音成片: %s", e)

        inputs = []
        for i, p in enumerate(plan["assets"].get("person_photos", [])):
            inputs.append({"label": f"固定人物照片{i + 1}", "kind": "image", "path": p})
        for i, p in enumerate(plan["assets"].get("product_images", [])):
            inputs.append({"label": f"商品图{i + 1}", "kind": "image", "path": p})
        for i, p in enumerate(plan["assets"].get("background_images", [])):
            inputs.append({"label": f"背景图{i + 1}", "kind": "image", "path": p})
        inputs.append({"label": "意图", "kind": "text",
                       "text": plan.get("intent", "")})
        inputs.append({"label": "整条视频提示词", "kind": "text", "text": prompt})
        inputs.append({"label": "硬约束", "kind": "text",
                       "text": json.dumps(plan.get("constraints") or {},
                                          ensure_ascii=False)})
        for s in shots:
            beat = (s.get("beats") or [{}])[0]
            inputs.append({"label": f"逻辑分镜{s['index']}", "kind": "text",
                           "text": beat.get("description") or s.get("prompt", "")})

        item = store.add_review_item(final, "product_video", {
            "title": plan.get("title") or "带货视频",
            "desc": plan.get("intent", ""),
            "plan_id": plan_id,
            "generation_mode": "single",
            "prompt": prompt,
            "constraints": plan.get("constraints") or {},
            "inputs": inputs,
            "shots": [{
                "index": s["index"],
                "duration": s["duration"],
                "shot_function": s.get("shot_function"),
                "face_arc": s.get("face_arc") or {},
                "product_evidence": s.get("product_evidence") or [],
                "cut_to_next": s.get("cut_to_next") or "",
                "prompt": s.get("prompt"),
            } for s in shots],
            "model": "MiniMax H3",
            "visual_concept": plan.get("meta", {}).get("visual_concept", ""),
            "pacing": plan.get("meta", {}).get("pacing", ""),
            "wardrobe_lock": plan.get("meta", {}).get("wardrobe_lock", True),
        })
        plan["meta"]["duration"] = duration
        plan["status"] = "done"
        pvplan.save(plan)
        store.job_finish(jid, "done", {
            "item_id": item.stem,
            "item": str(item),
            "generation_mode": "single",
            "shots": [{"index": s["index"], "status": "done"} for s in shots],
        })
    except Exception as e:
        plan["status"] = "error"
        pvplan.save(plan)
        store.job_finish(jid, "error", {
            "error": str(e),
            "generation_mode": "single",
            "shots": _shot_status(shots),
        })
        raise


def run(plan_id: str, jid: str, bgm: str | None = None):
    plan = pvplan.load(plan_id)
    mode = (plan.get("generation_mode")
            or (plan.get("meta") or {}).get("generation_mode") or "per_shot")
    if mode == "single":
        return _run_single(plan, plan_id, jid, bgm)
    shots = plan.get("shots") or []
    if not shots:
        raise ValueError("方案没有分镜")
    results: list[Path] = []
    # 整个方案共用一个客户端: 保留 WAF cookie 和连接, 避免每镜冷连接被断
    mm = minimax.Minimax()
    try:
        for i, shot in enumerate(shots):
            prompt, refs = compile_shot(plan, shot)
            shot["prompt"] = prompt
            shot["refs"] = refs
            shot["status"] = "running"
            store.job_update(jid, {
                "shots": _shot_status(shots),
                "current": i + 1,
                "total": len(shots),
            })
            planned = max(2, int(shot.get("duration", 3)))
            raw = C.TMP_DIR / f"{jid}_shot{shot['index']}_raw.mp4"
            out = C.TMP_DIR / f"{jid}_shot{shot['index']}.mp4"
            _generate_shot(prompt, refs, raw, max(4, planned),
                           plan["meta"].get("resolution", "768P"),
                           plan["meta"].get("aspect_ratio", "9:16"),
                           jid, client=mm,
                           idempotency_key=f"{jid}-shot{shot['index']}")
            # H3 最短 4 秒；按计划时长裁剪并丢掉模型随机音轨
            media.trim_silent(raw, out, planned)
            shot["duration"] = planned
            shot["status"] = "done"
            shot["file"] = str(out)
            results.append(out)

        final = C.TMP_DIR / f"{jid}_final.mp4"
        _concat(results, final)
        bgm = bgm or plan.get("bgm")
        if bgm:
            bgm_path = C.ASSETS / "bgm" / Path(bgm).name
            if bgm_path.exists():
                try:
                    mixed = C.TMP_DIR / f"{jid}_bgm.mp4"
                    media.mix_bgm_fade(final, bgm_path, mixed, volume=0.35)
                    norm = C.TMP_DIR / f"{jid}_norm.mp4"
                    media.loudnorm(mixed, norm)
                    final = norm
                except Exception as e:
                    # BGM 失败不阻塞成片：保留无音轨版本
                    log.warning("BGM 混入失败，保留静音成片: %s", e)

        inputs = []
        for i, p in enumerate(plan["assets"].get("person_photos", [])):
            inputs.append({"label": f"固定人物照片{i + 1}", "kind": "image", "path": p})
        for i, p in enumerate(plan["assets"].get("product_images", [])):
            inputs.append({"label": f"商品图{i + 1}", "kind": "image", "path": p})
        for i, p in enumerate(plan["assets"].get("background_images", [])):
            inputs.append({"label": f"背景图{i + 1}", "kind": "image", "path": p})
        inputs.append({"label": "意图", "kind": "text", "text": plan.get("intent", "")})
        for s in shots:
            inputs.append({"label": f"分镜{s['index']}提示词", "kind": "text",
                           "text": s.get("prompt", "")})

        item = store.add_review_item(final, "product_video", {
            "title": plan.get("title") or "带货视频",
            "desc": plan.get("intent", ""),
            "plan_id": plan_id,
            "inputs": inputs,
            "shots": [{
                "index": s["index"],
                "duration": s["duration"],
                "shot_function": s.get("shot_function"),
                "prompt": s.get("prompt"),
            } for s in shots],
            "model": "MiniMax H3",
            "visual_concept": plan.get("meta", {}).get("visual_concept", ""),
            "pacing": plan.get("meta", {}).get("pacing", ""),
            "wardrobe_lock": plan.get("meta", {}).get("wardrobe_lock", True),
        })
        plan["meta"]["duration"] = sum(s["duration"] for s in shots)
        plan["status"] = "done"
        pvplan.save(plan)
        store.job_finish(jid, "done", {
            "item_id": item.stem,
            "item": str(item),
            "shots": [{"index": s["index"], "status": "done"} for s in shots],
        })
    except Exception as e:
        plan["status"] = "error"
        pvplan.save(plan)
        store.job_finish(jid, "error", {
            "error": str(e),
            "shots": _shot_status(shots),
        })
        raise
