"""自动化创作管线: 主题 -> 成片 -> 审核队列

backend (config.yaml auto_content.backend):
  mpt          MoneyPrinterTurbo 本地服务(需先启动)
  minimax_llm  零部署链路: DeepSeek 写口播文案+画面提示词 -> MiniMax TTS 配音
               -> MiniMax-H3 文生视频 -> 合成音轨 -> 审核队列
"""
from pathlib import Path

from orchestrator.app import mpt, store
from orchestrator.app import config as C


class PipelineError(RuntimeError):
    pass


def run_mpt(subject: str, script: str, jid: str, cfg: dict,
            **overrides) -> Path:
    client = mpt.MPT()
    if not client.health():
        raise PipelineError(
            f"MoneyPrinterTurbo 不可达: {client.base}, "
            f"启动: cd services/MoneyPrinterTurbo && uv run python main.py")
    task_id = client.create_video(
        subject, script=script,
        aspect=cfg.get("video_aspect", "9:16"),
        source=cfg.get("video_source", "pexels"),
        voice_name=cfg.get("voice_name", ""),
        clip_duration=cfg.get("video_clip_duration", 5),
        count=cfg.get("video_count", 1),
        **overrides)
    t = client.wait(task_id)
    videos = t.get("videos") or []
    if not videos:
        raise PipelineError(f"MPT 任务完成但无产出: {t}")
    out = C.TMP_DIR / f"{jid}_mpt.mp4"
    client.download(videos[0], out)
    return out


def run_minimax_llm(subject: str, script: str, jid: str, cfg: dict) -> Path:
    """DeepSeek 文案 -> MiniMax TTS -> H3 画面 -> ffmpeg 合成 -> 成片。
    DeepSeek 偶发不可用/超时: 自动降级为模板文案, 保证链路仍能产出。"""
    from orchestrator.app import llm, media, minimax

    used_fallback = False
    try:
        ds = llm.LLM()
    except llm.LLMError as e:
        ds, used_fallback = None, True
        store.job_update(jid, {"llm_error": str(e)})

    if not script:
        if ds:
            try:
                script = ds.chat(
                    f"主题：{subject}\n写一段 60~90 字的短视频口播文案，口语化、"
                    "开头要有钩子，只输出文案本身。")
            except llm.LLMError as e:
                used_fallback = True
                store.job_update(jid, {"llm_error": str(e)})
        if not script:
            script = f"{subject}。这是一个值得关注的新趋势，" \
                     "掌握它的人已经在悄悄拉开差距，看完记得收藏转发。"
    store.job_update(jid, {"script": script, "llm_fallback": used_fallback})

    mm = minimax.Minimax()
    audio = C.TMP_DIR / f"{jid}_vo.mp3"
    voice = cfg.get("voice_name") or "female-shaonv"
    mm.tts(script, voice, audio)          # 官方站 TTS

    if ds:
        try:
            visual_prompt = ds.chat(
                f"这是短视频的口播文案：{script}\n为它写一条配合的画面生成提示词："
                "描述主体、场景、光线、镜头运动，竖屏短视频风格，中文，不超过100字。"
                "只输出提示词。")
        except llm.LLMError as e:
            used_fallback = True
            store.job_update(jid, {"llm_error": str(e), "llm_fallback": True})
            visual_prompt = ""
    else:
        visual_prompt = ""
    if not visual_prompt:
        visual_prompt = (f"{subject}相关主题的专业短视频画面：现代办公桌、"
                         "笔记本电脑屏幕展示数据、光线明亮、镜头缓慢推进、"
                         "竖屏构图、质感真实")
    store.job_update(jid, {"visual_prompt": visual_prompt})

    secs = min(15, max(4, round(media.ffprobe_duration(audio) or 6)))
    video = C.TMP_DIR / f"{jid}_h3.mp4"
    tid = mm.video_generate([mm.part_text(visual_prompt)],
                            duration=secs, resolution="768P",
                            ratio=cfg.get("video_aspect", "9:16"))
    mm.video_wait_download(tid, video)

    out = C.TMP_DIR / f"{jid}_final.mp4"
    media.mux_audio(video, audio, out)
    return out


def run(subject: str, script: str = "", title: str | None = None,
        desc: str = "", tags: list[str] | None = None,
        jid: str | None = None, **overrides) -> dict:
    cfg = C.section("auto_content")
    backend = cfg.get("backend", "minimax_llm")
    jid = jid or store.job_create("auto_content", {"subject": subject})
    try:
        if backend == "mpt":
            out = run_mpt(subject, script, jid, cfg, **overrides)
        else:
            out = run_minimax_llm(subject, script, jid, cfg)

        from orchestrator.app import equivgraph
        inputs = [{"label": "主题", "kind": "text", "text": subject}]
        if backend == "minimax_llm":
            if script:
                inputs.append({"label": "口播文案", "kind": "text",
                               "text": script})
            vp = C.TMP_DIR / f"{jid}_vo.mp3"
            if vp.exists():
                inputs.append({"label": "配音音频", "kind": "audio",
                               "path": equivgraph._rel(vp)})
        item = store.add_review_item(out, "auto_content", {
            "title": title or subject[:20], "desc": desc or subject,
            "tags": tags or [], "backend": backend,
            "job": jid, "inputs": inputs,
        })
        store.job_finish(jid, "done", {"item": str(item), "item_id": item.stem})
        return {"job": jid, "item": str(item)}
    except Exception as e:
        store.job_finish(jid, "error", {"error": str(e)})
        raise


def main():
    import argparse
    ap = argparse.ArgumentParser(description="自动化创作短视频")
    ap.add_argument("--subject", required=True, help="主题, 如 'Kimi 新功能教程'")
    ap.add_argument("--script", default="", help="自定义文案, 空则 AI 生成")
    ap.add_argument("--title", default=None)
    ap.add_argument("--tags", default="")
    a = ap.parse_args()
    print(run(a.subject, script=a.script, title=a.title,
              tags=[t for t in a.tags.split(",") if t]))


if __name__ == "__main__":
    main()
