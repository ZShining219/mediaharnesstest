"""MiniMax API 客户端。

两条线路（.env 配置）：
- 视频生成 MiniMax-H3: 默认走秘塔代理 MINIMAX_BASE_URL + MINIMAX_API_KEY (mk- key)
    新版多模态接口: POST {base}/video_generation  body.content = 多模态数组
    轮询: GET {base}/query/video_generation/{task_id}  (task.status/content.url)
- 语音 TTS / 声音克隆: 走官方站 MINIMAX_API_KEY_OFFICIAL + MINIMAX_BASE_URL_OFFICIAL
    (秘塔代理只代理视频接口; 官方 v1 接口如需 GroupId 请配置 MINIMAX_GROUP_ID,
     v2 视频接口不需要 — 实测空 GroupId 会触发官方 401)

通道纪律(对齐 EOS 生产链路): 提交不重试 — 传输中断标 SubmitAmbiguous(远端
可能已建任务, 重发=重复扣费); 轮询只重试传输错误与 5xx, 连续断连标 PollPaused。

文档: https://platform.minimaxi.com/docs/api-reference (官方)
     https://metaso.cn/minimax-h3 (秘塔代理说明)
"""
import atexit
import base64
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx

from . import config as C


class MinimaxError(RuntimeError):
    pass


class SubmitAmbiguous(MinimaxError):
    """提交请求传输中断: 远端可能已创建任务, 不得自动重试/换通道"""


class PollPaused(MinimaxError):
    """轮询暂停(连续断连/超时): 任务可能仍在生成, 可按 task_id 找回"""


class DownloadFailed(MinimaxError):
    """服务商任务已完成, 但产物下载失败: 已扣费, 必须按 task_id 取回,
    不能当成普通生成失败让用户直接重发"""


def is_ambiguous_error(exc: BaseException) -> bool:
    """异常链里是否含有"远端可能已建/已完成, 本地只是没拿到"的语义。
    管线 re-raise 后上层兜底/任务状态判定统一用这个判断, 避免误标 error。"""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (SubmitAmbiguous, PollPaused, DownloadFailed)):
            return True
        exc = exc.__cause__
    return False


_SIDECAR_LOCK = threading.Lock()
_SIDECAR_PROC: subprocess.Popen | None = None
_SIDECAR_DEFAULT_URL = "http://127.0.0.1:8791"


def _sidecar_base() -> str:
    return C.MINIMAX_BASE_URL.rstrip("/")


def _sidecar_key_sha() -> str:
    return hashlib.sha256((C.MINIMAX_API_KEY or "").encode()).hexdigest()[:8]


