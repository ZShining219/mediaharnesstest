"""参考视频池的案例描述（encoder）。

设计对应 docs/reference-prompt-reverse.md：
- L1 证据：镜头切分 / 关键帧 / ASR / 音频统计
- L2 全量描述：视觉事实 + 9 角色视角 + H3 提示词蓝图
- 输出落盘到 data/reference_cases/{ref_id}/，供下游检索/泛化/解码使用

只读原视频；不修改 assets/ 与 reference_pool.json。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path

from . import config as C, llm, media, reference_pool
from .jsonutil import extract_json

log = logging.getLogger("reference_analysis")

CASES_DIR = C.ROOT / "data" / "reference_cases"
CASES_DIR.mkdir(parents=True, exist_ok=True)
WHISPER_DIR = C.ROOT / "models" / "whisper"
WHISPER_DIR.mkdir(parents=True, exist_ok=True)

_WHISPER = None

ROLES = ["audience", "director", "cinematographer", "editor", "art",
         "sound", "marketing", "platform", "generator"]


def _log(msg: str):
    log.info(msg)
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _run(cmd: list[str], timeout: int = 300) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(
            f"命令失败 ({p.returncode}): {' '.join(cmd[:4])}...\n"
            f"{p.stderr[-800:]}")
    return p.stdout


def _uniform_shots(duration: float, n: int) -> list[dict]:
    n = max(2, min(10, int(n)))
    step = duration / n
    return [{
        "index": i + 1,
        "start": round(i * step, 2),
        "end": round(min(duration, (i + 1) * step), 2),
    } for i in range(n)]


def _merge_shots(shots: list[dict], max_shots: int = 8) -> list[dict]:
    if len(shots) <= max_shots:
        return shots
    total = shots[-1]["end"] - shots[0]["start"]
    target = total / max_shots
    out: list[dict] = []
    cur_start, cur_end = shots[0]["start"], shots[0]["end"]
    for s in shots[1:]:
        if (s["end"] - cur_start) > target * 1.15 and len(out) < max_shots - 1:
            out.append({"start": cur_start, "end": cur_end})
            cur_start, cur_end = s["start"], s["end"]
        else:
            cur_end = s["end"]
    out.append({"start": cur_start, "end": cur_end})
    return [{"index": i + 1, "start": round(s["start"], 2),
             "end": round(s["end"], 2)} for i, s in enumerate(out)]


def detect_shots(video: Path, duration: float) -> list[dict]:
    shots: list[dict] = []
    try:
        from scenedetect import ContentDetector, detect
        scenes = detect(str(video), ContentDetector(
            threshold=27.0, min_scene_len=12))
        shots = [{
            "index": i + 1,
            "start": round(s.get_seconds(), 2),
            "end": round(e.get_seconds(), 2),
        } for i, (s, e) in enumerate(scenes)]
    except Exception as e:
        log.warning("PySceneDetect 失败，退回均匀切分: %s", e)
    if len(shots) <= 1:
        n = max(3, min(8, round(duration / 6)))
        shots = _uniform_shots(duration, n)
    return _merge_shots(shots, 8)


def extract_frames(video: Path, shots: list[dict], out_dir: Path,
                   width: int = 560) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    for s in shots:
        mid = (float(s["start"]) + float(s["end"])) / 2
        out = out_dir / f"shot_{s['index']:02d}.jpg"
        try:
            _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.3f}",
                  "-i", str(video), "-frames:v", "1",
                  "-vf", f"scale={width}:-1", "-q:v", "3", str(out)],
                 timeout=60)
            if out.exists() and out.stat().st_size > 0:
                s["frame"] = str(out.relative_to(C.ROOT))
                s["frame_time"] = round(mid, 2)
                frames.append({"index": s["index"], "time": mid,
                               "path": out, "rel": s["frame"]})
        except Exception as e:
            log.warning("抽帧失败 shot=%s: %s", s["index"], e)
    if not frames:
        raise RuntimeError("没有抽到任何关键帧")
    return frames


def _whisper():
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel
        name = C.env("WHISPER_MODEL", "base")
        # faster-whisper 1.2 与 huggingface_hub 2.x 的下载 API 不兼容；
        # 若本地已有 snapshot，直接按目录加载，避免走 hf_hub_download。
        local_root = WHISPER_DIR / f"models--Systran--faster-whisper-{name}"
        snapshots = sorted((local_root / "snapshots").glob("*"))
        if snapshots:
            name = str(snapshots[-1])
        _log(f"加载 faster-whisper 模型: {name}")
        _WHISPER = WhisperModel(
            name, device="cpu", compute_type="int8",
            download_root=str(WHISPER_DIR))
    return _WHISPER


def transcribe(video: Path) -> list[dict]:
    """ASR；失败返回空列表，不阻塞整条链路。"""
    try:
        model = _whisper()
        wav = C.TMP_DIR / f"asr_{video.stem[:16]}.wav"
        _run(["ffmpeg", "-v", "error", "-y", "-i", str(video),
              "-ac", "1", "-ar", "16000", str(wav)], timeout=300)
        # 直接传 numpy 数组，绕过 PyAV 19 与 faster-whisper 的
        # metadata_errors 参数不兼容问题。
        import wave
        import numpy as np
        with wave.open(str(wav), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            audio = np.frombuffer(raw, dtype=np.int16).astype(
                np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio, language="zh", vad_filter=True, beam_size=1)
        out = []
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                out.append({"start": round(float(seg.start), 2),
                            "end": round(float(seg.end), 2),
                            "text": text})
        try:
            wav.unlink()
        except Exception:
            pass
        return out
    except Exception as e:
        log.warning("ASR 失败，跳过: %s", e)
        return []


def audio_profile(video: Path) -> dict:
    info = {"has_audio": False, "mean_volume_db": None,
            "max_volume_db": None}
    try:
        info["has_audio"] = media.has_audio(video)
        if not info["has_audio"]:
            return info
        stderr = ""
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(video),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120)
        stderr = p.stderr or ""
        m = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", stderr)
        if m:
            info["mean_volume_db"] = float(m.group(1))
        m = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", stderr)
        if m:
            info["max_volume_db"] = float(m.group(1))
    except Exception as e:
        log.warning("音频统计失败: %s", e)
    return info


VISION_SCHEMA = {
    "global": {
        "category": "", "scene": "", "visual_style": "", "lighting": "",
        "color_palette": [], "pacing": "", "camera_language": "",
        "on_screen_text_style": "", "product": "",
    },
    "shots": [{
        "index": 1, "start": 0, "end": 0,
        "shot_size": "", "angle": "", "camera": "", "lighting": "",
        "color": "", "composition": "", "subject": "", "action": "",
        "product": "", "product_visibility": "", "on_screen_text": "",
        "transition": "", "confidence": 0.0,
    }],
}

ROLE_SCHEMA = {
    "roles": {r: {"observations": [], "inferences": [],
                  "key_moments": [], "confidence": 0.0} for r in ROLES},
    "blueprint": {
        "global_style": "",
        "shot_prompts": [{"index": 1, "time": [0, 0], "prompt": ""}],
        "camera_language": "", "lighting": "", "pacing": "",
        "on_screen_text_style": "", "negative": [],
        "invariants": [], "variables": [], "hard_constraints": [],
        "soft_constraints": [], "reference_role_map": {},
        "structure": {"hook": "", "beat_order": [], "proof": "",
                      "cta": ""},
    },
}

VISION_SYSTEM = """你是视频逆向分析摄影师。你只描述画面里真实可见的内容。
禁止编造看不到的细节；不确定就写“不确定”。运镜使用受控词表：
static / handheld / pan_left / pan_right / tilt_up / tilt_down /
truck_left / truck_right / dolly_in / dolly_out / zoom_in / zoom_out /
orbit / crane_up / crane_down / roll。景别使用：
extreme_close_up / close_up / medium_close_up / medium / full / wide。
只输出 JSON。"""

ROLE_SYSTEM = """你是视频案例库的分析团队。基于给定的逐镜事实、字幕与音频统计，
从 9 个角色视角输出观察与推断，并生成一份可迁移的 H3 提示词蓝图。
纪律：
- observations 只能写可从事实层得到的内容；
- inferences 写推断，必须标注不确定性；
- 不要把推断写成事实；
- 蓝图要描述“画面怎么成立”，不要写成营销口号；
- 只输出 JSON。"""


def _ref_llm(timeout: float = 300):
    """案例描述默认用非 reasoning 的 deepseek-chat，避免 reasoning 吃掉输出预算。"""
    return llm.LLM(model=C.env("REFERENCE_LLM_MODEL", "deepseek-chat"),
                   timeout=timeout)


def _llm_json(fn, label: str, attempts: int = 3) -> dict | None:
    last = None
    for i in range(attempts):
        try:
            txt = fn(i)
            data = extract_json(txt)
            if data:
                return data
            last = ValueError("JSON 解析失败")
            log.warning("%s 第 %d 次输出无 JSON: %s", label, i + 1, txt[:300])
        except Exception as e:
            last = e
            log.warning("%s 第 %d 次失败: %s", label, i + 1, e)
        time.sleep(1.5 * (i + 1))
    log.warning("%s 最终失败: %s", label, last)
    return None


def describe_visual(ref: dict, shots: list[dict], frames: list[dict],
                    transcript: list[dict], audio: dict) -> dict:
    shot_lines = "\n".join(
        f"- 图{i + 1} = shot {f['index']}，时间 {shots[i]['start']}-{shots[i]['end']}s，"
        f"这是该镜头中间帧"
        for i, f in enumerate(frames))
    transcript_text = "\n".join(
        f"[{s['start']}-{s['end']}] {s['text']}" for s in transcript[:80]) or "（无可用字幕）"
    prompt = f"""视频元数据：
