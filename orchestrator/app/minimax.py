"""MiniMax API 客户端。

两条线路（.env 配置）：
- 视频生成 MiniMax-H3: 默认走秘塔代理 MINIMAX_BASE_URL + MINIMAX_API_KEY (mk- key)
    新版多模态接口: POST {base}/video_generation  body.content = 多模态数组
    轮询: GET {base}/query/video_generation/{task_id}  (task.status/content.url)
- 语音 TTS / 声音克隆: 走官方站 MINIMAX_API_KEY_OFFICIAL + MINIMAX_BASE_URL_OFFICIAL
    (秘塔代理只代理视频接口; 官方接口必须带 GroupId 查询参数, 空值即可)

文档: https://platform.minimaxi.com/docs/api-reference (官方)
     https://metaso.cn/minimax-h3 (秘塔代理说明)
"""
import base64
import json
import mimetypes
import time
from pathlib import Path

import httpx

from . import config as C


class MinimaxError(RuntimeError):
    pass


def file_data_uri(p: Path) -> str:
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def as_url(v) -> str:
    """素材值 -> 可提交 URL: http(s)/data: 原样, 本地路径转 base64 data URI"""
    s = str(v)
    if s.startswith(("http://", "https://", "data:")):
        return s
    p = Path(v)
    if not p.is_absolute():
        p = C.ROOT / p
    return file_data_uri(p)


