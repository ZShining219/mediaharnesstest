"""数字人口播管线: 文案 -> TTS -> 音频驱动人像 -> 字幕/BGM -> 审核队列

角色资产结构 (assets/characters/<name>/):
    config.json      {"voice_id": "xxx", "default_prompt": "...", "look": "looks/default.png"}
    refs/            原始参考照片(供换装/换发型出图用)
    looks/           各形象版本, 当前形象由 config.json 的 look 指定
"""
import json
import time
from pathlib import Path

from orchestrator.app import comfyui, media, minimax, store
from orchestrator.app import config as C


class PipelineError(RuntimeError):
    pass


def character_dir(name: str) -> Path:
    return C.ASSETS / "characters" / name


def load_character(name: str) -> dict:
    d = character_dir(name)
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8")) \
        if (d / "config.json").exists() else {}
    cfg.setdefault("look", "looks/default.png")
    return cfg


def portrait_of(name: str) -> Path:
    cfg = load_character(name)
    p = character_dir(name) / cfg["look"]
    if not p.exists():
        raise PipelineError(f"角色 {name} 的形象图不存在: {p}, "
                            f"请放入照片或在 config.json 中指定 look")
    return p


def synth_voice(text: str, voice_id: str, out: Path,
                emotion: str | None = None) -> Path:
    tts_cfg = C.section("digital_human")
    engine = tts_cfg.get("tts_engine", "minimax")
    if engine == "minimax":
        mm = minimax.Minimax()
        return mm.tts(text, voice_id=voice_id, out_path=out,
                      model=tts_cfg.get("minimax_tts_model", "speech-2.8-hd"),
                      emotion=emotion)
    raise PipelineError(f"未知 TTS 引擎: {engine}")


def animate_wavespeed(portrait: Path, audio: Path, prompt_text: str,
                      jid: str, resolution: str | None = None) -> Path:
    """WaveSpeed 托管 InfiniteTalk: 图+音频 -> 口型视频 (无需GPU)"""
    from orchestrator.app import wavespeed
    ws = wavespeed.WaveSpeed()
    resolution = resolution or C.section("digital_human").get("resolution", "720p")
    return ws.infinitetalk(portrait, audio, C.TMP_DIR / f"{jid}_raw.mp4",
                           prompt=prompt_text, resolution=resolution)


def animate_comfyui(portrait: Path, audio: Path, prompt_text: str,
                    workflow: str, jid: str) -> Path:
    """通过 ComfyUI 工作流(InfiniteTalk 等)生成口型视频"""
    client = comfyui.ComfyUI()
    if not client.health():
        raise PipelineError(f"ComfyUI 不可达: {client.base}, "
                            f"请检查 COMFYUI_BASE_URL 或先启动服务")
    p_name = client.upload(portrait)
    a_name = client.upload(audio)
    prompt = comfyui.load_workflow(workflow)
    patches = comfyui.load_patch_map(workflow)
    prompt = comfyui.apply_patches(
        prompt, patches,
        variables={"PORTRAIT": p_name, "AUDIO": a_name, "PROMPT": prompt_text})
    pid = client.submit(prompt)
    outputs = client.wait_and_collect(pid)
    videos = [f for f in outputs
              if f["filename"].lower().endswith((".mp4", ".webm", ".mov"))]
    if not videos:
        raise PipelineError(f"ComfyUI 未产出视频: {outputs}")
    dst = C.TMP_DIR / f"{jid}_raw.mp4"
    return client.download(videos[0], dst)


def animate_minimax(portrait: Path, audio: Path | None, prompt_text: str,
                    jid: str, duration: int | None = None) -> Path:
    """MiniMax-H3 形象口播: 参考图 + (可选)参考音频 -> 视频。
    秘塔代理接口; 音频参与生成时口型更好。"""
    mm = minimax.Minimax()
    content = [mm.part_text(prompt_text), mm.part_image(portrait)]
    if audio:
        content.append(mm.part_audio(audio))
    if duration:
        secs = duration
    elif audio:
        secs = min(15, max(4, round(media.ffprobe_duration(audio) or 6)))
    else:
        secs = 6
    tid = mm.video_generate(content, duration=secs, resolution="768P")
    # 立即落库: 后续轮询/下载断连时 job 里仍有服务商 task_id, 可取回
    store.job_update(jid, {"provider_task": tid, "provider_via": mm.via})
    mm.video_wait_download(tid, C.TMP_DIR / f"{jid}_raw.mp4")
    return C.TMP_DIR / f"{jid}_raw.mp4"


