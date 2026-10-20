"""LLM 输出里的 JSON 提取：兼容 markdown 包裹、前后解释、尾逗号。"""
import json
import re


def extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    matches = re.findall(r"\{.*\}", text, re.S)
    for raw in sorted(matches, key=len, reverse=True):
        for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
    return None