class Minimax:
    """默认实例: 秘塔代理(视频)。Minimax.official() -> 官方站(TTS/克隆)。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 group_id: str | None = ""):
        self.key = api_key or C.MINIMAX_API_KEY
        if not self.key:
            raise MinimaxError("缺少 MINIMAX_API_KEY, 请在 .env 中配置")
        self.base = (base_url or C.MINIMAX_BASE_URL).rstrip("/")
        gid = C.MINIMAX_GROUP_ID if group_id == "" else group_id
        self.http = httpx.Client(
            base_url=self.base, timeout=120,
            headers={"Authorization": f"Bearer {self.key}"},
            # 官方站必须带 GroupId 参数(可空); 秘塔代理会忽略它
            params={"GroupId": gid or ""},
        )

    @classmethod
    def official(cls) -> "Minimax":
        """官方站实例 (TTS/声音克隆/官方视频计费)"""
        key = C.env("MINIMAX_API_KEY_OFFICIAL") or C.MINIMAX_API_KEY
        base = C.env("MINIMAX_BASE_URL_OFFICIAL", "https://api.minimax.cn")
        return cls(api_key=key, base_url=base)

    def _v1(self, path: str) -> str:
        """把 /v2 结尾的 base 换成 /v1 (官方 t2a_v2 等旧接口在 v1 下)"""
        base = self.base
        for suf in ("/v2", "/v1"):
            if base.endswith(suf):
                base = base[: -len(suf)]
                break
        return base + "/v1" + path

    # ---------------- 多模态内容块 ----------------

    @staticmethod
    def part_text(text: str) -> dict:
        return {"type": "text", "text": text}

    @staticmethod
    def part_image(v) -> dict:
        return {"type": "image_url", "image_url": {"url": as_url(v)},
                "role": "reference_image"}

    @staticmethod
    def part_video(v) -> dict:
        return {"type": "video_url", "video_url": {"url": as_url(v)},
                "role": "reference_video"}

    @staticmethod
    def part_audio(v) -> dict:
        return {"type": "audio_url", "audio_url": {"url": as_url(v)},
                "role": "reference_audio"}

    # ---------------- 视频生成 (MiniMax-H3, content 数组接口) ----------------

    def video_generate(self, content: list[dict] | str, model: str = "MiniMax-H3",
                       resolution: str = "768P", duration: int | None = None,
                       ratio: str | None = None, aigc_watermark: bool = False,
                       **extra) -> str:
        """提交视频任务, 返回 task_id。
        content: 多模态数组 [{type:text|image_url|video_url|audio_url,...}],
                 传 str 时自动包成纯文本提示。"""
        if isinstance(content, str):
            content = [self.part_text(content)]
        body = {"model": model, "content": content, "resolution": resolution,
                "aigc_watermark": aigc_watermark, **extra}
        if duration:
            body["duration"] = int(duration)
        if ratio:
            body["ratio"] = ratio
        data = self._post("/video_generation", body)
        tid = data.get("task_id") or (data.get("task") or {}).get("task_id")
        if not tid:
            raise MinimaxError(f"未返回 task_id: {json.dumps(data, ensure_ascii=False)[:400]}")
        return tid

    def video_query(self, task_id: str) -> dict:
        """返回 task dict: {status, content:{url}, usage, base_resp, error}"""
        data = self._check(self.http.get(f"/query/video_generation/{task_id}"))
        return data.get("task") or data

    def video_wait(self, task_id: str, timeout: float = 1800,
                   poll: float = 8) -> dict:
        """轮询直到完成, 返回 task dict (含 content.url 与 usage)"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self.video_query(task_id)
            status = str(task.get("status") or "").lower()
            if status in ("succeeded", "success"):
                return task
            if status in ("failed", "fail", "cancelled", "canceled"):
                msg = ((task.get("error") or {}).get("message")
                       or (task.get("base_resp") or {}).get("status_msg")
                       or json.dumps(task, ensure_ascii=False)[:300])
                raise MinimaxError(f"视频生成失败: {msg}")
            time.sleep(poll)
        raise MinimaxError(f"视频任务 {task_id} 超时")

    def video_url(self, task: dict) -> str:
        url = (task.get("content") or {}).get("url") or task.get("url")
        if not url:
            raise MinimaxError(f"任务完成但无视频地址: {json.dumps(task, ensure_ascii=False)[:300]}")
        return url

    @staticmethod
    def download(url: str, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        return dst

    def video_wait_download(self, task_id: str, dst: Path,
                            timeout: float = 1800) -> dict:
        """等待 + 下载, 返回 task dict (含 usage)"""
        task = self.video_wait(task_id, timeout=timeout)
        self.download(self.video_url(task), dst)
        return task

    # ---------------- TTS (官方站) ----------------

    def tts(self, text: str, voice_id: str, out_path: Path,
            model: str = "speech-2.6-hd", emotion: str | None = None,
            speed: float = 1.0, fmt: str = "mp3", **extra) -> Path:
        """t2a_v2 同步合成。emotion: happy/sad/angry/fear/disgust/surprise/neutral"""
        client = self if "metaso" not in self.base else Minimax.official()
        voice_setting = {"voice_id": voice_id, "speed": speed, "vol": 1.0, "pitch": 0}
        if emotion:
            voice_setting["emotion"] = emotion
        payload = {
            "model": model, "text": text, "stream": False,
            "language_boost": "auto", "output_format": "hex",
            "voice_setting": voice_setting,
            "audio_setting": {"format": fmt, "sample_rate": 32000,
                              "bitrate": 128000, "channel": 1},
            **extra,
        }
        r = client.http.post(client._v1("/t2a_v2"), json=payload)
        data = client._check(r)
        audio_hex = (data.get("data") or {}).get("audio")
        if not audio_hex:
            raise MinimaxError(f"TTS 返回无音频: {json.dumps(data, ensure_ascii=False)[:400]}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(bytes.fromhex(audio_hex))
        return out_path

    # ---------------- 声音克隆 (官方站) ----------------

    def upload_file(self, path: Path, purpose: str = "voice_clone") -> int:
        client = self if "metaso" not in self.base else Minimax.official()
        with open(path, "rb") as f:
            r = client.http.post(client._v1("/files/upload"),
                                 files={"file": (path.name, f)},
                                 data={"purpose": purpose})
        data = client._check(r)
        return int((data.get("file") or {}).get("file_id") or data.get("file_id"))

    def clone_voice(self, audio_path: Path, voice_id: str,
                    prompt_file_id: int | None = None) -> str:
        client = self if "metaso" not in self.base else Minimax.official()
        payload: dict = {"file_id": client.upload_file(audio_path),
                         "voice_id": voice_id}
        if prompt_file_id:
            payload["clone_prompt"] = {"prompt_audio": prompt_file_id}
        client._post(client._v1("/voice_clone"), payload)
        return voice_id

    # ---------------- internals ----------------

    def _post(self, path: str, payload: dict) -> dict:
        # path 可为绝对路径(http...)或相对 base 的路径
        return self._check(self.http.post(path, json=payload))

    @staticmethod
    def _check(r: httpx.Response) -> dict:
        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
            raise
        br = data.get("base_resp") or {}
        err = data.get("error") or {}
        if (r.status_code >= 400 or (br.get("status_code") not in (None, 0))
                or (data.get("type") == "error" and err)):
            raise MinimaxError(
                f"HTTP {r.status_code} base_resp={br} error={err} "
                f"body={json.dumps(data, ensure_ascii=False)[:400]}")
        return data