标题：{ref.get('title', '')}
备注：{ref.get('note', '')}
标签：{ref.get('tags', [])}
时长：{ref.get('duration', '')}s

可用的帧（按时间顺序）：
{shot_lines}

音频统计：{json.dumps(audio, ensure_ascii=False)}
ASR 字幕（可能不完整）：
{transcript_text}

请输出两类内容，严格按下面 JSON 结构：
{json.dumps(VISION_SCHEMA, ensure_ascii=False, indent=1)}

要求：
1. global 是整条视频的全局判断；shots 必须与上面给出的图一一对应，数量一致。
2. 每个 shot 描述景别、角度、运镜、光线、色彩、构图、主体、动作、商品、商品可见度、画面文字、转场。
3. 画面文字尽量逐字抄录；看不清就写“不确定”，不要猜。
4. product 要具体到品类/颜色/材质/结构/细节；product_visibility 用 full/partial/background/none。
5. confidence 是 0-1，表示该镜头描述的把握程度。
6. 只输出 JSON。"""
    data = _llm_json(
        lambda i: _ref_llm().chat_vision(
            prompt, [f["path"] for f in frames],
            system=VISION_SYSTEM, max_tokens=6000,
            temperature=0.15 if i == 0 else 0.05, json_mode=True),
        f"视觉描述 {ref.get('id')}")
    if not data:
        raise RuntimeError("视觉描述失败")
    data.setdefault("global", {})
    got = data.get("shots") or data.get("frames") or []
    if not isinstance(got, list):
        got = []
    # 按帧顺序补齐/对齐，避免模型少写或多写
    norm = []
    for i, s in enumerate(shots):
        item = got[i] if i < len(got) and isinstance(got[i], dict) else {}
        item = {**item, "index": s["index"],
                "start": s["start"], "end": s["end"]}
        norm.append(item)
    data["shots"] = norm
    return data


def _fallback_blueprint(visual: dict) -> dict:
    """角色/蓝图 LLM 失败时的兜底：仍然保存可检索的逐镜描述。"""
    g = visual.get("global") or {}
    return {
        "global_style": " ".join(str(g.get(k) or "") for k in (
            "category", "scene", "visual_style", "lighting", "pacing",
            "camera_language", "product")),
        "shot_prompts": [{
            "index": s.get("index"),
            "time": [s.get("start"), s.get("end")],
            "prompt": "；".join(str(s.get(k) or "") for k in (
                "shot_size", "angle", "camera", "lighting", "subject",
                "action", "product", "on_screen_text", "transition")),
        } for s in (visual.get("shots") or [])],
        "camera_language": g.get("camera_language") or "",
        "lighting": g.get("lighting") or "",
        "pacing": g.get("pacing") or "",
        "on_screen_text_style": g.get("on_screen_text_style") or "",
        "negative": [],
        "invariants": [],
        "variables": [],
        "hard_constraints": [],
        "soft_constraints": [],
        "reference_role_map": {},
        "structure": {},
    }


def roles_and_blueprint(ref: dict, visual: dict, transcript: list[dict],
                        audio: dict) -> dict:
    transcript_text = "\n".join(
        f"[{s['start']}-{s['end']}] {s['text']}" for s in transcript[:100]) or "（无）"
    base = f"""视频元数据：
{json.dumps({k: ref.get(k) for k in ('id', 'title', 'note', 'tags', 'duration', 'source_url')}, ensure_ascii=False, indent=1)}

