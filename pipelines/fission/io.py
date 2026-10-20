"""Fission 链路 IO：信封、JSON 读写、轻量校验。"""
from __future__ import annotations

import json
import time
from pathlib import Path


def load_json(path: Path | str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: Path | str, data) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def envelope(type_: str, version: str, id_: str, producer: str,
             payload: dict, refs: list | None = None,
             provenance: dict | None = None) -> dict:
    return {
        "type": type_,
        "version": version,
        "id": id_,
        "created_at": int(time.time()),
        "producer": producer,
        "payload": payload,
        "refs": refs or [],
        "provenance": provenance or {},
    }


def validate_envelope(env: dict, type_: str | None = None) -> list[str]:
    errors = []
    if not isinstance(env, dict):
        return ["envelope 不是对象"]
    for k in ("type", "version", "id", "payload"):
        if not env.get(k):
            errors.append(f"缺少 {k}")
    if type_ and env.get("type") != type_:
        errors.append(f"type={env.get('type')}，期望 {type_}")
    if not isinstance(env.get("payload"), dict):
        errors.append("payload 不是对象")
    return errors
