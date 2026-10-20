"""固定参考视频池: 人工维护的参考/对标视频集合。

与每日备料池(data/material_pool.json)分开:
- material_pool: 自动采集的候选/备料, 有去重/评分语义
- reference_pool: 人工确认的固定参考, 供后续结构分析/爆款追踪使用

只维护池记录; 删除条目不删除 assets/ 下的原视频文件。
"""
import json
import re
import time
import uuid
from pathlib import Path

from . import config as C

POOL_FILE = C.ROOT / "data" / "reference_pool.json"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _load() -> list[dict]:
    if not POOL_FILE.exists():
        return []
    try:
        data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict]):
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _path(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else C.ROOT / p


def _rel(p: Path) -> str:
    return str(p.resolve().relative_to(C.ROOT.resolve()))


def _in_assets(p: Path) -> bool:
    try:
        p.resolve().relative_to(C.ASSETS.resolve())
        return True
    except ValueError:
        return False


def _duration(p: Path) -> float | None:
    try:
        from . import media
        d = media.ffprobe_duration(p)
        return round(float(d), 2) if d else None
    except Exception:
        return None


def _tags(v) -> list[str]:
    if isinstance(v, str):
        v = re.split(r"[,，、;；\s]+", v)
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip() for x in v if str(x).strip()][:12]


def list_items() -> list[dict]:
    items = _load()
    items.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    out = []
    for it in items:
        p = _path(it.get("path") or "")
        out.append({
            **it,
            "exists": p.is_file(),
            "filename": p.name,
            "size": p.stat().st_size if p.is_file() else None,
        })
    return out


def add(path: str | None = None, url: str | None = None,
        title: str | None = None, note: str = "",
        tags=None, source_url: str | None = None) -> dict:
    """加入参考池。path 与 url 至少一个; url 会先下载到 assets/sources/。"""
    if not path and url:
        from . import materials
        path = materials.download(url, "source", title or None)
    if not path:
        raise ValueError("需要视频路径或链接")

    p = _path(path)
    if not p.is_file():
        raise ValueError(f"视频不存在: {path}")
    if not _in_assets(p):
        raise ValueError("参考视频必须位于 assets/ 目录下")
    if p.suffix.lower() not in VIDEO_EXT:
        raise ValueError(f"不支持的视频类型: {p.suffix}")

    rel = _rel(p)
    items = _load()
    # 同一路径视为同一条, 更新元数据而不是重复添加
    for it in items:
        if it.get("path") == rel:
            it["title"] = (title or it.get("title") or p.stem).strip()
            it["note"] = note.strip() if note else it.get("note", "")
            it["tags"] = _tags(tags) if tags else it.get("tags", [])
            if source_url:
                it["source_url"] = source_url
            _save(items)
            return it

    item = {
        "id": f"ref-{int(time.time())}-{uuid.uuid4().hex[:4]}",
        "path": rel,
        "title": (title or p.stem).strip(),
        "note": (note or "").strip(),
        "tags": _tags(tags),
        "source_url": (source_url or url or "").strip(),
        "duration": _duration(p),
        "created_at": int(time.time()),
    }
    items.insert(0, item)
    _save(items)
    return item


def delete(item_id: str) -> dict:
    """只删除池记录, 保留原视频文件。"""
    items = _load()
    for i, it in enumerate(items):
        if it.get("id") == item_id:
            removed = items.pop(i)
            _save(items)
            return {"deleted": item_id, "path": removed.get("path")}
    raise KeyError(f"参考池记录不存在: {item_id}")
