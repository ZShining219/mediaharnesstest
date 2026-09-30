"""编排器 FastAPI 服务: 仪表盘 / 审核 / 任务提交 / 发布 / 素材管理"""
import json
import shutil
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import comfyui, config as C, mpt, nodegraph, nodedefs, publisher, scheduler, store

app = FastAPI(title="AI 传媒工作流编排器")


@app.middleware("http")
async def token_guard(request, call_next):
    """ORCH_TOKEN 设置后: /api 与 /media 需带 token (?token= 或 X-Token 头)"""
    if C.ORCH_TOKEN and (request.url.path.startswith("/api")
                         or request.url.path.startswith("/media")):
        tok = (request.query_params.get("token")
               or request.headers.get("x-token")
               or request.cookies.get("orch_token"))
        if tok != C.ORCH_TOKEN:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.on_event("startup")
def _startup():
    scheduler.start()


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


# ---------------- pages ----------------

TPL = Path(__file__).parent / "templates"


@app.get("/", response_class=HTMLResponse)
def index():
    return (TPL / "index.html").read_text(encoding="utf-8")


@app.get("/api/config/public")
def public_cfg():
    """前端需要的非敏感配置(素材管理器免密链接等)"""
    return {"assets_pw": C.env("ASSETS_PW", "")}


@app.get("/media/{item_id}")
def media_file(item_id: str):
    for d in (C.REVIEW_DIR, C.APPROVED_DIR, C.PUBLISHED_DIR, C.FAILED_DIR):
        for f in d.iterdir():
            if f.stem == item_id and f.suffix.lower() in store.MEDIA_EXT:
                return FileResponse(f)
    raise HTTPException(404)


# ---------------- 素材/角色管理 ----------------

ASSET_KINDS = {
    "source": C.ASSETS / "sources",      # 对标视频
    "garment": C.ASSETS / "garments",    # 服装参考
    "voice": C.ASSETS / "voices",        # 声音样本
    "image": C.ASSETS / "images",        # 通用参考图
    "bgm": C.ASSETS / "bgm",
}
UPLOAD_TMP = C.OUTPUTS / "tmp" / "uploads"


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), kind: str = "source",
                 character: str | None = None):
    """浏览器上传素材。kind=source/garment/voice/image/bgm, 或 character+look 形象"""
    if kind == "look":
        if not character:
            raise HTTPException(400, "kind=look 需要 character 参数")
        d = C.ASSETS / "characters" / character / "looks"
    else:
        d = ASSET_KINDS.get(kind)
        if not d:
            raise HTTPException(400, f"未知 kind: {kind}")
    d.mkdir(parents=True, exist_ok=True)
    safe_name = f"{int(time.time())}_{Path(file.filename or 'file').name.replace('..', '_')}"
    dst = d / safe_name
    with open(dst, "wb") as f:
        shutil.copyfileobj(file.file, f)
    rel = dst.relative_to(C.ROOT)
    return {"path": str(rel), "name": safe_name}


@app.get("/api/assets")
def list_assets():
    out = {}
    for kind, d in ASSET_KINDS.items():
        d.mkdir(parents=True, exist_ok=True)
        out[kind] = [str(f.relative_to(C.ROOT)) for f in sorted(d.iterdir()) if f.is_file()]
    out["characters"] = [p.name for p in (C.ASSETS / "characters").iterdir() if p.is_dir()]
    return out


@app.get("/api/assets/file")
def asset_file(path: str):
    p = (C.ROOT / path).resolve()
    if not str(p).startswith(str(C.ASSETS.resolve())) or not p.is_file():
        raise HTTPException(403)
    return FileResponse(p)


@app.get("/api/characters")
def list_characters():
    from pipelines.digital_human.pipeline import character_dir, load_character
    res = []
    chars = C.ASSETS / "characters"
    for d in sorted(chars.iterdir()):
        if not d.is_dir():
            continue
        cfg = load_character(d.name)
        look = character_dir(d.name) / cfg.get("look", "looks/default.png")
        looks = [f.name for f in (d / "looks").iterdir() if f.is_file()] \
            if (d / "looks").exists() else []
        res.append({"name": d.name, "voice_id": cfg.get("voice_id", ""),
                    "look": cfg.get("look"), "looks": looks,
                    "has_look": look.exists()})
    return res


class CharCfgReq(BaseModel):
    voice_id: str | None = None
    default_prompt: str | None = None
    look: str | None = None


@app.post("/api/characters/{name}/config")
def set_character(name: str, req: CharCfgReq):
    d = C.ASSETS / "characters" / name
    (d / "looks").mkdir(parents=True, exist_ok=True)
    cfg = {}
    cfg_file = d / "config.json"
    if cfg_file.exists():
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    for k in ("voice_id", "default_prompt", "look"):
        v = getattr(req, k)
        if v is not None:
            cfg[k] = v
    cfg_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


class VoiceCloneReq(BaseModel):
    voice_path: str          # assets/voices/xxx.wav 相对路径
    voice_id: str            # 自定义音色ID
    character: str = "default"


