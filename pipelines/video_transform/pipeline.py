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


def run(source: Path, prompt: str = "", face: Path | None = None,
        cloth: Path | None = None, background: Path | None = None,
        mask: Path | None = None, workflow: str | None = None,
        title: str | None = None, desc: str = "", tags: list[str] | None = None,
        jid: str | None = None) -> dict:
    cfg = C.section("video_transform")
    workflow = workflow or cfg.get("workflow", "video_vace_transform")
    jid = jid or store.job_create("video_transform", {"source": str(source)})
    try:
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

        item = store.add_review_item(out, "video_transform", {
            "title": title or source.stem, "desc": desc, "tags": tags or [],
            "source": source.name, "prompt": prompt,
        })
        store.job_finish(jid, "done", {"item": str(item)})
        return {"job": jid, "item": str(item)}
    except Exception as e:
        store.job_finish(jid, "error", {"error": str(e)})
        raise


def main():
    import argparse
    ap = argparse.ArgumentParser(description="对标视频换脸/换衣/换背景")
    ap.add_argument("--source", type=Path, required=True, help="对标视频")
    ap.add_argument("--face", type=Path)
    ap.add_argument("--cloth", type=Path)
    ap.add_argument("--background", type=Path)
    ap.add_argument("--mask", type=Path, help="遮罩视频(可选)")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--workflow", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--tags", default="")
    a = ap.parse_args()
    print(run(a.source, prompt=a.prompt, face=a.face, cloth=a.cloth,
              background=a.background, mask=a.mask, workflow=a.workflow,
              title=a.title, tags=[t for t in a.tags.split(",") if t]))


if __name__ == "__main__":
    main()
