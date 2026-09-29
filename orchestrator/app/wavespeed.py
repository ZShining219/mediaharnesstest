"""WaveSpeed AI 托管模型客户端 (国内直连, 按次计费, 无需GPU)

模型路径速查:
  wavespeed-ai/infinitetalk            图+音频 -> 口播视频 (数字人, ≤10min, 720p)
  wavespeed-ai/infinitetalk-fast       同上快速版
  wavespeed-ai/infinitetalk/multi      双人对话版
  wavespeed-ai/wan-2.2/animate         图+驱动视频: mode=animate 动起来 / mode=replace 换入视频
  wavespeed-ai/wan-2.2/animate-2       图+驱动视频, prompt 可控背景
  wavespeed-ai/qwen-image/edit-plus    图像编辑 (换装/换发型)
  wavespeed-ai/qwen-image/edit         图像编辑基础版

文档: https://wavespeed.ai/docs/docs-api/
"""
import base64
import mimetypes
import time
from pathlib import Path

import httpx

from . import config as C


class WaveSpeedError(RuntimeError):
    pass


BASE = "https://api.wavespeed.ai"
MODEL_INFINITETALK = "wavespeed-ai/infinitetalk"
MODEL_INFINITETALK_FAST = "wavespeed-ai/infinitetalk-fast"
MODEL_WAN_ANIMATE = "wavespeed-ai/wan-2.2/animate"
MODEL_WAN_ANIMATE2 = "wavespeed-ai/wan-2.2/animate-2"
MODEL_QWEN_EDIT = "wavespeed-ai/qwen-image/edit-plus"


class WaveSpeed:
    def __init__(self, api_key: str | None = None):
        self.key = api_key or C.env("WAVESPEED_API_KEY")
        if not self.key:
            raise WaveSpeedError("缺少 WAVESPEED_API_KEY, 请在 .env 中配置")
        self.http = httpx.Client(
            base_url=BASE, timeout=120,
            headers={"Authorization": f"Bearer {self.key}"})

    # ---------------- 上传 ----------------

    def upload(self, path: Path) -> str:
        """上传本地文件换取可访问 URL (输入参数均接受 URL / base64 data URI)"""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        for attempt in range(3):
            try:
                with open(path, "rb") as f:
                    r = self.http.post("/api/v3/media/upload/binary",
                                       content=f.read(),
                                       headers={"Content-Type": mime})
                data = r.json()
                d = data.get("data") or {}
                url = d.get("download_url") or d.get("url")
                if url:
                    return url
                raise WaveSpeedError(f"上传返回无url: {str(data)[:300]}")
            except (httpx.HTTPError, WaveSpeedError) as e:
                if attempt == 2:
                    raise
                time.sleep(2)
        raise WaveSpeedError("unreachable")

    @staticmethod
    def _as_uri(p: Path) -> str:
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        b64 = base64.b64encode(p.read_bytes()).decode()
        return f"data:{mime};base64,{b64}"

    def upload_or_uri(self, path: Path, uri_limit_mb: float = 8) -> str:
        """小文件走 base64, 大文件走上传"""
        if path.stat().st_size < uri_limit_mb * 1024 * 1024:
            return self._as_uri(path)
        return self.upload(path)

    # ---------------- 通用提交/轮询 ----------------

    def submit(self, model: str, inputs: dict) -> str:
        r = self.http.post(f"/api/v3/{model}", json=inputs)
        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
            raise
        if r.status_code >= 400:
            raise WaveSpeedError(f"submit {model} HTTP{r.status_code}: {str(data)[:400]}")
        pid = (data.get("data") or {}).get("id") or data.get("id")
        if not pid:
            raise WaveSpeedError(f"submit {model} 无任务id: {str(data)[:400]}")
        return pid

    def wait(self, prediction_id: str, timeout: float = 3600, poll: float = 5) -> list[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.http.get(f"/api/v3/predictions/{prediction_id}/result")
            data = r.json().get("data") or {}
            status = data.get("status")
            if status == "completed":
                return data.get("outputs") or []
            if status in ("failed", "canceled"):
                raise WaveSpeedError(
                    f"任务失败: {data.get('error') or str(data)[:400]}")
            time.sleep(poll)
        raise WaveSpeedError(f"任务 {prediction_id} 超时")

    def run(self, model: str, inputs: dict, timeout: float = 3600) -> list[str]:
        return self.wait(self.submit(model, inputs), timeout)

    @staticmethod
    def download(url: str, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        return dst

    # ---------------- 业务封装 ----------------

    def infinitetalk(self, image: Path, audio: Path, out: Path,
                     prompt: str = "", resolution: str = "720p",
                     fast: bool = True, seed: int = -1) -> Path:
        """图+音频 -> 对口型说话视频"""
        inputs = {
            "image": self.upload_or_uri(image),
            "audio": self.upload_or_uri(audio),
            "resolution": resolution,
            "seed": seed,
        }
        if prompt:
            inputs["prompt"] = prompt
        model = MODEL_INFINITETALK_FAST if fast else MODEL_INFINITETALK
        urls = self.run(model, inputs)
        return self.download(urls[0], out)

    def wan_animate_replace(self, character_img: Path, source_video: Path,
                            out: Path, resolution: str = "720p") -> Path:
        """把 source_video 中的人替换为 character_img 的形象(保留动作/场景)"""
        inputs = {
            "image": self.upload_or_uri(character_img),
            "video": self.upload(source_video),
            "mode": "replace",
            "resolution": resolution,
        }
        urls = self.run(MODEL_WAN_ANIMATE, inputs)
        return self.download(urls[0], out)

    def wan_animate2(self, character_img: Path, driving_video: Path, out: Path,
                     prompt: str = "", motion_prompt: str = "",
                     resolution: str = "720p") -> Path:
        """形象图按驱动视频动作动起来, prompt 可控制输出背景"""
        inputs = {
            "image": self.upload_or_uri(character_img),
            "video": self.upload(driving_video),
            "resolution": resolution,
        }
        if prompt:
            inputs["prompt"] = prompt
        if motion_prompt:
            inputs["motion_prompt"] = motion_prompt
        urls = self.run(MODEL_WAN_ANIMATE2, inputs)
        return self.download(urls[0], out)

    def image_edit(self, image: Path, prompt: str, out: Path,
                   size: str | None = None, seed: int = -1) -> Path:
        """图像编辑: 换装/换发型/换背景"""
        inputs = {"image": self.upload_or_uri(image), "prompt": prompt,
                  "seed": seed, "output_format": "png"}
        if size:
            inputs["size"] = size
        urls = self.run(MODEL_QWEN_EDIT, inputs)
        return self.download(urls[0], out)
