"""MiniMax API 客户端: TTS / 声音克隆 / 视频生成(MiniMax-H3) / 文件管理。

文档: https://platform.minimaxi.com/docs/api-reference/api-overview
"""
import json
import time
from pathlib import Path

import httpx

from . import config as C


class MinimaxError(RuntimeError):
    pass


class Minimax:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.key = api_key or C.MINIMAX_API_KEY
        if not self.key:
            raise MinimaxError("缺少 MINIMAX_API_KEY, 请在 .env 中配置")
        self.base = (base_url or C.MINIMAX_BASE_URL).rstrip("/")
        self.http = httpx.Client(
            base_url=self.base, timeout=120,
            headers={"Authorization": f"Bearer {self.key}"},
            params={"GroupId": C.MINIMAX_GROUP_ID} if C.MINIMAX_GROUP_ID else {},
        )

    # ---------------- TTS ----------------

    def tts(self, text: str, voice_id: str, out_path: Path,
            model: str = "speech-2.8-hd", emotion: str | None = None,
            speed: float = 1.0, fmt: str = "mp3", **extra) -> Path:
        """t2a_v2 同步合成, 返回音频文件路径。emotion: happy/sad/angry/fear/disgust/surprise/neutral"""
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
        data = self._post("/v1/t2a_v2", payload)
        audio_hex = (data.get("data") or {}).get("audio")
        if not audio_hex:
            raise MinimaxError(f"TTS 返回无音频: {json.dumps(data, ensure_ascii=False)[:400]}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(bytes.fromhex(audio_hex))
        return out_path

    # ---------------- 声音克隆 ----------------

    def upload_file(self, path: Path, purpose: str = "voice_clone") -> int:
        with open(path, "rb") as f:
            r = self.http.post("/v1/files/upload",
                               files={"file": (path.name, f)},
                               data={"purpose": purpose})
        data = self._check(r)
        return int((data.get("file") or {}).get("file_id") or data.get("file_id"))

    def clone_voice(self, audio_path: Path, voice_id: str,
                    prompt_file_id: int | None = None) -> str:
        payload: dict = {"file_id": self.upload_file(audio_path), "voice_id": voice_id}
        if prompt_file_id:
            payload["clone_prompt"] = {"prompt_audio": prompt_file_id}
        self._post("/v1/voice_clone", payload)
        return voice_id

    # ---------------- 视频生成 (MiniMax-H3) ----------------

    def video_generate(self, prompt: str, model: str = "MiniMax-H3",
                       first_frame_image: str | None = None,
                       subject_reference: list[str] | None = None,
                       duration: int | None = None, resolution: str | None = None,
                       **extra) -> str:
        """提交视频任务, 返回 task_id。
        first_frame_image / subject_reference 传可公网访问的图片 URL 或 base64。"""
        payload: dict = {"model": model, "prompt": prompt, **extra}
        if first_frame_image:
            payload["first_frame_image"] = first_frame_image
        if subject_reference:
            payload["subject_reference"] = [{"image": i} for i in subject_reference]
        if duration:
            payload["duration"] = duration
        if resolution:
            payload["resolution"] = resolution
        data = self._post("/v1/video_generation", payload)
        return data["task_id"]

    def video_wait(self, task_id: str, timeout: float = 1800, poll: float = 10) -> str:
        """轮询直到完成, 返回 file_id"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._check(self.http.get("/v1/query/video_generation",
                                             params={"task_id": task_id}))
            status = data.get("status")
            if status == "Success":
                return data["file_id"]
            if status in ("Fail", "Failed"):
                raise MinimaxError(f"视频生成失败: {json.dumps(data, ensure_ascii=False)[:400]}")
            time.sleep(poll)
        raise MinimaxError(f"视频任务 {task_id} 超时")

    def file_download(self, file_id: str | int, dst: Path) -> Path:
        data = self._check(self.http.get("/v1/files/retrieve",
                                         params={"file_id": file_id}))
        url = (data.get("file") or {}).get("download_url") or data.get("download_url")
        if not url:
            raise MinimaxError(f"file_id {file_id} 无下载地址")
        with self.http.stream("GET", url) as r:
            r.raise_for_status()
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return dst

    # ---------------- internals ----------------

    def _post(self, path: str, payload: dict) -> dict:
        return self._check(self.http.post(path, json=payload))

    @staticmethod
    def _check(r: httpx.Response) -> dict:
        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
            raise
        br = data.get("base_resp") or {}
        if r.status_code >= 400 or (br.get("status_code") not in (None, 0)):
            raise MinimaxError(
                f"HTTP {r.status_code} base_resp={br} "
                f"body={json.dumps(data, ensure_ascii=False)[:400]}")
        return data
