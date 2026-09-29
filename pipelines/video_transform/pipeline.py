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

from orchestrator.app import comfyui, store
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


def run(source: Path, prompt: str = "", face: Path | None = None,
        cloth: Path | None = None, background: Path | None = None,
        mask: Path | None = None, workflow: str | None = None,
        mode: str = "replace", pre_edit_prompt: str | None = None,
        title: str | None = None, desc: str = "", tags: list[str] | None = None,
        jid: str | None = None) -> dict:
    cfg = C.section("video_transform")
    backend = cfg.get("backend", "wavespeed")
    workflow = workflow or cfg.get("workflow", "video_vace_transform")
    jid = jid or store.job_create("video_transform", {"source": str(source)})
    try:
        if backend == "wavespeed":
            out = _run_wavespeed_path(
                jid, cfg, source, face, cloth, prompt, mode, pre_edit_prompt)
        else:
            out = _run_comfyui_path(jid, cfg, workflow, source, prompt,
                                    face, cloth, background, mask)

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

        item = store.add_review_item(out, "video_transform", {
            "title": title or source.stem, "desc": desc, "tags": tags or [],
            "source": source.name, "prompt": prompt, "mode": mode,
        })
        store.job_finish(jid, "done", {"item": str(item)})
        return {"job": jid, "item": str(item)}
    except Exception as e:
        store.job_finish(jid, "error", {"error": str(e)})
        raise


def _run_wavespeed_path(jid, cfg, source, face, cloth, prompt, mode,
                        pre_edit_prompt) -> Path:
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
                         resolution=cfg.get("resolution", "720p"))


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
