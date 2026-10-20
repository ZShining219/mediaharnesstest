"""节点定义注册表 —— 单一事实来源。

前端 /api/nodes 拉取本注册表的 schema 动态生成画布节点;
后端 GraphRunner 按 connections 拓扑执行各节点的 fn。

节点签名: fn(ctx, inputs, params) -> {输出槽名: 值}
  ctx: NodeCtx (tmpdir/客户端/日志/收集审核项)
  inputs: {输入槽名: 上游产出 (Path|str)}
  params: {参数名: 用户填的值}
数据类型: video | image | audio | text | any   (槽类型用于前端连线校验)
"""
from __future__ import annotations

import base64
import mimetypes
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config as C


def file_data_uri(p: Path) -> str:
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


class NodeError(RuntimeError):
    pass


@dataclass
class NodeCtx:
    jid: str
    tmpdir: Path
    log: Callable[[str], None] = print
    items: list = field(default_factory=list)   # 收集到的审核条目
    inputs: list = field(default_factory=list)  # 图的输入素材清单(素材节点)

    def tmp(self, name: str, suffix: str) -> Path:
        return self.tmpdir / f"{name}{suffix}"


@dataclass
class NodeDef:
    type: str            # "material/video" 唯一标识
    title: str
    category: str        # material / model / proc / output
    inputs: list         # [(name, dtype)]; name 前缀 '?' 表示可选
    outputs: list        # [(name, dtype)]
    params: list         # [{name, kind, default, options?, multiline?, hint?}]
    fn: Callable         # (ctx, inputs, params) -> dict


def P(name, kind, default=None, options=None, multiline=False, hint=""):
    """参数声明。kind: text/textarea/combo/toggle/number/asset:<组>"""
    return {"name": name, "kind": kind, "default": default,
            "options": options, "multiline": multiline, "hint": hint}


REGISTRY: dict[str, NodeDef] = {}


def node(type_, title, category, inputs, outputs, params):
    def deco(fn):
        REGISTRY[type_] = NodeDef(type_, title, category, inputs, outputs, params, fn)
        return fn
    return deco


def _p(ctx: NodeCtx, v) -> Path:
    """把资产值转成绝对路径"""
    if v is None:
        raise NodeError("缺少素材文件")
    p = C.ROOT / v if not str(v).startswith("/") else Path(v)
    if not p.exists():
        raise NodeError(f"文件不存在: {p}")
    return p


# ==================== 素材节点 ====================

@node("material/video", "素材·视频", "material", [], [("video", "video")],
      [P("文件", "asset:video"), P("标题", "text", "")])
def n_material_video(ctx, ins, ps):
    return {"video": _p(ctx, ps.get("文件"))}


@node("material/image", "素材·图片", "material", [], [("image", "image")],
      [P("文件", "asset:image")])
def n_material_image(ctx, ins, ps):
    return {"image": _p(ctx, ps.get("文件"))}


@node("material/audio", "素材·音频", "material", [], [("audio", "audio")],
      [P("文件", "asset:audio")])
def n_material_audio(ctx, ins, ps):
    return {"audio": _p(ctx, ps.get("文件"))}


@node("material/text", "素材·文本", "material", [], [("text", "text")],
      [P("内容", "textarea", "")])
def n_material_text(ctx, ins, ps):
    return {"text": ps.get("内容") or ""}


@node("material/character", "素材·角色形象", "material", [], [("image", "image")],
      [P("角色", "@characters"), P("形象版本", "@looks")])
def n_material_character(ctx, ins, ps):
    p = _p(ctx, ps.get("形象版本"))
    return {"image": p}


# ==================== 模型节点 ====================

@node("model/tts_minimax", "模型·MiniMax 情感TTS", "model",
      [("text", "text")], [("audio", "audio")],
      [P("音色ID", "text", "female-shaonv", hint="官方站系统音色/克隆音色ID"),
       P("情绪", "combo", "neutral",
        options=["neutral", "happy", "sad", "angry", "surprise", "fear", "disgust"]),
       P("语速", "number", 1.0)])
