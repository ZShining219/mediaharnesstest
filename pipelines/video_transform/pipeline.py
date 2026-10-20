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

import httpx

from orchestrator.app import comfyui, media, minimax, store
from orchestrator.app import config as C


class PipelineError(RuntimeError):
    pass


def _auto_title() -> str:
    """默认标题: 日期+当日序号, 如 1013-03"""
    import time as _t
    day0 = _t.mktime(_t.strptime(_t.strftime("%Y-%m-%d"), "%Y-%m-%d"))
    n = sum(1 for j in store.job_list(500)
            if j["type"].removeprefix("cron:") == "video_transform"
            and (j.get("created_at") or 0) >= day0)
    return f"{_t.strftime('%m%d')}-{n:02d}"


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
                resolution: str = "768P", ratio: str | None = None,
                extra: list[tuple[str, Path]] = (),
                task_cb=None) -> Path:
    """MiniMax-H3 路径: 对标视频(reference_video)+人物形象图(reference_image)
    -> 重新生成"人物被替换"的视频。秘塔代理计费 ~¥0.09/秒(输入+输出)。
    extra: 追加参考图 [(角色说明, 路径)], 按序作为 reference_image 提交
    task_cb: 拿到 provider task_id 即回调(用于记进 job, 断连可找回)"""
    # 时长: 指定值或对标视频长度, 统一钳到 H3 支持的 4-15 秒
    secs = min(15, max(4, round(duration or media.ffprobe_duration(source))))
    # 参考视频必须 <=15.5 秒；旧写法 secs+1 在 secs=15 时会到 16 秒被 H3 400
    src_ref = media.h3_ref_video(source, max_secs=min(15.0, secs))
    refs = [("目标人脸/形象", media.ref_image(character_img))]
    refs += [(label, media.ref_image(p)) for label, p in (extra or [])]
    legend = "，".join(f"参考图{i + 1}={label}" for i, (label, _) in enumerate(refs))
    # 自定义提示词也追加槽位标注, 保证"参考图N"与提交顺序恒对应
    text = (f"{prompt}（{legend}）" if prompt else
            f"把参考视频中的人物替换为参考图中的人物（{legend}），"
            "保持动作、表情、口型、场景和运镜完全一致，"
            "人物五官、发型、体型、着装与各参考图一致")
    MM = minimax.Minimax
    content = [MM.part_text(text), MM.part_video(src_ref)]
    content += [MM.part_image(p) for _, p in refs]
    # 双通道 failover: 官方直连(api.minimax.cn)优先, 失败自动回秘塔代理。
    # 同一任务可能在某通道实际已建成功——跨通道重试仍可能重复计费, 概率极小
    mm, used_via, errs = None, None, []
    for via in minimax.video_via_order():
        try:
            m = MM.video_client(via)
            tid = m.video_generate(content, duration=secs,
                                   resolution=resolution, ratio=ratio)
            mm, used_via = m, via
            break
        except minimax.SubmitAmbiguous:
            # 传输中断: 该通道可能已建任务, 不换通道不重试(EOS 纪律)
            raise
        except minimax.MinimaxError as e:
            errs.append(f"{via}: {e}")
    if mm is None:
        raise PipelineError("提交失败(已尝试所有通道): " + " | ".join(errs)[:300])
    if task_cb:
        task_cb(tid, used_via)
    mm.video_wait_download(tid, out)
    return out


