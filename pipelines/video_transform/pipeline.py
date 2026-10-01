"""对标视频转换管线: 输入舞蹈/参考视频 + 人脸/服装/背景参考图
   -> ComfyUI (Wan2.2-VACE + Phantom) 换脸换衣换背景 -> 审核队列

工作流模板编排说明见 orchestrator/workflows/README.md。
补丁变量约定:
    $SOURCE  源视频(上传到 comfyui input 后的文件名)
    $FACE    人脸参考图
    $CLOTH   服装参考图
    $BG      背景参考图
    $PROMPT  文本提示词
    $MASK    遮罩视频/图片(可选)
"""
from pathlib import Path

from orchestrator.app import comfyui, media, store
from orchestrator.app import config as C


class PipelineError(RuntimeError):
    pass


def run_wavespeed(source: Path, character_img: Path, out: Path,
                  prompt: str = "", mode: str = "replace",
                  resolution: str = "720p") -> Path:
    """WaveSpeed 托管模型路径:
    - replace: Wan2.2-Animate 把视频中人整替换成参考形象(动作/场景保留)
    - animate2: Wan2.2-Animate-2 形象按视频动, prompt 控制新背景
    """
    from orchestrator.app import wavespeed
    ws = wavespeed.WaveSpeed()
    if mode == "animate2":
        return ws.wan_animate2(character_img, source, out,
                               prompt=prompt, resolution=resolution)
    return ws.wan_animate_replace(character_img, source, out,
                                  resolution=resolution)


def run_minimax(source: Path, character_img: Path, out: Path,
                prompt: str = "", duration: int | None = None,
                resolution: str = "768P") -> Path:
    """MiniMax-H3 路径: 对标视频(reference_video)+人物形象图(reference_image)
    -> 重新生成"人物被替换"的视频。秘塔代理计费 ~¥0.09/秒(输入+输出)。"""
    from orchestrator.app import minimax
    mm = minimax.Minimax()
    secs = duration or min(15, max(4, round(media.ffprobe_duration(source))))
    content = [mm.part_text(
        prompt or "把参考视频中的人物替换为参考图片中的人物，保持动作、表情、"
                   "口型、场景和运镜完全一致，人物五官、发型、着装与参考图一致"),
        mm.part_video(source), mm.part_image(character_img)]
    tid = mm.video_generate(content, duration=secs, resolution=resolution)
    mm.video_wait_download(tid, out)
    return out


def run(source: Path, prompt: str = "", face: Path | None = None,
        cloth: Path | None = None, background: Path | None = None,
        mask: Path | None = None, workflow: str | None = None,
        mode: str = "replace", pre_edit_prompt: str | None = None,
        keep_audio: bool = True, bgm: str | None = None,
        resolution: str | None = None,
        title: str | None = None, desc: str = "", tags: list[str] | None = None,
        jid: str | None = None) -> dict:
    cfg = C.section("video_transform")
    backend = cfg.get("backend", "wavespeed")
    workflow = workflow or cfg.get("workflow", "video_vace_transform")
    jid = jid or store.job_create("video_transform", {"source": str(source)})
    try:
        if backend == "minimax":
            if not face:
                raise PipelineError("minimax 模式需要 face 目标形象图")
            out = C.TMP_DIR / f"{jid}_swap.mp4"
            run_minimax(source, face, out, prompt=prompt,
                        resolution=resolution or cfg.get("resolution", "768P"))
        elif backend == "wavespeed":
            out = _run_wavespeed_path(
                jid, cfg, source, face, cloth, prompt, mode, pre_edit_prompt,
                resolution or cfg.get("resolution", "720p"))
        else:
            out = _run_comfyui_path(jid, cfg, workflow, source, prompt,
                                    face, cloth, background, mask)

        # 后处理: 生成模型输出通常无声 → 回填源视频音轨; 可选 BGM
        from orchestrator.app import media
        if keep_audio and not media.has_audio(out) and media.has_audio(source):
            muxed = C.TMP_DIR / f"{jid}_mux.mp4"
            media.mux_audio(out, source, muxed)
            out = muxed
        if bgm:
            bgm_path = C.ASSETS / "bgm" / bgm
            if bgm_path.exists():
                mixed = C.TMP_DIR / f"{jid}_bgm.mp4"
                media.mix_bgm(out, bgm_path, mixed)
                out = mixed

        # 可选第二阶段: 脸部精修工作流 (仅 comfyui 后端)
        face_wf = cfg.get("face_detail_workflow") if backend == "comfyui" else None
        if face_wf:
            client = comfyui.ComfyUI()
            variables = {"FACE": client.upload(face) if face else ""}
            v_name = client.upload(out)
            wf2 = comfyui.apply_patches(
                comfyui.load_workflow(face_wf),
                comfyui.load_patch_map(face_wf),
                variables={"SOURCE": v_name, "FACE": variables["FACE"],
                           "PROMPT": prompt})
            pid2 = client.submit(wf2)
            outs2 = client.wait_and_collect(pid2)
            vids2 = [f for f in outs2
                     if f["filename"].lower().endswith((".mp4", ".webm", ".mov"))]
            if vids2:
                out2 = C.TMP_DIR / f"{jid}_face.mp4"
                client.download(vids2[0], out2)
                out = out2

        item = store.add_review_item(out, "video_transform", {
            "title": title or source.stem, "desc": desc, "tags": tags or [],
            "source": source.name, "prompt": prompt, "mode": mode,
        })
        store.job_finish(jid, "done", {"item": str(item), "item_id": item.stem})
        return {"job": jid, "item": str(item)}
    except Exception as e:
        store.job_finish(jid, "error", {"error": str(e)})
        raise