逐镜事实：
{json.dumps(visual, ensure_ascii=False)[:12000]}

ASR 字幕：
{transcript_text}

音频统计：
{json.dumps(audio, ensure_ascii=False)}
"""
    prompt = base + f"""
请输出 roles + blueprint，严格按下面 JSON 结构：
{json.dumps(ROLE_SCHEMA, ensure_ascii=False, indent=1)}

角色问题集：
- audience：前 3 秒看到/听到什么？注意力锚点？信息记忆点？可能划走的位置？
- director：叙事节拍、冲突/转折、信息释放顺序、意图。
- cinematographer：景别/机位/焦段感/运镜/光线/构图/色彩。
- editor：切点密度、转场类型、节奏曲线、字幕节奏。
- art：场景、道具、服装、材质、色彩、品牌资产。
- sound：人声/口播、BGM、音效、节拍；只能基于字幕与音频统计推断。
- marketing：卖点顺序、证明方式、CTA、优惠/价格露出。
- platform：画幅、安全区、字幕样式、平台原生感、合规风险。
- generator：哪些元素可被 H3 复现？哪些是风险项？需要什么参考图？

输出纪律（很重要，避免 JSON 被截断）：
- 每个角色只写 3-5 条 observations、2-3 条 inferences、2-3 条 key_moments；
- 每条不超过 50 字；
- blueprint 的 shot_prompts 每镜不超过 150 字；
- invariants / variables / hard_constraints / soft_constraints 各不超过 7 条；
- 总输出控制在 3500 字以内；
- 只输出 JSON。"""
    data = _llm_json(
        lambda i: _ref_llm().chat(
            prompt, system=ROLE_SYSTEM, max_tokens=8000,
            temperature=0.35 if i == 0 else 0.15, json_mode=True),
        f"角色与蓝图 {ref.get('id')}")
    if not data:
        compact = base + """