def n_tts(ctx, ins, ps):
    from . import minimax
    text = ins.get("text")
    if not text:
        raise NodeError("TTS 需要文本输入")
    vid = ps.get("音色ID") or C.env("MINIMAX_VOICE_ID", "female-shaonv")
    out = ctx.tmp("tts", ".mp3")
    minimax.Minimax().tts(text, vid, out, emotion=ps.get("情绪"),
                          speed=float(ps.get("语速") or 1.0))
    return {"audio": out}


@node("model/llm_deepseek", "模型·DeepSeek 文案", "model",
      [("?text", "text")], [("text", "text")],
      [P("任务", "combo", "prompt",
         options=["prompt", "script", "custom"],
         hint="prompt=视频提示词 / script=口播文案 / custom=自由指令"),
       P("自由指令", "textarea", "", hint="custom 模式用; {input} 为上游文本占位"),
       P("字数上限", "number", 120)])
def n_llm(ctx, ins, ps):
    from . import llm
    task = ps.get("任务") or "prompt"
    src = (ins.get("text") or "").strip()
    limit = int(ps.get("字数上限") or 120)
    if task == "prompt":
        system = ("你是短视频导演。根据用户主题写一条视频生成提示词：描述画面主体、"
                  "动作、场景、光线、镜头运动、风格。只输出提示词本身，中文，"
                  f"不超过{limit}字。")
        user = src or ps.get("自由指令") or ""
    elif task == "script":
        system = ("你是短视频编剧。根据主题写一段口播文案：口语化、有钩子、"
                  f"不超过{limit}字。只输出文案本身。")
        user = src or ps.get("自由指令") or ""
    else:
        tpl = ps.get("自由指令") or "{input}"
        user = tpl.replace("{input}", src)
        system = None
    if not user:
        raise NodeError("DeepSeek 节点需要上游文本或自由指令")
    ctx.log("DeepSeek 生成中…")
    text = llm.LLM().chat(user, system=system, max_tokens=max(256, limit * 4))
    ctx.log(f"DeepSeek 产出 {len(text)} 字")
    return {"text": text}


@node("model/infinitetalk", "模型·InfiniteTalk 口播", "model",
      [("image", "image"), ("audio", "audio"), ("?prompt", "text")],
      [("video", "video")],
      [P("分辨率", "combo", "720p", options=["480p", "720p"]),
       P("快速模式", "toggle", True)])
def n_infinitetalk(ctx, ins, ps):
    from . import wavespeed
    out = ctx.tmp("italk", ".mp4")
    wavespeed.WaveSpeed().infinitetalk(
        _p(ctx, ins["image"]), _p(ctx, ins["audio"]), out,
        prompt=ins.get("prompt") or "", resolution=ps.get("分辨率") or "720p",
        fast=bool(ps.get("快速模式")))
    return {"video": out}


@node("model/wan_animate", "模型·Wan2.2-Animate 换人", "model",
      [("video", "video"), ("image", "image"), ("?prompt", "text")],
      [("video", "video")],
      [P("模式", "combo", "replace",
         options=["replace", "animate2"]),
       P("分辨率", "combo", "720p", options=["480p", "720p"])])
def n_wan_animate(ctx, ins, ps):
    from . import wavespeed
    ws = wavespeed.WaveSpeed()
    out = ctx.tmp("animate", ".mp4")
    prompt = ins.get("prompt") or ""
    if ps.get("模式") == "animate2":
        ws.wan_animate2(_p(ctx, ins["image"]), _p(ctx, ins["video"]), out,
                        prompt=prompt, resolution=ps.get("分辨率") or "720p")
    else:
        ws.wan_animate_replace(_p(ctx, ins["image"]), _p(ctx, ins["video"]), out,
                               resolution=ps.get("分辨率") or "720p")
    return {"video": out}


@node("model/image_edit", "模型·图像编辑(换装)", "model",
      [("image", "image"), ("text", "text")], [("image", "image")],
      [P("输出尺寸", "text", "", hint="如 1024*1024, 可空")])
def n_image_edit(ctx, ins, ps):
    from . import wavespeed
    if not ins.get("text"):
        raise NodeError("图像编辑需要文本指令(接 素材·文本)")
    out = ctx.tmp("edit", ".png")
    wavespeed.WaveSpeed().image_edit(
        _p(ctx, ins["image"]), ins["text"], out, size=ps.get("输出尺寸") or None)
    return {"image": out}


