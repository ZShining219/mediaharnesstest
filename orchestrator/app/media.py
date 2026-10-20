"""ffmpeg 后处理工具: 音频合成 / 字幕 / 响度归一化 / BGM / 上传前瘦身"""
import re
import subprocess
from pathlib import Path

from . import config as C


def _run(*args: str):
    proc = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-800:]}")
    return proc


def ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    return float(proc.stdout.strip() or 0)


def has_audio(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return "audio" in proc.stdout


def ffprobe_wh(path: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True)
    try:
        w, h = proc.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return 0, 0


# ---------------- 上传前瘦身: 大参考素材压缩, 降低提交断连概率 ----------------

def _ref_cache(src: Path, suffix: str, tag: str) -> Path:
    """按 路径+mtime 缓存瘦身产物到 tmp"""
    try:
        key = abs(hash((str(src.resolve()), src.stat().st_mtime)))
    except OSError:
        key = abs(hash(str(src)))
    dst = C.TMP_DIR / f"{tag}_{key:x}_{src.stem}{suffix}"
    return dst


def ref_image(src: Path, max_px: int = 1280) -> Path:
    """参考图瘦身: >max_px 或 >0.8MB -> 缩放并重编码 jpg(参考用途足够)。
    小图原样返回。"""
    src = Path(src)
    if src.suffix.lower() in (".jpg", ".jpeg") and src.stat().st_size <= 800 * 1024:
        return src
    dst = _ref_cache(src, ".jpg", "refimg")
    if dst.exists():
        return dst
    _run("-i", str(src),
         "-vf", f"scale={max_px}:{max_px}:force_original_aspect_ratio=decrease"
                ":force_divisible_by=2",
         "-q:v", "4", str(dst))
    return dst


def ref_video(src: Path, max_secs: float | None = None) -> Path:
    """参考视频瘦身: >4MB 或 >720p -> 720p crf25 重编码, 并按需截到 max_secs。
    小而矮的原样返回。"""
    src = Path(src)
    w, h = ffprobe_wh(src)
    need = src.stat().st_size > 4 * 1024 * 1024 or max(w, h) > 1280 or bool(max_secs)
    if not need:
        return src
    dst = _ref_cache(src, ".mp4", f"refvid{int(max_secs or 0)}")
    if dst.exists():
        return dst
    args = ["-i", str(src)]
    if max_secs:
        args += ["-t", str(max_secs)]
    args += ["-vf", "scale=1280:1280:force_original_aspect_ratio=decrease"
             ":force_divisible_by=2", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    _run(*args)
    return dst


H3_REF_MIN_SEC = 2.0
H3_REF_MAX_SEC = 15.0


def h3_ref_video(src: Path, max_secs: float = H3_REF_MAX_SEC) -> Path:
    """H3 参考视频统一瘦身: 裁到 2-15 秒，避免 400
    "media duration must be between 2 and 15.5 seconds"。

    旧代码用 secs+1 做上限，secs=15 时会产出 16 秒参考视频，
    正好越过 H3 的 15.5 秒硬限制。
    """
    src = Path(src)
    dur = ffprobe_duration(src)
    if dur < H3_REF_MIN_SEC:
        raise ValueError(
            f"参考视频太短({dur:.1f}s)，H3 要求 2-15.5 秒；请换长一点的视频")
    return ref_video(src, max_secs=min(H3_REF_MAX_SEC, max_secs))


def mux_audio(video: Path, audio: Path, out: Path):
    """用 audio 替换 video 的音轨"""
    _run("-i", str(video), "-i", str(audio),
         "-c:v", "copy", "-map", "0:v", "-map", "1:a",
         "-c:a", "aac", "-shortest", str(out))


def mix_bgm(video: Path, bgm: Path, out: Path, bgm_volume: float = 0.15):
    """混入背景音。video 无音轨时直接把 BGM 作音轨(否则 amix 会崩)"""
    if has_audio(video):
        _run("-i", str(video), "-stream_loop", "-1", "-i", str(bgm),
             "-filter_complex",
             f"[1:a]volume={bgm_volume}[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(out))
    else:
        _run("-i", str(video), "-stream_loop", "-1", "-i", str(bgm),
             "-filter_complex", f"[1:a]volume={bgm_volume}[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
             "-shortest", str(out))


def concat(videos: list[Path], out: Path):
    """顺序拼接多段视频(要求同编码参数)"""
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{v.resolve()}'\n" for v in videos), encoding="utf-8")
    _run("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))


def trim_keep_audio(video: Path, out: Path, seconds: float):
    """裁剪到指定时长并保留音轨（H3 原生口播/BGM/音效）。"""
    dur = max(0.2, float(seconds))
    _run("-i", str(video), "-t", f"{dur:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(out))


def trim_silent(video: Path, out: Path, seconds: float):
    """裁剪到指定时长并去掉音轨。

    纯带货链路不用 H3 的随机原生音频；H3 最短生成 4 秒，按计划
    2-4 秒裁剪，既控制节奏又统一无音轨，方便后续铺一条 BGM。
    """
    dur = max(0.2, float(seconds))
    _run("-i", str(video), "-t", f"{dur:.3f}", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out))


def mix_bgm_fade(video: Path, bgm: Path, out: Path,
                 volume: float = 0.35, fade_in: float = 0.35,
                 fade_out: float = 0.6):
    """给无音轨成片铺一条循环 BGM，带淡入淡出。

    与 mix_bgm 的区别：不保留/混合视频原音轨，专门服务“无口播、
    只用统一 BGM”的带货视频。
    """
    dur = ffprobe_duration(video)
    fo = max(0.0, dur - max(0.1, fade_out))
    af = (f"volume={volume},"
          f"afade=t=in:st=0:d={max(0.05, fade_in):.2f},"
          f"afade=t=out:st={fo:.3f}:d={max(0.05, fade_out):.2f}")
    _run("-i", str(video), "-stream_loop", "-1", "-i", str(bgm),
         "-filter_complex", f"[1:a]{af}[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-ar", "44100",
         "-shortest", str(out))


def concat_reencode(videos: list[Path], out: Path):
    """编码/尺寸不一致时的重编码拼接(无音轨)。

    逐镜生成可能得到略有差异的尺寸, 先统一 scale+pad 再 concat。
    """
    if not videos:
        raise ValueError("没有可拼接的视频")
    w, h = ffprobe_wh(videos[0])
    args: list[str] = []
    for v in videos:
        args += ["-i", str(v)]
    parts = []
    for i in range(len(videos)):
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(len(videos))) +
                 f"concat=n={len(videos)}:v=1:a=0[v]")
    _run(*args, "-filter_complex", ";".join(parts),
         "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out))


def loudnorm(video: Path, out: Path):
    _run("-i", str(video), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:v", "copy", "-c:a", "aac", "-ar", "44100", str(out))


def burn_subtitles_pil(video: Path, srt: Path, out: Path,
                       font_size: int = 42, margin_v: int = 92,
                       stroke: int = 3, font_path: str | None = None):
    """帧级硬字幕（Pillow + STHeiti），不依赖 ffmpeg 的 libass/freetype。"""
    import shutil
    import tempfile
    from PIL import Image, ImageDraw, ImageFont

    font_path = font_path or "/System/Library/Fonts/STHeiti Medium.ttc"
    if not Path(font_path).exists():
        raise FileNotFoundError(f"字幕字体不存在: {font_path}")
    font = ImageFont.truetype(font_path, font_size, index=0)

    def parse_ts(v: str) -> float:
        h, m, s = v.strip().split(":")
        return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))

    cues = []
    for block in re.split(r"\n\s*\n", srt.read_text(encoding="utf-8").strip()):
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            a, b = lines[1].split("-->")
            cues.append((parse_ts(a), parse_ts(b), "\n".join(lines[2:])))

    tmp = Path(tempfile.mkdtemp(prefix="subs_", dir=str(C.TMP_DIR)))
    try:
        _run("-i", str(video), "-vf", "fps=24", "-q:v", "2",
             str(tmp / "frame_%05d.jpg"))
        for i, p in enumerate(sorted(tmp.glob("frame_*.jpg")), 1):
            t = (i - 1) / 24.0
            text = next((x[2] for x in cues if x[0] <= t < x[1]), "")
            if not text:
                continue
            im = Image.open(p).convert("RGB")
            draw = ImageDraw.Draw(im)
            box = draw.multiline_textbbox((0, 0), text, font=font,
                                          stroke_width=stroke, align="center")
            tw, th = box[2] - box[0], box[3] - box[1]
            x = (im.width - tw) // 2 - box[0]
            y = im.height - margin_v - th - box[1]
            draw.multiline_text((x, y), text, font=font, fill="white",
                                stroke_width=stroke, stroke_fill="black",
                                align="center")
            im.save(p, quality=95)
        _run("-framerate", "24", "-i", str(tmp / "frame_%05d.jpg"),
             "-i", str(video), "-map", "0:v", "-map", "1:a?",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def burn_subtitles(video: Path, srt: Path, out: Path,
                   font_size: int = 14, margin_v: int = 40,
                   outline: int = 1):
    style = (f"FontName=PingFang SC,FontSize={font_size},"
             "PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H00000000,"
             f"Outline={outline},Shadow=0,"
             f"Alignment=2,MarginV={margin_v}")
    # ffmpeg 滤镜参数解析: 路径含空格/中文要用 filename='...' 形式,
    # 且内部 ' \ : 需反斜杠转义
    esc = str(srt.resolve()).replace("\\", "\\\\").replace("'", "\\'") \
        .replace(":", "\\:")
    try:
        _run("-i", str(video), "-vf",
             f"subtitles=filename='{esc}':force_style='{style}'",
             "-c:a", "copy", str(out))
    except RuntimeError as e:
        if "No such filter" not in str(e):
            raise
        # ffmpeg 未编译 libass -> 退化为软字幕轨(可开关)
        _run("-i", str(video), "-i", str(srt),
             "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", str(out))


_PUNC = re.compile(r"[^。！？!?，,；;：:\s]+[。！？!?，,；;：:]?")


def text_to_srt(text: str, duration: float, out: Path,
                max_chars: int = 22) -> Path:
    """按标点切句, 时长均摊生成简易字幕。有精确需求时改用 TTS 时间戳或 ASR。"""
    segs = [m.group(0) for m in _PUNC.finditer(text) if m.group(0).strip()]
    lines: list[str] = []
    for s in segs:
        s = s.strip()
        while len(s) > max_chars:
            lines.append(s[:max_chars])
            s = s[max_chars:]
        if s:
            lines.append(s)
    if not lines:
        lines = [text[:max_chars] or " "]
    per = duration / len(lines)

    def ts(sec: float) -> str:
        h, sec = divmod(sec, 3600)
        m, s = divmod(sec, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"

    body = []
    for i, line in enumerate(lines):
        body.append(f"{i + 1}\n{ts(i * per)} --> {ts((i + 1) * per)}\n{line}\n")
    out.write_text("\n".join(body), encoding="utf-8")
    return out