上一次输出过长/不合法。这次只输出一个紧凑 JSON：
- roles 只含 audience / director / cinematographer / editor / marketing / generator；
- 每个角色 3 条 observations + 2 条 inferences；
- blueprint 只含 global_style、shot_prompts（每镜≤100字）、invariants（≤5）、variables（≤5）、hard_constraints（≤5）、soft_constraints（≤5）、structure；
- 总输出不超过 2000 字；只输出 JSON。"""
        data = _llm_json(
            lambda i: _ref_llm().chat(
                compact, system=ROLE_SYSTEM, max_tokens=8000,
                temperature=0.2, json_mode=True),
            f"角色与蓝图紧凑 {ref.get('id')}", attempts=2)
    if not data:
        log.warning("角色/蓝图最终失败，使用兜底蓝图: %s", ref.get("id"))
        return {"roles": {r: {"observations": [], "inferences": [],
                              "key_moments": [], "confidence": 0.0}
                          for r in ROLES},
                "blueprint": _fallback_blueprint(visual)}
    roles = data.get("roles") or {}
    if not isinstance(roles, dict):
        roles = {}

    def norm_role(v):
        if isinstance(v, dict):
            return {
                "observations": v.get("observations") or [],
                "inferences": v.get("inferences") or [],
                "key_moments": v.get("key_moments") or [],
                "confidence": v.get("confidence") or 0.0,
            }
        if isinstance(v, str):
            return {"observations": [v], "inferences": [],
                    "key_moments": [], "confidence": 0.0}
        if isinstance(v, list):
            return {"observations": [str(x) for x in v],
                    "inferences": [], "key_moments": [],
                    "confidence": 0.0}
        return {"observations": [], "inferences": [],
                "key_moments": [], "confidence": 0.0}

    roles = {r: norm_role(roles.get(r)) for r in ROLES}
    bp = data.get("blueprint")
    if not isinstance(bp, dict):
        bp = _fallback_blueprint(visual)
    return {"roles": roles, "blueprint": bp}


def _write_markdown(case_dir: Path, ref: dict, visual: dict,
                    extra: dict, transcript: list[dict]) -> Path:
    bp = extra.get("blueprint") or {}
    lines = [f"# {ref.get('title') or ref.get('id')}", "",
             f"- 来源：{ref.get('source_url', '')}",
             f"- 时长：{ref.get('duration', '')}s",
             f"- 标签：{', '.join(ref.get('tags') or [])}", ""]
    g = visual.get("global") or {}
    lines += ["## 全局", ""]
    for k in ("category", "scene", "visual_style", "lighting", "pacing",
              "camera_language", "on_screen_text_style", "product"):
        if g.get(k):
            lines.append(f"- **{k}**：{g[k]}")
    if g.get("color_palette"):
        lines.append(f"- **color_palette**：{', '.join(map(str, g['color_palette']))}")
    lines += ["", "## 分镜", ""]
    for s in visual.get("shots") or []:
        lines.append(f"### Shot {s.get('index')} · {s.get('start')}–{s.get('end')}s")
        for k in ("shot_size", "angle", "camera", "lighting", "color",
                  "composition", "subject", "action", "product",
                  "product_visibility", "on_screen_text", "transition"):
            if s.get(k):
                lines.append(f"- {k}: {s[k]}")
        lines.append("")
    lines += ["## 角色视角", ""]
    roles = extra.get("roles") or {}
    for r in ROLES:
        d = roles.get(r) or {}
        if not isinstance(d, dict):
            d = {"observations": [str(d)]}
        lines.append(f"### {r}")
        for label, key in (("观察", "observations"), ("推断", "inferences")):
            for x in d.get(key) or []:
                lines.append(f"- {label}：{x}")
        for x in d.get("key_moments") or []:
            lines.append(f"- 关键时刻：{x}")
        lines.append("")
    lines += ["## H3 蓝图", "", f"**全局风格**：{bp.get('global_style', '')}", ""]
    shot_prompts = bp.get("shot_prompts") or []
    if isinstance(shot_prompts, dict):
        shot_prompts = [shot_prompts]
    for s in shot_prompts:
        if not isinstance(s, dict):
            continue
        lines.append(f"### Shot {s.get('index')} · {s.get('time')}")
        lines.append(str(s.get("prompt") or ""))
        lines.append("")
    for key in ("invariants", "variables", "hard_constraints",
                "soft_constraints", "negative"):
        vals = bp.get(key)
        if isinstance(vals, str):
            vals = [vals]
        if vals:
            lines.append(f"### {key}")
            for x in vals:
                lines.append(f"- {x}")
            lines.append("")
    if transcript:
        lines += ["## 字幕/转写", ""]
        for s in transcript:
            lines.append(f"- [{s['start']}-{s['end']}] {s['text']}")
    out = case_dir / "prompt_blueprint.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def analyze_one(ref: dict, force: bool = False,
                transcribe_audio: bool = True) -> dict:
    ref_id = ref.get("id")
    if not ref_id:
        raise ValueError("参考池条目缺少 id")
    case_dir = CASES_DIR / ref_id
    desc_path = case_dir / "descriptions.json"
    if desc_path.exists() and not force:
        try:
            old = json.loads(desc_path.read_text(encoding="utf-8"))
            return {"id": ref_id, "ok": True, "cached": True,
                    "shots": len(old.get("shots") or []),
                    "video": old.get("meta", {}).get("path")}
        except Exception:
            pass

    case_dir.mkdir(parents=True, exist_ok=True)
    video = Path(ref.get("path") or "")
    if not video.is_absolute():
        video = C.ROOT / video
    if not video.is_file():
        raise FileNotFoundError(f"视频不存在: {video}")

    _log(f"开始 {ref_id} · {video.name[:50]}")
    duration = float(ref.get("duration") or media.ffprobe_duration(video) or 0)
    w, h = media.ffprobe_wh(video)
    shots = detect_shots(video, duration)
    frames = extract_frames(video, shots, case_dir / "frames")
    transcript = transcribe(video) if transcribe_audio else []
    audio = audio_profile(video)
    _log(f"{ref_id} 镜头 {len(shots)} / 帧 {len(frames)} / 字幕 {len(transcript)}")

    visual = describe_visual(ref, shots, frames, transcript, audio)
    extra = roles_and_blueprint(ref, visual, transcript, audio)

    evidence = {
        "ref_id": ref_id,
        "video": str(video.relative_to(C.ROOT)) if video.is_relative_to(C.ROOT) else str(video),
        "duration": round(duration, 2),
        "width": w, "height": h,
        "shots": shots,
        "transcript": transcript,
        "audio": audio,
        "frames": [f["rel"] for f in frames],
    }
    doc = {
        "ref_id": ref_id,
        "meta": {k: ref.get(k) for k in
                 ("id", "path", "title", "note", "tags", "source_url",
                  "duration", "created_at", "exists", "filename", "size")},
        "global": visual.get("global") or {},
        "shots": visual.get("shots") or [],
        "roles": extra.get("roles") or {},
        "blueprint": extra.get("blueprint") or {},
        "transcript": transcript,
        "audio": audio,
        "analyzed_at": int(time.time()),
    }
    (case_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_dir / "descriptions.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_dir / "prompt_blueprint.json").write_text(
        json.dumps(extra.get("blueprint") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    _write_markdown(case_dir, ref, visual, extra, transcript)
    _log(f"完成 {ref_id}")
    return {"id": ref_id, "ok": True, "shots": len(shots),
            "frames": len(frames), "transcript": len(transcript),
            "video": str(video)}


def rebuild_case_index() -> dict:
    """全量重建 data/reference_cases/index.json。

    以目录中的 descriptions.json 为准，避免 analyze_pool 只写当前批次
    导致索引条数小于实际案例数。
    """
    items = []
    for p in sorted(CASES_DIR.glob("*/descriptions.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        try:
            ev = json.loads((p.parent / "evidence.json").read_text(
                encoding="utf-8"))
        except Exception:
            ev = {}
        meta = d.get("meta") or {}
        items.append({
            "id": d.get("ref_id") or p.parent.name,
            "ok": True,
            "shots": len(d.get("shots") or []),
            "frames": len(ev.get("frames") or []),
            "transcript": len(d.get("transcript") or []),
            "video": meta.get("path") or "",
        })
    index = {
        "generated_at": int(time.time()),
        "total": len(items),
        "ok": sum(1 for x in items if x["ok"]),
        "failed": sum(1 for x in items if not x["ok"]),
        "items": items,
    }
    (CASES_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def analyze_pool(limit: int | None = None, ids: list[str] | None = None,
                 force: bool = False, transcribe_audio: bool = True) -> dict:
    items = reference_pool.list_items()
    if ids:
        keep = set(ids)
        items = [x for x in items if x.get("id") in keep]
    if limit:
        items = items[:limit]
    results = []
    for i, ref in enumerate(items, 1):
        _log(f"[{i}/{len(items)}] {ref.get('id')}")
        try:
            results.append(analyze_one(
                ref, force=force, transcribe_audio=transcribe_audio))
        except Exception as e:
            log.exception("分析失败 %s", ref.get("id"))
            results.append({"id": ref.get("id"), "ok": False,
                            "error": f"{type(e).__name__}: {e}"})
    index = rebuild_case_index()
    index["batch"] = {
        "total": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
    }
    return index


def list_cases() -> list[dict]:
    """供前端：列出已完成描述的案例摘要。"""
    out = []
    for p in sorted(CASES_DIR.glob("*/descriptions.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = d.get("meta") or {}
        roles = d.get("roles") or {}
        out.append({
            "ref_id": d.get("ref_id") or p.parent.name,
            "title": m.get("title") or "",
            "tags": m.get("tags") or [],
            "duration": m.get("duration"),
            "shots": len(d.get("shots") or []),
            "roles": sum(1 for v in roles.values()
                         if isinstance(v, dict)
                         and (v.get("observations") or v.get("inferences"))),
            "transcript": len(d.get("transcript") or []),
            "analyzed_at": d.get("analyzed_at") or int(p.stat().st_mtime),
            "has_blueprint": bool(d.get("blueprint")),
        })
    out.sort(key=lambda x: x.get("analyzed_at") or 0, reverse=True)
    return out


def load_case(ref_id: str) -> dict:
    if "/" in ref_id or "\\" in ref_id or ".." in ref_id:
        raise ValueError("非法 ref_id")
    p = CASES_DIR / ref_id / "descriptions.json"
    if not p.exists():
        raise FileNotFoundError(f"案例描述不存在: {ref_id}")
    return json.loads(p.read_text(encoding="utf-8"))
