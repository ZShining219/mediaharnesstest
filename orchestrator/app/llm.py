"""LLM 客户端: DeepSeek (OpenAI 兼容) — 文案/提示词/脚本生成。

.env:
    LLM_API_KEY=sk-...
    LLM_BASE_URL=https://api.deepseek.com
    LLM_MODEL=deepseek-v4-flash
"""
import httpx

from . import config as C


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None):
        self.key = api_key or C.env("LLM_API_KEY")
        if not self.key:
            raise LLMError("缺少 LLM_API_KEY, 请在 .env 中配置")
        self.base = (base_url or C.env("LLM_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or C.env("LLM_MODEL", "deepseek-v4-flash")
        self.http = httpx.Client(
            base_url=self.base, timeout=float(C.env("LLM_TIMEOUT_SECONDS", "60")),
            headers={"Authorization": f"Bearer {self.key}"})

    def chat(self, user: str, system: str | None = None,
             max_tokens: int = 2000, temperature: float = 0.7) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": user})
        try:
            r = self.http.post("/chat/completions", json={
                "model": self.model, "messages": msgs,
                "max_tokens": max_tokens, "temperature": temperature,
            })
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
        text = ((choice.get("message") or {}).get("content") or "").strip()
        if not text:
            raise LLMError(f"LLM 返回空内容: {str(data)[:300]}")
        return text
