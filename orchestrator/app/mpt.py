"""MoneyPrinterTurbo API 客户端 (services/MoneyPrinterTurbo 本地服务)"""
import time
from pathlib import Path

import httpx

from . import config as C


class MPTError(RuntimeError):
    pass


class MPT:
    def __init__(self, base_url: str | None = None):
        self.base = (base_url or C.MPT_BASE_URL).rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=60)

    def health(self) -> bool:
        try:
            return self.http.get("/ping").status_code == 200
        except httpx.HTTPError:
            try:
                return self.http.get("/api/ping").status_code == 200
            except httpx.HTTPError:
                return False

    def create_video(self, subject: str, script: str = "",
                     aspect: str = "9:16", source: str = "pexels",
                     voice_name: str = "", clip_duration: int = 5,
                     count: int = 1, subtitle: bool = True,
                     bgm_type: str = "random", **extra) -> str:
        payload = {
            "video_subject": subject,
            "video_script": script,
            "video_aspect": aspect,
            "video_source": source,
            "video_clip_duration": clip_duration,
            "video_count": count,
            "subtitle_enabled": subtitle,
            "bgm_type": bgm_type,
            "n_threads": 2,
            **extra,
        }
        if voice_name:
            payload["voice_name"] = voice_name
        r = self.http.post("/api/v1/videos", json=payload)
        data = r.json()
        if r.status_code != 200 or data.get("code") != 200:
            raise MPTError(f"创建任务失败: {r.status_code} {data}")
        return data["data"]["task_id"]

    def task(self, task_id: str) -> dict:
        r = self.http.get(f"/api/v1/tasks/{task_id}")
        data = r.json()
        if r.status_code != 200 or data.get("code") != 200:
            raise MPTError(f"查询失败: {r.status_code} {data}")
        return data.get("data") or {}

    def wait(self, task_id: str, timeout: float = 3600, poll: float = 10) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            t = self.task(task_id)
            # state: 1=完成 0/进行中 -1=失败 (MPT 内部常量)
            if t.get("state") == 1:
                return t
            if t.get("state") == -1:
                raise MPTError(f"任务失败: {t}")
            time.sleep(poll)
        raise MPTError(f"任务 {task_id} 超时")

    def download(self, rel_path: str, dst: Path) -> Path:
        """rel_path 取 task 返回的 videos[0] 等相对路径"""
        for ep in ("/api/v1/download/", "/api/v1/stream/"):
            r = self.http.get(f"{ep}{rel_path}", follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 1000:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(r.content)
                return dst
        raise MPTError(f"下载失败: {rel_path}")