def _h3_run(ctx, content: list[dict], out: Path, ps: dict,
            default_prompt: str, ins: dict) -> dict:
    """H3 通用提交: content 多模态数组 -> 等结果 -> 下载"""
    from . import minimax, store
    prompt = (ins.get("text") or ins.get("prompt") or "").strip() or default_prompt
    content.insert(0, minimax.Minimax.part_text(prompt))
    mm = minimax.Minimax()
    duration = max(4, min(15, int(ps.get("时长(秒)") or 6)))
    resolution = ps.get("分辨率") or "768P"
    ratio = ps.get("画幅") or None
    tid = mm.video_generate(content, duration=duration,
                            resolution=resolution, ratio=ratio)
    # 立即落库: 后续轮询/下载断连时 job 里仍有服务商 task_id, 可取回
    store.job_update(ctx.jid, {"provider_task": tid, "provider_via": mm.via})
    ctx.log(f"H3 任务 {tid} ({resolution} {duration}s"
            f"{' ratio=' + ratio if ratio else ''})")
    task = mm.video_wait(tid)
    usage = task.get("usage") or {}
    ctx.log(f"H3 完成 usage={usage}")
    mm.download(mm.video_url(task), out)
    return {"video": out}


@node("model/minimax_h3", "模型·MiniMax H3 文/图生视频", "model",
      [("text", "text"), ("?image", "image")], [("video", "video")],
      [P("时长(秒)", "number", 6),
       P("分辨率", "combo", "768P", options=["480p", "512p", "768P", "2K"]),
       P("画幅", "combo", "9:16", options=["9:16", "16:9", "1:1", "adaptive"])])
def n_h3(ctx, ins, ps):
    from . import minimax
    if not (ins.get("text") or "").strip():
        raise NodeError("H3 需要提示词文本")
    content = []
    if ins.get("image"):
        content.append(minimax.Minimax.part_image(_p(ctx, ins["image"])))
    return _h3_run(ctx, content, ctx.tmp("h3", ".mp4"), ps,
                   "生成一段高质量视频", ins)


@node("model/h3_faceswap", "模型·H3 人物替换(换脸)", "model",
      [("video", "video"), ("image", "image"), ("?text", "text")],
      [("video", "video")],
      [P("时长(秒)", "number", 6),
       P("分辨率", "combo", "768P", options=["480p", "512p", "768P", "2K"]),
       P("画幅", "combo", "adaptive", options=["adaptive", "9:16", "16:9", "1:1"])])
def n_h3_faceswap(ctx, ins, ps):
    """对标视频(参考视频) + 人物形象图(参考图) -> 替换人物后的新视频"""
    from . import media, minimax
    src = media.h3_ref_video(_p(ctx, ins["video"]), max_secs=15.0)
    content = [
        minimax.Minimax.part_video(src),
        minimax.Minimax.part_image(_p(ctx, ins["image"])),
    ]
    return _h3_run(ctx, content, ctx.tmp("swap", ".mp4"), ps,
                   "把参考视频中的人物替换为参考图片中的人物，保持动作、表情、"
                   "场景和运镜完全一致，人物五官与参考图一致", ins)


@node("model/h3_avatar", "模型·H3 形象口播(图+声音)", "model",
      [("image", "image"), ("audio", "audio"), ("?text", "text")],
      [("video", "video")],
      [P("时长(秒)", "number", 6),
       P("分辨率", "combo", "768P", options=["480p", "512p", "768P", "2K"]),
       P("画幅", "combo", "9:16", options=["9:16", "16:9", "1:1", "adaptive"])])
def n_h3_avatar(ctx, ins, ps):
    """人物形象图 + 参考音频(口播配音) -> 人物按音频说话的视频"""
    from . import minimax
    content = [
        minimax.Minimax.part_image(_p(ctx, ins["image"])),
        minimax.Minimax.part_audio(_p(ctx, ins["audio"])),
    ]
    return _h3_run(ctx, content, ctx.tmp("avatar", ".mp4"), ps,
                   "图片中的人物对着镜头自然地朗读参考音频的台词，口型准确、"
                   "表情生动、画质清晰", ins)


# ==================== 后处理节点 ====================

@node("proc/mux_audio", "后处理·合成音轨", "proc",
      [("video", "video"), ("audio", "audio")], [("video", "video")], [])
