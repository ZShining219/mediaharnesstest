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


def job_finish(jid: str, status: str, result: dict, *, force: bool = False) -> bool:
    """写终态, 默认只允许 running -> 终态。

    管线自己已经把结果写成 unknown/error/done(含 provider_task 等找回线索)后
    会 re-raise, 上层兜底若再次 job_finish 会把这些线索覆盖掉 —— 因此这里默认
    拒绝二次终态写入, 返回是否真正写入。需要强制覆盖时传 force=True。
    """
    with _conn() as c:
        row = c.execute("SELECT result FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            return False
        # 与已有结果合并: 运行中写入的 provider_task / provider_via 等
        # 找回线索不能因为最终态回写而丢失
        merged = {**json.loads(row[0] or "{}"), **(result or {})}
        if status == "done":          # 成功终态不保留上一轮失败/取回痕迹
            for k in ("error", "recover_error", "recovering"):
                merged.pop(k, None)
        sql = "UPDATE jobs SET status=?, result=?, updated_at=? WHERE id=?"
        args = [status, json.dumps(merged, ensure_ascii=False), time.time(), jid]
        if not force:
            sql += " AND status='running'"
        return c.execute(sql, args).rowcount > 0


def job_get(jid: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id,type,status,params,result,created_at,updated_at "
            "FROM jobs WHERE id=?", (jid,),
        ).fetchone()
    if not row:
        return None
    return dict(id=row[0], type=row[1], status=row[2],
                params=json.loads(row[3] or "{}"),
                result=json.loads(row[4] or "{}"),
                created_at=row[5], updated_at=row[6])


def job_result(jid: str) -> dict:
    return (job_get(jid) or {}).get("result") or {}


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


def job_mark_interrupted() -> int:
    """启动时调用: 上次进程退出遗留的 running 任务标记为 interrupted"""
    with _conn() as c:
        cur = c.execute(
            "UPDATE jobs SET status='interrupted', updated_at=? WHERE status='running'",
            (time.time(),),
        )
        return cur.rowcount


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
    """把成品 + sidecar 元数据放入待审核队列(同名自动加后缀防覆盖)"""
    dst = C.REVIEW_DIR / media.name
    if media.resolve() != dst.resolve():
        if dst.exists():
            dst = C.REVIEW_DIR / f"{media.stem}_{uuid.uuid4().hex[:6]}{media.suffix}"
        shutil.move(str(media), dst)
    item_id = dst.stem
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