@app.post("/api/voice/clone")
def voice_clone(req: VoiceCloneReq):
    """上传的声音样本 -> MiniMax 克隆 -> 写入角色 voice_id"""
    from . import minimax
    p = C.ROOT / req.voice_path
    if not p.exists():
        raise HTTPException(404, f"声音文件不存在: {req.voice_path}")
    vid = minimax.Minimax().clone_voice(p, req.voice_id)
    if req.character:
        set_character(req.character, CharCfgReq(voice_id=vid))
    return {"voice_id": vid}


@app.post("/api/characters/{name}/edit-look")
def edit_look(name: str, req: dict):
    """形象编辑: 换装/换发型 (WaveSpeed Qwen-Image-Edit)"""
    from . import wavespeed
    from pipelines.digital_human.pipeline import load_character, character_dir
    cfg = load_character(name)
    cur = character_dir(name) / cfg.get("look", "looks/default.png")
    if not cur.exists():
        raise HTTPException(404, "当前形象图不存在")
    out = character_dir(name) / "looks" / f"edit_{int(time.time())}.png"
    wavespeed.WaveSpeed().image_edit(cur, req["prompt"], out)
    return {"look": f"looks/{out.name}", "path": str(out.relative_to(C.ROOT))}


# ---------------- status ----------------

@app.get("/api/health")
def health():
    return {
        "wavespeed": {"configured": bool(C.WAVESPEED_API_KEY),
                      "url": "https://api.wavespeed.ai"},
        "minimax": {"configured": bool(C.MINIMAX_API_KEY),
                    "url": C.MINIMAX_BASE_URL},
        "comfyui": {"url": C.COMFYUI_BASE_URL, "ok": comfyui.ComfyUI().health()},
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
    resolution: str | None = None
    subtitles: bool | None = None
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
    mode: str = "replace"            # replace | animate2
    pre_edit_prompt: str | None = None
    keep_audio: bool = True
    bgm: str | None = None
    resolution: str | None = None
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
        resolution=req.resolution, subtitles=req.subtitles,
        title=req.title, desc=req.desc, tags=req.tags, jid=jid))


@app.post("/api/jobs/video-transform")
def job_vt(req: VTReq, bg: BackgroundTasks):
    from pipelines.video_transform import pipeline
    jid = store.job_create("video_transform", req.model_dump())
    return _bg(bg, lambda: _run_guarded(
        jid, pipeline.run, _resolve(req.source), prompt=req.prompt,
        face=_resolve(req.face), cloth=_resolve(req.cloth),
        background=_resolve(req.background), mask=_resolve(req.mask),
        workflow=req.workflow, mode=req.mode,
        pre_edit_prompt=req.pre_edit_prompt,
        keep_audio=req.keep_audio, bgm=req.bgm, resolution=req.resolution,
        title=req.title, desc=req.desc, tags=req.tags, jid=jid))


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


@app.get("/api/jobs/{jid}")
def job_detail(jid: str):
    for j in store.job_list(200):
        if j["id"] == jid:
            return j
    raise HTTPException(404)


# ---------------- 节点画布 (graph engine) ----------------

GRAPHS_DIR = C.DB_PATH.parent / "graphs"


@app.get("/api/nodes")
def node_schema():
    """节点类型注册表, 前端据此动态生成画布节点"""
    return nodedefs.schema()


class GraphReq(BaseModel):
    nodes: list[dict]                # [{id,type,pos,params}]
    links: list[dict] = []           # [{src,src_slot,dst,dst_slot}]
    name: str | None = None


@app.post("/api/graph/run")
def graph_run(req: GraphReq, bg: BackgroundTasks):
    graph = {"nodes": req.nodes, "links": req.links}
    try:
        nodegraph.validate(graph)
    except nodegraph.GraphError as e:
        raise HTTPException(400, str(e))
    jid = store.job_create("graph", {"nodes": len(req.nodes),
                                     "name": req.name})
    def _run():
        try:
            res = nodegraph.run(graph, jid)
            store.job_finish(jid, "done", res)
        except Exception as e:
            store.job_finish(jid, "error", {"error": str(e)})
    bg.add_task(_run)
    return {"queued": True, "job": jid}


@app.get("/api/graphs")
def list_graphs():
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    return [{"name": f.stem, "mtime": f.stat().st_mtime}
            for f in sorted(GRAPHS_DIR.glob("*.json"))]


class GraphSaveReq(BaseModel):
    name: str
    graph: dict


@app.post("/api/graphs")
def save_graph(req: GraphSaveReq):
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    name = "".join(c for c in req.name if c not in '/\\..') or f"g{int(time.time())}"
    (GRAPHS_DIR / f"{name}.json").write_text(
        json.dumps(req.graph, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"saved": name}


@app.get("/api/graphs/{name}")
def load_graph(name: str):
    f = GRAPHS_DIR / f"{name}.json"
    if not f.exists():
        raise HTTPException(404)
    return json.loads(f.read_text(encoding="utf-8"))


@app.get("/api/workflows/{name}/inspect")
def wf_inspect(name: str):
    try:
        return comfyui.inspect_workflow(name)
    except Exception as e:
        raise HTTPException(400, str(e))