def run(text: str, character: str = "default", emotion: str | None = None,
        prompt: str | None = None, look: str | None = None,
        resolution: str | None = None, subtitles: bool | None = None,
        title: str | None = None, desc: str = "", tags: list[str] | None = None,
        jid: str | None = None) -> dict:
    cfg = C.section("digital_human")
    post = cfg.get("post", {})
    jid = jid or store.job_create("digital_human", {"character": character, "len": len(text)})
    try:
        char_cfg = load_character(character)
        if look:
            char_cfg["look"] = f"looks/{look}.png" if not look.startswith("looks/") else look
        portrait = character_dir(character) / char_cfg["look"]
        voice_id = char_cfg.get("voice_id") or cfg.get("default_voice_id")
        if not voice_id:
            raise PipelineError(
                f"角色 {character} 未配置 voice_id; 先用 MiniMax voice_clone 克隆声音"
                f"或使用系统音色, 写入 {character_dir(character)}/config.json")

        audio = synth_voice(text, voice_id, C.TMP_DIR / f"{jid}.mp3",
                            emotion or cfg.get("default_emotion"))
        speak_prompt = prompt or char_cfg.get("default_prompt") or \
            "一位主播自然地对着镜头说话，表情生动，画质清晰"

        backend = cfg.get("backend", "minimax")
        if backend == "comfyui":
            raw = animate_comfyui(portrait, audio, speak_prompt,
                                  cfg.get("workflow", "digital_human_infinitetalk"), jid)
        elif backend == "wavespeed":
            raw = animate_wavespeed(portrait, audio, speak_prompt, jid, resolution)
        else:  # minimax (默认, 秘塔代理零部署)
            raw = animate_minimax(portrait, audio, speak_prompt, jid)

        final = raw
        # 若生成视频不含音轨, 合成 TTS 音频
        if not media.has_audio(final):
            muxed = C.TMP_DIR / f"{jid}_mux.mp4"
            media.mux_audio(final, audio, muxed)
            final = muxed
        if post.get("loudnorm"):
            out = C.TMP_DIR / f"{jid}_ln.mp4"
            media.loudnorm(final, out)
            final = out
        if post.get("bgm"):
            bgm = C.ASSETS / "bgm" / post["bgm"]
            if bgm.exists():
                out = C.TMP_DIR / f"{jid}_bgm.mp4"
                media.mix_bgm(final, bgm, out, post.get("bgm_volume", 0.15))
                final = out
        if subtitles if subtitles is not None else post.get("burn_subtitles"):
            srt = media.text_to_srt(text, media.ffprobe_duration(final),
                                  C.TMP_DIR / f"{jid}.srt")
            out = C.TMP_DIR / f"{jid}_sub.mp4"
            media.burn_subtitles(final, srt, out)
            final = out

        from orchestrator.app import equivgraph
        inputs = [
            {"label": "口播文案", "kind": "text", "text": text},
            {"label": "角色形象", "kind": "image",
             "path": equivgraph._rel(portrait)},
            {"label": "TTS 配音", "kind": "audio",
             "path": equivgraph._rel(audio)},
            {"label": "角色/音色", "kind": "text",
             "text": f"{character} · {voice_id}"},
        ]
        item = store.add_review_item(final, "digital_human", {
            "title": title or text[:20],
            "desc": desc, "tags": tags or [],
            "character": character, "backend": backend,
            "job": jid, "inputs": inputs,
        })
        store.job_finish(jid, "done", {"item": str(item), "item_id": item.stem})
        return {"job": jid, "item": str(item)}
    except Exception as e:
        res = {"error": str(e)}
        prev = store.job_result(jid)          # 保留已落库的 provider_task
        if prev.get("provider_task"):
            res["provider_task"] = prev["provider_task"]
            res["provider_via"] = prev.get("provider_via")
        store.job_finish(
            jid, "unknown" if minimax.is_ambiguous_error(e) else "error", res)
        raise


def main():
    import argparse
    ap = argparse.ArgumentParser(description="数字人口播生成")
    ap.add_argument("--text", help="口播文案 (与 --text-file 二选一)")
    ap.add_argument("--text-file", type=Path)
    ap.add_argument("--character", default="default")
    ap.add_argument("--emotion", default=None)
    ap.add_argument("--look", default=None, help="形象版本名 looks/<name>.png")
    ap.add_argument("--title", default=None)
    ap.add_argument("--tags", default="")
    a = ap.parse_args()
    text = a.text or a.text_file.read_text(encoding="utf-8").strip()
    print(run(text, character=a.character, emotion=a.emotion, look=a.look,
              title=a.title, tags=[t for t in a.tags.split(",") if t]))


if __name__ == "__main__":
    main()
