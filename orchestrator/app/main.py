"""编排器 FastAPI 服务: 仪表盘 / 审核 / 任务提交 / 发布"""
import time
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import comfyui, config as C, mpt, publisher, scheduler, store

app = FastAPI(title="AI 传媒工作流编排器")


def auth(token: str = ""):
    if C.ORCH_TOKEN and token != C.ORCH_TOKEN:
        raise HTTPException(401, "bad token")


@app.on_event("startup")
def _startup():
    scheduler.start()


# ---------------- pages ----------------

TPL = Path(__file__).parent / "templates"


@app.get("/", response_class=HTMLResponse)
def index():
    return (TPL / "index.html").read_text(encoding="utf-8")


@app.get("/media/{item_id}")
def media_file(item_id: str):
    for d in (C.REVIEW_DIR, C.APPROVED_DIR, C.PUBLISHED_DIR, C.FAILED_DIR):
        for f in d.iterdir():
            if f.stem == item_id and f.suffix.lower() in store.MEDIA_EXT:
                return FileResponse(f)
    raise HTTPException(404)


# ---------------- status ----------------

@app.get("/api/health")
def health():
    return {
        "comfyui": {"url": C.COMFYUI_BASE_URL, "ok": comfyui.ComfyUI().health()},
        "minimax": {"configured": bool(C.MINIMAX_API_KEY)},
        "mpt": {"url": C.MPT_BASE_URL, "ok": mpt.MPT().health()},
        "sau": {"installed": publisher.sau_available()},
    }


# ---------------- review ----------------

@app.get("/api/review")
def review_list():
    return store.list_review()


class ApproveReq(BaseModel):
    title: str = ""
    desc: str = ""
    tags: list[str] = []
    platform: str = "douyin"
    schedule: str | None = None       # "YYYY-MM-DD HH:MM"
    publish_now: bool = False


@app.post("/api/review/{item_id}/approve")
def approve(item_id: str, req: ApproveReq):
    meta = store.move_item(item_id, C.REVIEW_DIR, C.APPROVED_DIR)
    pub = C.section("publish")
    meta.update({"title": req.title or meta.get("title"),
                 "desc": req.desc or meta.get("desc", ""),
                 "tags": req.tags or meta.get("tags") or [],
                 "platform": req.platform, "schedule": req.schedule})
    (C.APPROVED_DIR / f"{item_id}.json").write_text(
        __import__("json").dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"moved": "approved"}
    if req.publish_now or (pub.get("auto_after_approve") and pub.get("auto_schedule") == "now"):
        try:
            media = next(f for f in C.APPROVED_DIR.iterdir()
                         if f.stem == item_id and f.suffix.lower() in store.MEDIA_EXT)
            publisher.upload_video(media, title=meta["title"] or item_id,
                                   desc=meta["desc"], tags=meta["tags"],
                                   platform=req.platform, schedule=req.schedule)
            store.move_item(item_id, C.APPROVED_DIR, C.PUBLISHED_DIR)
            result["published"] = True
        except Exception as e:
            result["published"] = False
            result["error"] = str(e)
    return result


@app.post("/api/review/{item_id}/reject")
def reject(item_id: str):
    return store.move_item(item_id, C.REVIEW_DIR, C.FAILED_DIR)


@app.post("/api/approved/{item_id}/publish")
def publish_item(item_id: str, req: ApproveReq):
    media = next((f for f in C.APPROVED_DIR.iterdir()
                  if f.stem == item_id and f.suffix.lower() in store.MEDIA_EXT), None)
    if not media:
        raise HTTPException(404, "item not in approved queue")
    meta_file = C.APPROVED_DIR / f"{item_id}.json"
    meta = {}
    if meta_file.exists():
        import json
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    publisher.upload_video(
        media, title=req.title or meta.get("title") or item_id,
        desc=req.desc or meta.get("desc", ""),
        tags=req.tags or meta.get("tags") or [],
        platform=req.platform or meta.get("platform", "douyin"),
        schedule=req.schedule or meta.get("schedule"))
    store.move_item(item_id, C.APPROVED_DIR, C.PUBLISHED_DIR)
    return {"published": True}


@app.get("/api/approved")
def approved_list():
    return store.list_approved()


# ---------------- jobs ----------------

class DHReq(BaseModel):
    text: str
    character: str = "default"
    emotion: str | None = None
    look: str | None = None
    prompt: str | None = None
    title: str | None = None
    desc: str = ""
    tags: list[str] = []


class VTReq(BaseModel):
    source: str                      # 项目内相对路径或绝对路径
    prompt: str = ""
    face: str | None = None
    cloth: str | None = None
    background: str | None = None
    mask: str | None = None
    workflow: str | None = None
    title: str | None = None
    desc: str = ""
    tags: list[str] = []


class ACReq(BaseModel):
    subject: str
    script: str = ""
    title: str | None = None
    desc: str = ""
    tags: list[str] = []


def _resolve(p: str | None) -> Path | None:
    if not p:
        return None
    pp = Path(p)
    return pp if pp.is_absolute() else C.ROOT / pp


def _bg(bg: BackgroundTasks, fn, *a, **kw):
    bg.add_task(fn, *a, **kw)
    return {"queued": True}


@app.post("/api/jobs/digital-human")
def job_dh(req: DHReq, bg: BackgroundTasks):
    from pipelines.digital_human import pipeline
    jid = store.job_create("digital_human", req.model_dump())
    return _bg(bg, lambda: _run_guarded(
        jid, pipeline.run, req.text, character=req.character,
        emotion=req.emotion, look=req.look, prompt=req.prompt,
        title=req.title, desc=req.desc, tags=req.tags, jid=jid))


@app.post("/api/jobs/video-transform")
def job_vt(req: VTReq, bg: BackgroundTasks):
    from pipelines.video_transform import pipeline
    jid = store.job_create("video_transform", req.model_dump())
    return _bg(bg, lambda: _run_guarded(
        jid, pipeline.run, _resolve(req.source), prompt=req.prompt,
        face=_resolve(req.face), cloth=_resolve(req.cloth),
        background=_resolve(req.background), mask=_resolve(req.mask),
        workflow=req.workflow, title=req.title, desc=req.desc,
        tags=req.tags, jid=jid))


@app.post("/api/jobs/auto-content")
def job_ac(req: ACReq, bg: BackgroundTasks):
    from pipelines.auto_content import pipeline
    jid = store.job_create("auto_content", req.model_dump())
    return _bg(bg, lambda: _run_guarded(
        jid, pipeline.run, req.subject, script=req.script,
        title=req.title, desc=req.desc, tags=req.tags, jid=jid))


def _run_guarded(job_id, fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        store.job_finish(job_id, "error", {"error": str(e)})


@app.get("/api/jobs")
def jobs():
    return store.job_list()


@app.get("/api/workflows/{name}/inspect")
def wf_inspect(name: str):
    try:
        return comfyui.inspect_workflow(name)
    except Exception as e:
        raise HTTPException(400, str(e))
