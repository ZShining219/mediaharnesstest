"""LLM 客户端: DeepSeek (OpenAI 兼容) — 文案/提示词/脚本生成。

.env:
    LLM_API_KEY=sk-...
    LLM_BASE_URL=https://api.deepseek.com
    LLM_MODEL=deepseek-v4-flash
"""
import base64
import mimetypes
from pathlib import Path

import httpx

from . import config as C


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: float | None = None):
        self.key = api_key or C.env("LLM_API_KEY")
        if not self.key:
            raise LLMError("缺少 LLM_API_KEY, 请在 .env 中配置")
        self.base = (base_url or C.env("LLM_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or C.env("LLM_MODEL", "deepseek-v4-flash")
        self.http = httpx.Client(
            base_url=self.base,
            timeout=float(timeout or C.env("LLM_TIMEOUT_SECONDS", "60")),
            headers={"Authorization": f"Bearer {self.key}"})

    def _post(self, payload: dict) -> str:
        try:
            r = self.http.post("/chat/completions", json=payload)
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 请求失败: {e}") from e
        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
            raise
        if r.status_code >= 400:
            raise LLMError(f"LLM HTTP{r.status_code}: {str(data)[:300]}")
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = (msg.get("content") or "").strip()
        # DeepSeek 偶尔把内容全放进 reasoning_content，content 为空；
        # JSON 模式下优先用 content，空时退回 reasoning 再交给 _extract_json。
        if not text:
            text = (msg.get("reasoning_content") or "").strip()
        if not text:
            raise LLMError(f"LLM 返回空内容: {str(data)[:300]}")
        return text

    def chat(self, user: str, system: str | None = None,
             max_tokens: int = 2000, temperature: float = 0.7,
             json_mode: bool = False) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": user})
        payload = {
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._post(payload)

    @staticmethod
    def image_block(path) -> dict:
        p = Path(path)
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        b64 = base64.b64encode(p.read_bytes()).decode()
        return {"type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}}

    def chat_vision(self, user: str, images, system: str | None = None,
                    max_tokens: int = 6000, temperature: float = 0.2,
                    json_mode: bool = True) -> str:
        """多图视觉理解。images 为本地图片路径列表，按顺序对应提示词里的图号。"""
        content: list[dict] = [{"type": "text", "text": user}]
        for im in images:
            content.append(self.image_block(im))
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": content})
        payload = {
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._post(payload)
