"""轻量任务记录 (sqlite) + 审核队列(文件系统 + sidecar json)"""
import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from . import config as C

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
MEDIA_EXT = VIDEO_EXT | {".png", ".jpg", ".jpeg", ".webp"}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(C.DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY, type TEXT, status TEXT, params TEXT,
        result TEXT, created_at REAL, updated_at REAL)"""
    )
    return conn


def job_create(jtype: str, params: dict) -> str:
    jid = f"{jtype}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    with _conn() as c:
        c.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
            (jid, jtype, "running", json.dumps(params, ensure_ascii=False), "", time.time(), time.time()),
        )
    return jid


def job_finish(jid: str, status: str, result: dict):
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET status=?, result=?, updated_at=? WHERE id=?",
            (status, json.dumps(result, ensure_ascii=False), time.time(), jid),
        )


def job_update(jid: str, result: dict | None = None, status: str | None = None):
    """运行中回写部分状态(节点进度等); 与 job_finish 并存"""
    with _conn() as c:
        row = c.execute("SELECT result FROM jobs WHERE id=?", (jid,)).fetchone()
        merged = {**json.loads(row[0] or "{}"), **(result or {})}
        if status:
            c.execute("UPDATE jobs SET status=?, result=?, updated_at=? WHERE id=?",
                      (status, json.dumps(merged, ensure_ascii=False), time.time(), jid))
        else:
            c.execute("UPDATE jobs SET result=?, updated_at=? WHERE id=?",
                      (json.dumps(merged, ensure_ascii=False), time.time(), jid))


def job_list(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,type,status,params,result,created_at,updated_at FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        dict(id=r[0], type=r[1], status=r[2], params=json.loads(r[3] or "{}"),
             result=json.loads(r[4] or "{}"), created_at=r[5], updated_at=r[6])
        for r in rows
    ]


# ---------------- review items ----------------

def add_review_item(media: Path, pipeline: str, meta: dict) -> Path:
    """把成品 + sidecar 元数据放入待审核队列"""
    item_id = media.stem
    dst = C.REVIEW_DIR / media.name
    if media.resolve() != dst.resolve():
        shutil.move(str(media), dst)
    meta = {"id": item_id, "pipeline": pipeline, "status": "pending",
            "created_at": time.time(), **meta}
    (C.REVIEW_DIR / f"{item_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def _items_in(d: Path) -> list[dict]:
    items = []
    for f in sorted(d.iterdir()):
        if f.suffix.lower() not in MEDIA_EXT:
            continue
        side = f.with_suffix(".json")
        meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
        meta.setdefault("id", f.stem)
        meta["file"] = f.name
        meta["is_video"] = f.suffix.lower() in VIDEO_EXT
        meta["path"] = str(f)
        items.append(meta)
    return items


def list_review() -> list[dict]:
    return _items_in(C.REVIEW_DIR)


def list_approved() -> list[dict]:
    return _items_in(C.APPROVED_DIR)


def review_media_url(item_id: str, base: str = "/media") -> str:
    return f"{base}/{item_id}"


def move_item(item_id: str, src: Path, dst_dir: Path) -> dict:
    media = next((f for f in src.iterdir()
                  if f.stem == item_id and f.suffix.lower() in MEDIA_EXT), None)
    side = src / f"{item_id}.json"
    meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    if media:
        shutil.move(str(media), dst_dir / media.name)
    meta["status"] = dst_dir.name
    meta["updated_at"] = time.time()
    (dst_dir / f"{item_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if side.exists():
        side.unlink()
    return meta
