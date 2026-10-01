"""ffmpeg 后处理工具: 音频合成 / 字幕 / 响度归一化 / BGM"""
import re
import subprocess
from pathlib import Path


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


def mux_audio(video: Path, audio: Path, out: Path):
    """用 audio 替换 video 的音轨"""
    _run("-i", str(video), "-i", str(audio),
         "-c:v", "copy", "-map", "0:v", "-map", "1:a",
         "-c:a", "aac", "-shortest", str(out))


def mix_bgm(video: Path, bgm: Path, out: Path, bgm_volume: float = 0.15):
    _run("-i", str(video), "-stream_loop", "-1", "-i", str(bgm),
         "-filter_complex",
         f"[1:a]volume={bgm_volume}[bg];[0:a][bg]amix=inputs=2:duration=first[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(out))


def concat(videos: list[Path], out: Path):
    """顺序拼接多段视频(要求同编码参数)"""
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{v.resolve()}'\n" for v in videos), encoding="utf-8")
    _run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(out))


def loudnorm(video: Path, out: Path):
    _run("-i", str(video), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:v", "copy", "-c:a", "aac", str(out))


def burn_subtitles(video: Path, srt: Path, out: Path):
    style = ("FontName=PingFang SC,FontSize=14,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H00000000,Outline=1,Shadow=0,"
             "Alignment=2,MarginV=40")
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