def n_mux(ctx, ins, ps):
    from . import media
    out = ctx.tmp("mux", ".mp4")
    media.mux_audio(_p(ctx, ins["video"]), _p(ctx, ins["audio"]), out)
    return {"video": out}


@node("proc/bgm", "后处理·混入BGM", "proc",
      [("video", "video"), ("audio", "audio")], [("video", "video")],
      [P("BGM音量", "number", 0.15)])
def n_bgm(ctx, ins, ps):
    from . import media
    out = ctx.tmp("bgm", ".mp4")
    media.mix_bgm(_p(ctx, ins["video"]), _p(ctx, ins["audio"]), out,
                  bgm_volume=float(ps.get("BGM音量") or 0.15))
    return {"video": out}


@node("proc/subtitles", "后处理·烧字幕", "proc",
      [("video", "video"), ("text", "text")], [("video", "video")], [])
def n_sub(ctx, ins, ps):
    from . import media
    if not ins.get("text"):
        raise NodeError("字幕需要文本输入")
    v = _p(ctx, ins["video"])
    srt = ctx.tmp("sub", ".srt")
    media.text_to_srt(ins["text"], media.ffprobe_duration(v), srt)
    out = ctx.tmp("sub_v", ".mp4")
    media.burn_subtitles(v, srt, out)
    return {"video": out}


@node("proc/loudnorm", "后处理·响度归一", "proc",
      [("video", "video")], [("video", "video")], [])
def n_loudnorm(ctx, ins, ps):
    from . import media
    out = ctx.tmp("ln", ".mp4")
    media.loudnorm(_p(ctx, ins["video"]), out)
    return {"video": out}


@node("proc/concat", "后处理·视频拼接", "proc",
      [("a", "video"), ("b", "video")], [("video", "video")], [])
def n_concat(ctx, ins, ps):
    from . import media
    out = ctx.tmp("cc", ".mp4")
    media.concat([_p(ctx, ins["a"]), _p(ctx, ins["b"])], out)
    return {"video": out}


# ==================== 输出节点 ====================

@node("output/review", "输出·进审核队列", "output",
      [("media", "*")], [],
      [P("标题", "text", ""), P("简介", "text", ""), P("标签(,分隔)", "text", "")])
def n_out_review(ctx, ins, ps):
    from . import store
    media_path = _p(ctx, ins["media"])
    item = store.add_review_item(media_path, "graph", {
        "title": ps.get("标题") or media_path.stem,
        "desc": ps.get("简介") or "",
        "tags": [t for t in (ps.get("标签(,分隔)") or "").split(",") if t],
        "job": ctx.jid, "inputs": ctx.inputs})
    ctx.items.append(item.stem)
    return {}


@node("output/save", "输出·保存到目录", "output",
      [("media", "*")], [],
      [P("目录", "text", "outputs/saved"), P("文件名", "text", "")])
def n_out_save(ctx, ins, ps):
    src = _p(ctx, ins["media"])
    d = C.ROOT / (ps.get("目录") or "outputs/saved")
    d.mkdir(parents=True, exist_ok=True)
    name = ps.get("文件名") or src.name
    dst = d / name
    shutil.copy2(src, dst)
    ctx.log(f"已保存 {dst}")
    return {}


@node("output/publish", "输出·发布到平台", "output",
      [("media", "*")], [],
      [P("平台", "combo", "douyin", options=["douyin", "xhs", "bilibili", "tencent", "kuaishou"]),
       P("标题", "text", ""), P("标签(,分隔)", "text", ""),
       P("定时发布", "text", "", hint="YYYY-MM-DD HH:MM 可空=立即")])
def n_out_publish(ctx, ins, ps):
    from . import publisher
    media_path = _p(ctx, ins["media"])
    publisher.upload_video(
        media_path, ps.get("标题") or media_path.stem,
        desc="", tags=[t for t in (ps.get("标签(,分隔)") or "").split(",") if t],
        platform=ps.get("平台") or "douyin",
        schedule=ps.get("定时发布") or None)
    ctx.log(f"已发布 {media_path.name}")
    return {}


def schema() -> list[dict]:
    """前端消费的节点 schema"""
    return [{
        "type": d.type, "title": d.title, "category": d.category,
        "inputs": d.inputs, "outputs": d.outputs, "params": d.params,
    } for d in REGISTRY.values()]