def run(source: Path, prompt: str = "", face: Path | None = None,
        body: Path | None = None, body_back: Path | None = None,
        body_side: Path | None = None, cloth: Path | None = None,
        refs: list[Path] | None = None, background: Path | None = None,
        mask: Path | None = None, workflow: str | None = None,
        mode: str = "replace", pre_edit_prompt: str | None = None,
        keep_audio: bool = True, bgm: str | None = None,
        resolution: str | None = None, ratio: str | None = None,
        duration: int | None = None,
        title: str | None = None, desc: str = "", tags: list[str] | None = None,
        jid: str | None = None) -> dict:
    cfg = C.section("video_transform")
    backend = cfg.get("backend", "wavespeed")
    workflow = workflow or cfg.get("workflow", "video_vace_transform")
    jid = jid or store.job_create("video_transform", {"source": str(source)})
    character = face or body            # 无单独人脸图时身体参考兼任形象
    provider_task = {}                  # 秘塔 task_id, 断连时供找回
    try:
        if backend == "minimax":
            if not character:
                raise PipelineError("minimax 模式需要 face/body 目标形象图")
            extra = ([("身体正面参考", body)] if face and body else [])
            if body_back:
                extra.append(("身体背面参考", body_back))
            if body_side:
                extra.append(("身体侧面参考", body_side))
            if cloth:
                extra.append(("服饰参考", cloth))
            extra += [(f"追加参考{i + 1}", p) for i, p in enumerate(refs or [])]
            out = C.TMP_DIR / f"{jid}_swap.mp4"
            run_minimax(source, character, out, prompt=prompt,
                        resolution=resolution or cfg.get("resolution", "768P"),
                        ratio=ratio, duration=duration, extra=extra,
                        task_cb=lambda t, via: (
                            provider_task.update(id=t, via=via),
                            store.job_update(jid, {"provider_task": t,
                                                   "provider_via": via})))
        elif backend == "wavespeed":
            out = _run_wavespeed_path(
                jid, cfg, source, character, cloth, prompt, mode,
                pre_edit_prompt, resolution or cfg.get("resolution", "720p"))
        else:
            out = _run_comfyui_path(jid, cfg, workflow, source, prompt,
                                    character, cloth, background, mask)

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

        from orchestrator.app import equivgraph
        inputs = [
            {"label": "对标视频", "kind": "video", "path": equivgraph._rel(source)},
        ]
        if character:
            inputs.append({"label": "目标人脸", "kind": "image",
                           "path": equivgraph._rel(character)})
        if face and body:
            inputs.append({"label": "身体参考(正面)", "kind": "image",
                           "path": equivgraph._rel(body)})
        if body_back:
            inputs.append({"label": "身体参考(背面)", "kind": "image",
                           "path": equivgraph._rel(body_back)})
        if body_side:
            inputs.append({"label": "身体参考(侧面)", "kind": "image",
                           "path": equivgraph._rel(body_side)})
        if cloth:
            inputs.append({"label": "服饰参考", "kind": "image",
                           "path": equivgraph._rel(cloth)})
        for i, r in enumerate(refs or []):
            inputs.append({"label": f"追加参考{i + 1}", "kind": "image",
                           "path": equivgraph._rel(r)})
        if prompt:
            inputs.append({"label": "提示词", "kind": "text", "text": prompt})
        item = store.add_review_item(out, "video_transform", {
            "title": title or _auto_title(), "desc": desc, "tags": tags or [],
            "source": source.name, "prompt": prompt, "mode": mode,
            "job": jid, "inputs": inputs,
        })
        res = {"item": str(item), "item_id": item.stem}
        if provider_task.get("id"):
            res["provider_task"] = provider_task["id"]
            res["provider_via"] = provider_task.get("via")
        store.job_finish(jid, "done", res)
        return {"job": jid, "item": str(item)}
    except Exception as e:
        res = {"error": str(e)}
        if provider_task.get("id"):
            res["provider_task"] = provider_task["id"]
            res["provider_via"] = provider_task.get("via")
        # EOS 纪律: 提交中断/轮询暂停/下载失败 = 远端任务可能已存在或已完成,
        # 标 unknown 而非 error, 引导用 task_id 找回而不是直接重发
        ambiguous = minimax.is_ambiguous_error(e) \
            or (provider_task.get("id") and isinstance(e, httpx.HTTPError))
        store.job_finish(jid, "unknown" if ambiguous else "error", res)
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
    ap.add_argument("--body", type=Path, help="身体参考图·正面(体型/姿态)")
    ap.add_argument("--body-back", dest="body_back", type=Path, help="身体参考图·背面")
    ap.add_argument("--body-side", dest="body_side", type=Path, help="身体参考图·侧面")
    ap.add_argument("--cloth", type=Path)
    ap.add_argument("--background", type=Path)
    ap.add_argument("--mask", type=Path, help="遮罩视频(可选)")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--mode", default="replace",
                    choices=["replace", "animate2"],
                    help="replace=整人替换保留原场景; animate2=动作迁移+提示词控背景")
    ap.add_argument("--ratio", default=None,
                    choices=["adaptive", "9:16", "16:9", "1:1"],
                    help="画面比例(仅 minimax 后端)")
    ap.add_argument("--duration", type=int, default=None,
                    help="生成时长 4-15 秒(仅 minimax), 缺省=跟随对标视频")
    ap.add_argument("--pre-edit", dest="pre_edit_prompt", default=None,
                    help="先对形象图做编辑, 如 '换成红色连衣裙'")
    ap.add_argument("--workflow", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--tags", default="")
    a = ap.parse_args()
    print(run(a.source, prompt=a.prompt, face=a.face, body=a.body,
              body_back=a.body_back, body_side=a.body_side, cloth=a.cloth,
              background=a.background, mask=a.mask, workflow=a.workflow,
              mode=a.mode, pre_edit_prompt=a.pre_edit_prompt, ratio=a.ratio,
              duration=a.duration,
              title=a.title, tags=[t for t in a.tags.split(",") if t]))


if __name__ == "__main__":
    main()