def _node_bin() -> str | None:
    explicit = C.env("NODE_BIN", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("node")
    if found:
        return found
    nvm = Path.home() / ".nvm" / "versions" / "node"
    if nvm.exists():
        for p in sorted(nvm.glob("*/bin/node"), reverse=True):
            if p.exists():
                return str(p)
    for p in ("/opt/homebrew/bin/node", "/usr/local/bin/node"):
        if Path(p).exists():
            return p
    return None


def _sidecar_health(url: str) -> dict | None:
    try:
        data = httpx.get(f"{url}/health", timeout=1.5,
                         trust_env=False).json()
        return data if data.get("service") == "aimf-metaso-submit" else None
    except Exception:
        return None


def _stop_sidecar():
    proc = _SIDECAR_PROC
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


atexit.register(_stop_sidecar)


def _ensure_sidecar() -> str | None:
    """返回可用的 Node sidecar URL; Node/脚本不可用时返回 None(回退 httpx)。"""
    global _SIDECAR_PROC
    url = C.env("METASO_SIDECAR_URL", _SIDECAR_DEFAULT_URL).rstrip("/")
    want_base, want_key = _sidecar_base(), _sidecar_key_sha()
    health = _sidecar_health(url)
    if health and health.get("base") == want_base and health.get("key_sha") == want_key:
        return url
    with _SIDECAR_LOCK:
        health = _sidecar_health(url)
        if health and health.get("base") == want_base and health.get("key_sha") == want_key:
            return url
        # 端口上是旧配置的 sidecar: 先停掉再拉起
        if health:
            pid = health.get("pid")
            if isinstance(pid, int) and pid > 1:
                try:
                    os.kill(pid, 15)
                except Exception:
                    pass
                time.sleep(0.4)
        node = _node_bin()
        script = C.ROOT / "scripts" / "metaso_submit.mjs"
        if not node or not script.exists():
            return None
        from urllib.parse import urlparse
        env = os.environ.copy()
        env["METASO_SIDECAR_PORT"] = str(urlparse(url).port or 8791)
        log_path = C.ROOT / "logs" / "metaso_sidecar.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log:
            _SIDECAR_PROC = subprocess.Popen(
                [node, str(script), "--serve"],
                cwd=str(C.ROOT), env=env,
                stdout=log, stderr=log, start_new_session=True)
        for _ in range(30):
            time.sleep(0.2)
            health = _sidecar_health(url)
            if health and health.get("base") == want_base and health.get("key_sha") == want_key:
                return url
            if _SIDECAR_PROC.poll() is not None:
                break
        return None


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
        self._warmed = False
        gid = C.MINIMAX_GROUP_ID if group_id == "" else group_id
        # GroupId 只在配了真实值时才带: 实测官方接口对空 GroupId 返回 401,
        # 而 video_generation 系列本就不需要该参数 (EOS 项目生产验证)
        self.http = httpx.Client(
            base_url=self.base, timeout=120,
            # 关键: macOS 系统代理(127.0.0.1:8118)会被 httpx/urllib 自动读取，
            # 而 Node fetch 默认直连。秘塔提交走代理会间歇性被断开/返回 HTML；
            # trust_env=False 让 httpx 也直连，对齐 EOS 的 Node fetch。
            trust_env=False,
            headers={
                "Authorization": f"Bearer {self.key}",
                # 对齐 EOS 的 Node fetch UA
                "User-Agent": C.env("MINIMAX_USER_AGENT", "node"),
            },
            params={"GroupId": gid} if gid else {},
        )

    @classmethod
    def official(cls) -> "Minimax":
        """官方站实例 (TTS/声音克隆/官方视频计费)"""
        key = C.env("MINIMAX_API_KEY_OFFICIAL") or C.MINIMAX_API_KEY
        base = C.env("MINIMAX_BASE_URL_OFFICIAL", "https://api.minimax.cn/v2").rstrip("/")
        if not base.endswith(("/v1", "/v2")):
            base += "/v2"          # 视频/TTS 接口都在 /v1|/v2 之下, 裸域名兜底补 /v2
        return cls(api_key=key, base_url=base)

    @classmethod
    def video_client(cls, via: str) -> "Minimax":
        """视频生成实例: official=官方直连(api.minimax.cn, 需 GroupId+H3按量);
        metaso=秘塔代理(mk- key)"""
        return cls.official() if via == "official" else cls()

    @property
    def via(self) -> str:
        return "metaso" if "metaso" in self.base else "official"

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
                       idempotency_key: str | None = None,
                       **extra) -> str:
        """提交视频任务, 返回 task_id。
        content: 多模态数组 [{type:text|image_url|video_url|audio_url,...}],
                 传 str 时自动包成纯文本提示。
        idempotency_key: 同一镜头重试时保持不变, 便于代理侧去重。"""
        if isinstance(content, str):
            content = [self.part_text(content)]
        self._warmup()
        body = {"model": model, "content": content, "resolution": resolution,
                "aigc_watermark": aigc_watermark, **extra}
        if duration:
            body["duration"] = int(duration)
        if ratio:
            body["ratio"] = ratio
        # 官方限制序列化 JSON ≤64MB (base64 内联约膨胀 4/3)
        body_bytes = len(json.dumps(body, ensure_ascii=False).encode())
        if body_bytes > 64 * 1024 * 1024:
            raise MinimaxError(f"请求体 {body_bytes >> 20}MB 超过 64MB 上限, 请改用更小素材")
        # 秘塔提交对齐 EOS: 优先走 Node sidecar(全局 fetch/undici),
        # 不可用时回退 httpx。官方通道继续走 httpx。
        if (self.via == "metaso"
                and self.base == C.MINIMAX_BASE_URL.rstrip("/")
                and self.key == C.MINIMAX_API_KEY):
            tid = self._submit_via_sidecar(body, idempotency_key)
            if tid:
                return tid
        # 底层提交不自动重试; 需要容错时用 video_generate_safe():
        # 它先核对任务列表, 确认没建任务后再用同一个 idempotency_key 重发。
        try:
            data = self._post(
                "/video_generation", body,
                headers={"Idempotency-Key": idempotency_key}
                if idempotency_key else None)
        except httpx.RequestError as e:
            raise SubmitAmbiguous(
                f"提交视频任务连接中断({e}); {self.via} 侧可能已创建任务, "
                f"请到后台核对后再决定是否重发/取回, 避免重复扣费") from e
        tid = data.get("task_id") or (data.get("task") or {}).get("task_id")
        if not tid:
            raise MinimaxError(f"未返回 task_id: {json.dumps(data, ensure_ascii=False)[:400]}")
        return tid

    def _submit_via_sidecar(self, body: dict,
                            idempotency_key: str | None) -> str | None:
        """把提交交给本机 Node sidecar; 返回 None 表示 sidecar 不可用, 回退 httpx。"""
        url = _ensure_sidecar()
        if not url:
            return None
        try:
            r = httpx.post(
                f"{url}/submit",
                json={"body": body, "idempotency_key": idempotency_key},
                timeout=120, trust_env=False)
            data = r.json()
        except Exception as e:
            # 本地 sidecar 调用失败时无法确认它是否已转发, 不能直接改走 httpx 重发
            raise SubmitAmbiguous(
                f"Node sidecar 调用失败({e}); 无法确认秘塔侧是否已提交") from e
        if data.get("network"):
            raise SubmitAmbiguous(
                f"Node sidecar 提交连接中断({data.get('error')}); "
                "秘塔侧可能已创建任务, 请到后台核对后再决定是否重发/取回, 避免重复扣费")
        status = int(data.get("status") or 0)
        text = data.get("text") or ""
        try:
            payload = json.loads(text) if text else {}
        except Exception:
            payload = {"raw": text[:400]}
        self._check_payload(status, payload)
        tid = payload.get("task_id") or (payload.get("task") or {}).get("task_id")
        if not tid:
            raise MinimaxError(f"未返回 task_id: {text[:400]}")
        return tid

    def _warmup(self):
        """秘塔代理前有 Alibaba WAF: 先 GET 一次拿 aliyungf_tc/JSESSIONID,
        再 POST 大请求, 降低冷连接被直接断开(RemoteProtocolError)的概率。"""
        if getattr(self, "_warmed", False):
            return
        try:
            self.http.get("/query/video_generation", timeout=15)
        except Exception:
            pass
        self._warmed = True

    def list_video_tasks(self) -> list[dict]:
        """代理侧最近任务列表; 用于 Submission 断连后的安全找回。"""
        data = self._check(self.http.get("/query/video_generation"))
        return data.get("items") or []

    def _find_task_since(self, start_ts: float, duration, resolution,
                         ratio, image_count: int) -> str | None:
        try:
            tasks = self.list_video_tasks()
        except Exception:
            return None
        want_duration = None
        if duration is not None:
            try:
                want_duration = int(duration)
            except (TypeError, ValueError):
                want_duration = None
        found = []
        for t in tasks:
            created = t.get("created_at") or 0
            if created < start_ts - 3:
                continue
            if want_duration is not None and int(t.get("duration") or 0) != want_duration:
                continue
            if resolution and t.get("resolution") != resolution:
                continue
            if ratio and t.get("ratio") != ratio:
                continue
            usage = t.get("usage") or {}
            if (image_count
                    and usage.get("input_image_count") not in (None, image_count)):
                continue
            found.append(t)
        if not found:
            return None
        return max(found, key=lambda t: t.get("created_at") or 0).get("id")

    def video_generate_safe(self, content: list[dict] | str, *,
                            model: str = "MiniMax-H3", resolution: str = "768P",
                            duration: int | None = None, ratio: str | None = None,
                            idempotency_key: str | None = None,
                            retries: int = 3, **extra) -> str:
        """提交 + 断连安全找回。

        每次 SubmitAmbiguous 后先查任务列表:
        - 找到同参数、同图片数、created_at 在本次提交之后的任务 -> 直接复用 task_id;
        - 没找到 -> 用同一个 idempotency_key 冷却后重发。
        这样既避免重复扣费, 也不会让一次 TLS 抖动打断整条视频。
        """
        items = [self.part_text(content)] if isinstance(content, str) else content
        image_count = sum(
            1 for c in items
            if isinstance(c, dict) and c.get("type") == "image_url")
        key = idempotency_key or f"h3-{uuid.uuid4().hex}"
        start_ts = time.time()
        last: SubmitAmbiguous | None = None
        for attempt in range(retries):
            try:
                return self.video_generate(
                    items, model=model, resolution=resolution, duration=duration,
                    ratio=ratio, idempotency_key=key, **extra)
            except SubmitAmbiguous as e:
                last = e
                # 连接断了但任务可能已在远端创建: 轮询任务列表几秒
                for _ in range(4):
                    time.sleep(2)
                    tid = self._find_task_since(
                        start_ts, duration, resolution, ratio, image_count)
                    if tid:
                        return tid
                if attempt + 1 < retries:
                    time.sleep(5 * (attempt + 1))
        assert last is not None
        raise last

    def video_query(self, task_id: str) -> dict:
        """返回 task dict: {status, content:{url}, usage, base_resp, error}"""
        data = self._check(self.http.get(f"/query/video_generation/{task_id}"))
        return data.get("task") or data

    def video_wait(self, task_id: str, timeout: float = 1800,
                   poll: float = 8) -> dict:
        """轮询直到完成, 返回 task dict (含 content.url 与 usage)。
        网络抖动(断连/超时)重试不判死; 服务端真实失败(failed)立即抛错。"""
        deadline = time.time() + timeout
        fails = 0
        while time.time() < deadline:
            try:
                task = self.video_query(task_id)
            except MinimaxError as e:
                # 业务错误按 EOS 白名单: 仅 5xx 可重试, 4xx 直接抛出
                st = getattr(e.__cause__, "status", 0)
                if st and st < 500:
                    raise
                fails += 1
                if fails > 10:
                    raise PollPaused(
                        f"视频任务 {task_id} 轮询连续断连({e}); "
                        f"{self.via} 侧任务可能仍在生成, 可按 task_id 找回") from e
                time.sleep(poll)
                continue
            except httpx.RequestError as e:
                fails += 1
                if fails > 10:
                    raise PollPaused(
                        f"视频任务 {task_id} 轮询连续断连({e}); "
                        f"{self.via} 侧任务可能仍在生成, 可按 task_id 找回") from e
                time.sleep(poll)
                continue
            fails = 0
            status = str(task.get("status") or "").lower()
            if status in ("succeeded", "success"):
                return task
            if status in ("failed", "fail", "cancelled", "canceled"):
                msg = ((task.get("error") or {}).get("message")
                       or (task.get("base_resp") or {}).get("status_msg")
                       or json.dumps(task, ensure_ascii=False)[:300])
                raise MinimaxError(f"视频生成失败: {msg}")
            time.sleep(poll)
        raise PollPaused(
            f"视频任务 {task_id} 查询超时({self.via} 侧可能仍在生成, 可按 task_id 找回)")

    def video_url(self, task: dict) -> str:
        url = (task.get("content") or {}).get("url") or task.get("url")
        if not url:
            raise MinimaxError(f"任务完成但无视频地址: {json.dumps(task, ensure_ascii=False)[:300]}")
        return url

    @staticmethod
    def download(url: str, dst: Path, retries: int = 6) -> Path:
        """下载产物。传输断连/5xx 自动重试(下载幂等), 4xx 立即放弃。
        失败时删掉半成品, 避免残缺文件被当成成品; 最终抛 DownloadFailed,
        语义是"任务已完成、钱已花, 结果还在服务商那里可找回"。"""
        dst.parent.mkdir(parents=True, exist_ok=True)
        last: Exception | None = None
        for i in range(retries):
            try:
                with httpx.stream("GET", url,
                                  timeout=httpx.Timeout(300, connect=20),
                                  follow_redirects=True,
                                  trust_env=False) as r:
                    r.raise_for_status()
                    with open(dst, "wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                return dst
            except httpx.HTTPStatusError as e:
                last = e
                dst.unlink(missing_ok=True)
                if e.response.status_code < 500:   # 地址失效等, 重试无意义
                    raise DownloadFailed(
                        f"产物下载失败 HTTP {e.response.status_code}: "
                        f"{url[:160]}") from e
            except httpx.TransportError as e:
                last = e
                dst.unlink(missing_ok=True)
            if i + 1 < retries:
                time.sleep(2 * (i + 1))
        raise DownloadFailed(
            f"视频任务已完成但产物下载失败({last}); 可按 task_id 重新取回: "
            f"{url[:160]}") from last

    def video_wait_download(self, task_id: str, dst: Path,
                            timeout: float = 1800) -> dict:
        """等待 + 下载, 返回 task dict (含 usage)。
        下载失败时重查一次任务以刷新可能过期的产物 URL, 再试一轮。"""
        task = self.video_wait(task_id, timeout=timeout)
        try:
            self.download(self.video_url(task), dst)
        except DownloadFailed as first:
            try:                       # 产物 URL 可能过期: 重查拿新地址再试
                task = self.video_query(task_id)
            except httpx.RequestError as e:
                raise DownloadFailed(f"{first}; 重新获取产物地址失败({e})") from e
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

    # ---------------- 文生图/图生图 (官方站 image_generation) ----------------

    def gen_images(self, prompt: str, subject: list[dict] | None = None,
                   aspect_ratio: str = "3:4", n: int = 1,
                   model: str = "image-01") -> list[str]:
        """T2I/I2I: subject=[{"type":"character","image_file":url|dataURI}] 固定人物参考。
        返回 base64 图列表。秘塔代理无此接口, 走官方站。"""
        client = self if "metaso" not in self.base else Minimax.official()
        payload = {"model": model, "prompt": prompt, "n": max(1, min(9, n)),
                   "aspect_ratio": aspect_ratio, "response_format": "base64"}
        if subject:
            payload["subject_reference"] = subject
        data = client._check(client.http.post(client._v1("/image_generation"),
                                              json=payload))
        d = data.get("data") or {}
        return d.get("image_base64") or d.get("image_urls") or []

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

    def _post(self, path: str, payload: dict,
              headers: dict | None = None) -> dict:
        # path 可为绝对路径(http...)或相对 base 的路径
        return self._check(self.http.post(path, json=payload, headers=headers))

    @staticmethod
    def _check_payload(status: int, data: dict) -> dict:
        br = data.get("base_resp") or {}
        err = data.get("error") or {}
        if (status >= 400 or (br.get("status_code") not in (None, 0))
                or (data.get("type") == "error" and err)):
            raise MinimaxError(
                f"HTTP {status} base_resp={br} error={err} "
                f"body={json.dumps(data, ensure_ascii=False)[:400]}",
                ) from _StatusHint(status)
        return data

    @staticmethod
    def _check(r: httpx.Response) -> dict:
        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
            raise
        return Minimax._check_payload(r.status_code, data)


class _StatusHint(Exception):
    """挂到 MinimaxError.__cause__ 上携带 HTTP 状态, 供重试白名单判断"""

    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def video_via_order() -> list[str]:
    """视频提交通道(仅列出配了 key 的通道)。
    MINIMAX_VIDEO_VIA=metaso   → 只用秘塔代理, 失败不回退官方
                     official → 只用官方直连
                     auto(默认) → 秘塔优先, 官方兜底
    官方站 key 仍保留给 TTS/声音克隆, 与视频通道无关。"""
    pref = C.env("MINIMAX_VIDEO_VIA", "auto").lower()
    has_off = bool(C.env("MINIMAX_API_KEY_OFFICIAL"))
    has_mk = bool(C.MINIMAX_API_KEY)
    order = {"metaso": ["metaso"],
             "official": ["official"],
             "auto": ["metaso", "official"]}.get(pref, ["metaso", "official"])
    avail = [v for v in order
             if (v == "official" and has_off) or (v == "metaso" and has_mk)]
    if not avail:
        raise MinimaxError(
            f"MINIMAX_VIDEO_VIA={pref} 但对应通道没有配置 key "
            f"(metaso 需 MINIMAX_API_KEY, official 需 MINIMAX_API_KEY_OFFICIAL)")
    return avail