def _run_wavespeed_path(jid, cfg, source, face, cloth, prompt, mode,
                        pre_edit_prompt, resolution="720p") -> Path:
    """零部署路径: (可选换装编辑) -> Wan-Animate 整人替换"""
    if not face:
        raise PipelineError("wavespeed 模式需要 --face 目标形象图(人物全身/半身照)")
    character = face
    if pre_edit_prompt or cloth:
        from orchestrator.app import wavespeed
        ws = wavespeed.WaveSpeed()
        edit_prompt = pre_edit_prompt or "让第一张图的人穿上第二张图的衣服，保持人脸和姿势不变"
        edited = C.TMP_DIR / f"{jid}_look.png"
        ws.image_edit(character, edit_prompt, edited)
        character = edited
    out = C.TMP_DIR / f"{jid}_vace.mp4"
    return run_wavespeed(source, character, out, prompt=prompt, mode=mode,
                         resolution=resolution)


def _run_comfyui_path(jid, cfg, workflow, source, prompt,
                      face, cloth, background, mask) -> Path:
    client = comfyui.ComfyUI()
    if not client.health():
        raise PipelineError(f"ComfyUI 不可达: {client.base}")

    def up(p: Path | None) -> str:
        return client.upload(p) if p else ""

    variables = {
        "SOURCE": up(source), "FACE": up(face), "CLOTH": up(cloth),
        "BG": up(background), "MASK": up(mask), "PROMPT": prompt,
    }
    wf = comfyui.load_workflow(workflow)
    wf = comfyui.apply_patches(wf, comfyui.load_patch_map(workflow), variables)
    pid = client.submit(wf)
    outputs = client.wait_and_collect(pid)
    videos = [f for f in outputs
              if f["filename"].lower().endswith((".mp4", ".webm", ".mov"))]
    if not videos:
        raise PipelineError(f"ComfyUI 未产出视频: {outputs}")

    out = C.TMP_DIR / f"{jid}_vace.mp4"
    client.download(videos[0], out)

    # 可选第二阶段: 脸部精修工作流 (如 ReActor/PuLID)
    face_wf = cfg.get("face_detail_workflow")
    if face_wf:
        v_name = client.upload(out)
        wf2 = comfyui.apply_patches(
            comfyui.load_workflow(face_wf),
            comfyui.load_patch_map(face_wf),
            variables={"SOURCE": v_name, "FACE": variables["FACE"],
                       "PROMPT": prompt})
        pid2 = client.submit(wf2)
        outs2 = client.wait_and_collect(pid2)
        vids2 = [f for f in outs2
                 if f["filename"].lower().endswith((".mp4", ".webm", ".mov"))]
        if vids2:
            out2 = C.TMP_DIR / f"{jid}_face.mp4"
            client.download(vids2[0], out2)
            out = out2
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="对标视频换脸/换衣/换背景")
    ap.add_argument("--source", type=Path, required=True, help="对标视频")
    ap.add_argument("--face", type=Path)
    ap.add_argument("--cloth", type=Path)
    ap.add_argument("--background", type=Path)
    ap.add_argument("--mask", type=Path, help="遮罩视频(可选)")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--mode", default="replace",
                    choices=["replace", "animate2"],
                    help="replace=整人替换保留原场景; animate2=动作迁移+提示词控背景")
    ap.add_argument("--pre-edit", dest="pre_edit_prompt", default=None,
                    help="先对形象图做编辑, 如 '换成红色连衣裙'")
    ap.add_argument("--workflow", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--tags", default="")
    a = ap.parse_args()
    print(run(a.source, prompt=a.prompt, face=a.face, cloth=a.cloth,
              background=a.background, mask=a.mask, workflow=a.workflow,
              mode=a.mode, pre_edit_prompt=a.pre_edit_prompt,
              title=a.title, tags=[t for t in a.tags.split(",") if t]))


if __name__ == "__main__":
    main()
