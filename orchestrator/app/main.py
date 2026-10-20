"""编排器 FastAPI 服务: 仪表盘 / 审核 / 任务提交 / 发布 / 素材管理"""
import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import comfyui, config as C, equivgraph, mpt, nodegraph, nodedefs, publisher, scheduler, store

app = FastAPI(title="AI 传媒工作流编排器")
log = logging.getLogger("orchestrator")


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
    n = store.job_mark_interrupted()
    if n:
        print(f"[store] {n} 个遗留 running 任务标记为 interrupted")
    scheduler.start()


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


# ---------------- pages ----------------

TPL = Path(__file__).parent / "templates"
DIST = C.ROOT / "web" / "dist"


@app.get("/", response_class=HTMLResponse)
def index():
    if (DIST / "index.html").exists():
        return (DIST / "index.html").read_text(encoding="utf-8")
    return (TPL / "index.html").read_text(encoding="utf-8")


@app.get("/legacy", response_class=HTMLResponse)
def legacy_index():
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
    "person": C.ASSETS / "persons",      # 固定人物照片组
    "product": C.ASSETS / "products",    # 本期商品图
    "background": C.ASSETS / "backgrounds",  # 背景参考图
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


# ---------------- 固定参考视频池 ----------------

class RefPoolAddReq(BaseModel):
    path: str | None = None          # assets/ 下的已有视频
    url: str | None = None           # 或远端链接, 下载入 assets/sources/
    title: str | None = None
    note: str = ""
    tags: list[str] | None = None
    source_url: str | None = None


class RefFissionReq(BaseModel):
    ref_id: str
    product_time: float = 8.0
    n: int = 5
    bgm: str | None = None
    person: str | None = None
    dry_run: bool = False
    no_generate: bool = False


class FissionRunReq(BaseModel):
    profile_id: str = "bra-milk-lace"
    product_image: str | None = None
    person: str | None = None
    text: str | None = None
    n: int = 3
    skip_generate: bool = False
    resume: bool = False
    out_root: str | None = None


class FissionP0Req(BaseModel):
    profile_id: str = "panty-cotton-lace"
    product_image: str | None = None
    person: str | None = None
    text: str | None = None
    n: int = 5
    seed: int | None = None
    prepare_materials: bool = True
    refresh_materials: bool = False
    skip_generate: bool = False


FISSION_RUNS = C.ROOT / "data" / "runs"


def _is_p0_engine(engine) -> bool:
    return str(engine or "").startswith("p0")


@app.get("/api/reference-pool")
def reference_pool_list():
    from . import reference_pool
    return reference_pool.list_items()


@app.post("/api/reference-pool")
def reference_pool_add(req: RefPoolAddReq):
    from . import reference_pool
    try:
        return reference_pool.add(
            path=req.path, url=req.url, title=req.title,
            note=req.note, tags=req.tags, source_url=req.source_url)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/reference-pool/{item_id}")
def reference_pool_delete(item_id: str):
    from . import reference_pool
    try:
        return reference_pool.delete(item_id)
    except KeyError as e:
        raise HTTPException(404, e.args[0] if e.args else "参考池记录不存在")


@app.get("/api/reference-cases")
def reference_cases():
    from . import reference_analysis
    return reference_analysis.list_cases()


@app.get("/api/reference-cases/{ref_id}")
def reference_case(ref_id: str):
    from . import reference_analysis
    try:
        return reference_analysis.load_case(ref_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/reference-runs")
def reference_runs():
    from . import reference_fission
    return reference_fission.list_runs()


@app.get("/api/reference-runs/{run_id}")
def reference_run(run_id: str):
    from . import reference_fission
    try:
        return reference_fission.load_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------- 新裂变链路: profiles / runs / submit / resume ----------------

def _fission_run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id or ""):
        raise HTTPException(400, "非法 run_id")
    d = (FISSION_RUNS / run_id).resolve()
    if not d.is_relative_to(FISSION_RUNS.resolve()) or not d.is_dir():
        raise HTTPException(404, "run 不存在")
    return d


def _fission_load(rel: str) -> dict | list | None:
    try:
        return json.loads((FISSION_RUNS / rel).read_text(encoding="utf-8"))
    except Exception:
        return None


def _fission_summary(d: Path) -> dict | None:
    m = _fission_load(f"{d.name}/run.json")
    if not isinstance(m, dict):
        return None
    videos = list(d.glob("v[0-9][0-9]/variant_*.mp4"))
    return {
        "run_id": d.name,
        "engine": m.get("engine"),
        "status": m.get("status"),
        "profile_id": m.get("profile_id"),
        "n": m.get("n"),
        "created_at": m.get("created_at"),
        "updated_at": m.get("updated_at"),
        "inputs": m.get("inputs") or {},
        "stages": m.get("stages") or {},
        "contracts": (((m.get("stages") or {}).get("contracts") or {})
                      .get("count")),
        "audit_ok": (m.get("audit") or {}).get("ok"),
        "videos": len(videos),
        "errors": m.get("errors") or [],
    }


def _fission_detail(d: Path) -> dict:
    manifest = _fission_load(f"{d.name}/run.json") or {}
    ev = _fission_load(f"{d.name}/evaluation.json") or {}
    vset = _fission_load(f"{d.name}/variants.json") or {}
    worlds = _fission_load(f"{d.name}/worlds.json") or {}
    vpayload = vset.get("payload") or {} if isinstance(vset, dict) else {}
    ev_by_video = {}
    for e in (ev.get("evaluations") or []):
        if isinstance(e, dict) and e.get("video"):
            ev_by_video[Path(str(e["video"])).name] = e.get("validation")
    variants = []
    for cp in sorted(d.glob("v[0-9][0-9]/contract.json")):
        c = _fission_load(f"{d.name}/{cp.parent.name}/contract.json")
        if not isinstance(c, dict):
            continue
        vdir = cp.parent
        video = next(vdir.glob("variant_*.mp4"), None)
        run = _fission_load(f"{d.name}/{vdir.name}/run.json") or {}
        beats = (c.get("structure") or {}).get("beats") or []
        prompt_path = vdir / "prompt_h3.txt"
        voice_path = vdir / "voiceover.txt"
        cfmt = (c.get("target") or {}).get("format") or {}
        pres = cfmt.get("presentation") or {}
        variants.append({
            "index": int(vdir.name[1:]),
            "name": (c.get("structure") or {}).get("name") or vdir.name,
            "hypothesis": (c.get("structure") or {}).get("concept") or "",
            "primary_ref": (beats[0].get("source") or {}).get("ref_id")
            if beats else None,
            "beats": len(beats),
            "duration": cfmt.get("duration"),
            "archetype": cfmt.get("archetype"),
            "lane": pres.get("name"),
            "lane_summary": pres.get("summary"),
            "creative_world": (c.get("structure") or {}).get("creative_world"),
            "style_id": (c.get("structure") or {}).get("style_id"),
            "person_visibility": pres.get("person_visibility"),
            "presenter_mode": pres.get("presenter_mode"),
            "pacing": pres.get("pacing"),
            "voiceover": cfmt.get("voiceover"),
            "subtitles": cfmt.get("subtitles"),
            "validation": c.get("_validation") or {},
            "product_validation": ev_by_video.get(video.name) if video else None,
            "contract": c,
            "prompt": prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "",
            "voiceover": voice_path.read_text(encoding="utf-8").strip() if voice_path.exists() else "",
            "video": str(video.relative_to(C.ROOT)) if video else None,
            "review": run.get("review_path"),
            "run": run,
        })
    return {"run_id": d.name, "manifest": manifest,
            "variants": variants, "evaluation": ev,
            "audit": manifest.get("audit") or {},
            "worlds": worlds,
            "presentation_lanes": vpayload.get("presentation_lanes") or [],
            "diversity": vpayload.get("diversity") or {}}


@app.get("/api/fission/profiles")
def fission_profiles():
    from pipelines.fission.profiles import PROFILE_DIR
    out = []
    for p in sorted(PROFILE_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "profile_id": d.get("product_id") or p.stem,
            "category": d.get("category"),
            "identity": d.get("identity"),
            "image": d.get("image"),
            "person": (d.get("person") or {}).get("image"),
            "default_archetype": d.get("default_archetype"),
            "color_policy": d.get("color_policy"),
            "offer": d.get("offer"),
        })
    return out


@app.get("/api/fission/runs")
def fission_runs():
    if not FISSION_RUNS.exists():
        return {"items": []}
    items = []
    for d in FISSION_RUNS.iterdir():
        if not d.is_dir():
            continue
        s = _fission_summary(d)
        if s:
            items.append(s)
    items.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return {"items": items}


@app.get("/api/fission/runs/{run_id}")
def fission_run(run_id: str):
    d = _fission_run_dir(run_id)
    return _fission_detail(d)


@app.post("/api/jobs/fission")
def job_fission(req: FissionRunReq, bg: BackgroundTasks):
    from pipelines.fission.runner import run_pipeline
    params = req.model_dump()
    jid = store.job_create("fission_run", params)

    def _run():
        try:
            res = run_pipeline(
                req.profile_id, req.text, req.n, req.out_root,
                req.skip_generate, req.resume, req.person, req.product_image)
            store.job_finish(jid, "done", {
                "run_dir": res.get("run_dir"),
                "manifest": res.get("manifest"),
                "videos": res.get("videos"),
                "evaluation": res.get("evaluation"),
            })
        except Exception as e:
            log.exception("fission run failed")
            store.job_finish(jid, "error",
                             {"error": f"{type(e).__name__}: {e}"})

    bg.add_task(_run)
    return {"queued": True, "job": jid}


@app.post("/api/jobs/fission-p0")
def job_fission_p0(req: FissionP0Req, bg: BackgroundTasks):
    """P0.2 产品化 job：素材解读 -> 契约 -> H3 -> 审核队列。"""
    if req.n < 1 or req.n > 10:
        raise HTTPException(400, "n 必须在 1..10")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "", Path(req.profile_id).stem) or "product"
    run_id = (f"p0-{slug}-{time.strftime('%Y%m%d-%H%M%S')}-"
              f"{uuid.uuid4().hex[:6]}")
    run_dir = FISSION_RUNS / run_id
    params = req.model_dump()
    params.update({"run_id": run_id,
                   "run_dir": str(run_dir.relative_to(C.ROOT))})
    jid = store.job_create("fission_p0", params)

    def _progress(phase: str, extra: dict | None = None):
        data = {"phase": phase, "run_id": run_id,
                "run_dir": str(run_dir.relative_to(C.ROOT))}
        if extra:
            data["progress"] = extra
        store.job_update(jid, data)

    def _run():
        try:
            from pipelines.fission.p0_runner import run_p0
            res = run_p0(
                req.profile_id, req.text, req.n, str(run_dir), req.seed,
                person=req.person, product_image=req.product_image,
                prepare_materials=(req.prepare_materials
                                   or req.refresh_materials),
                refresh_materials=req.refresh_materials,
                generate=not req.skip_generate,
                progress=_progress,
            )
            manifest = res.get("manifest") or {}
            status = str(manifest.get("status") or "")
            result = {
                "run_dir": str(run_dir.relative_to(C.ROOT)),
                "run_id": run_id,
                "engine": "p0.2",
                "manifest": manifest,
                "videos": res.get("videos") or [],
                "contracts": len(res.get("contracts") or []),
                "audit_ok": (res.get("audit") or {}).get("ok"),
                "phase": ("contracts_only" if status == "contracts_done"
                          else "audit_failed" if status == "audit_failed"
                          else "generation"),
                "status": status,
            }
            if status == "partial":
                store.job_finish(jid, "partial", result)
            elif status in ("done", "contracts_done"):
                store.job_finish(jid, "done", result)
            else:
                store.job_finish(jid, "error", result)
        except Exception as e:
            log.exception("fission p0 job failed")
            store.job_finish(jid, "error", {
                "error": f"{type(e).__name__}: {e}",
                "run_id": run_id,
                "run_dir": str(run_dir.relative_to(C.ROOT)),
            })

    bg.add_task(_run)
    return {"queued": True, "job": jid, "run_id": run_id}


@app.post("/api/fission/runs/{run_id}/resume")
def fission_resume(run_id: str, bg: BackgroundTasks):
    d = _fission_run_dir(run_id)
    manifest = _fission_load(f"{d.name}/run.json") or {}
    if manifest.get("status") == "done":
        raise HTTPException(400, "run 已完成，无需续跑")
    engine = manifest.get("engine")
    inputs = manifest.get("inputs") or {}

    if _is_p0_engine(engine):
        from pipelines.fission.p0_runner import resume_p0_generation
        jid = store.job_create("fission_p0", {
            "run_id": run_id, "resume": True, "engine": engine,
            "inputs": inputs})

        def _progress(phase: str, extra: dict | None = None):
            data = {"phase": phase, "run_id": run_id,
                    "run_dir": str(d.relative_to(C.ROOT))}
            if extra:
                data["progress"] = extra
            store.job_update(jid, data)

        def _run_p0_resume():
            try:
                res = resume_p0_generation(d, progress=_progress)
                status = str((res.get("manifest") or {}).get("status") or "")
                result = {
                    "run_dir": str(d.relative_to(C.ROOT)),
                    "run_id": run_id,
                    "engine": engine,
                    "manifest": res.get("manifest"),
                    "videos": res.get("videos") or [],
                    "audit_ok": ((res.get("manifest") or {}).get(
                        "audit") or {}).get("ok"),
                    "status": status,
                    "phase": "generation",
                }
                if status == "partial":
                    store.job_finish(jid, "partial", result)
                elif status == "done":
                    store.job_finish(jid, "done", result)
                else:
                    store.job_finish(jid, "error", result)
            except Exception as e:
                log.exception("fission p0 resume failed")
                store.job_finish(jid, "error", {
                    "error": f"{type(e).__name__}: {e}",
                    "run_id": run_id,
                    "run_dir": str(d.relative_to(C.ROOT)),
                })

        bg.add_task(_run_p0_resume)
        return {"queued": True, "job": jid, "run_id": run_id}

    from pipelines.fission.runner import run_pipeline
    jid = store.job_create("fission_run", {
        "run_id": run_id, "resume": True, "inputs": inputs})

    def _run():
        try:
            res = run_pipeline(
                inputs.get("profile") or manifest.get("profile_path")
                or manifest.get("profile_id") or "bra-milk-lace",
                inputs.get("text"), int(inputs.get("n") or manifest.get("n") or 3),
                str(d), False, True, inputs.get("person"),
                inputs.get("product_image"))
            store.job_finish(jid, "done", {
                "run_dir": res.get("run_dir"),
                "manifest": res.get("manifest"),
                "videos": res.get("videos"),
                "evaluation": res.get("evaluation"),
            })
        except Exception as e:
            log.exception("fission resume failed")
            store.job_finish(jid, "error",
                             {"error": f"{type(e).__name__}: {e}"})

    bg.add_task(_run)
    return {"queued": True, "job": jid}


@app.get("/api/file")
def any_file(path: str):
    """任务输入/中间产物预览: 限 assets/ 与 outputs/ 目录内的文件"""
    p = Path(path)
    if not p.is_absolute():
        p = C.ROOT / p
    p = p.resolve()
    roots = (C.ASSETS.resolve(), C.OUTPUTS.resolve(),
             FISSION_RUNS.resolve())
    if not any(p.is_relative_to(r) for r in roots) or not p.is_file():
        raise HTTPException(404)
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
        "minimax_tts": {"configured": bool(C.env("MINIMAX_API_KEY_OFFICIAL") or C.MINIMAX_API_KEY),
                        "url": C.env("MINIMAX_BASE_URL_OFFICIAL", "https://api.minimax.cn")},
        "deepseek": {"configured": bool(C.env("LLM_API_KEY")),
                     "url": C.env("LLM_BASE_URL", "https://api.deepseek.com")},
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
    body: str | None = None          # 身体参考图·正面(体型/姿态)
    body_back: str | None = None     # 身体参考图·背面
    body_side: str | None = None     # 身体参考图·侧面
    cloth: str | None = None
    refs: list[str] = []             # 追加参考图(槽位扩展)
    background: str | None = None
    mask: str | None = None
    workflow: str | None = None
    mode: str = "replace"            # replace | animate2
    pre_edit_prompt: str | None = None
    keep_audio: bool = True
    bgm: str | None = None
    resolution: str | None = None
    ratio: str | None = None          # adaptive/9:16/16:9/1:1 (仅 minimax 后端生效)
    duration: int | None = None       # 4-15 秒(仅 minimax), 空=跟随对标视频长度
    title: str | None = None
    desc: str = ""
    tags: list[str] = []


class ACReq(BaseModel):
    subject: str
    script: str = ""
    title: str | None = None
    desc: str = ""
    tags: list[str] = []


class PVPlanReq(BaseModel):
    intent: str
    person_photos: list[str] = []
    product_images: list[str] = []
    background_images: list[str] = []
    duration: int | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    bgm: str | None = None
    pacing: str | None = None


class PVJobReq(BaseModel):
    plan_id: str
    bgm: str | None = None


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
    params = req.model_dump()
    try:  # 等效执行图 + 输入清单(供任务详情回放/对照), 失败不阻塞提交
        from pipelines.digital_human.pipeline import character_dir, load_character
        look = req.look or load_character(req.character).get("look", "looks/default.png")
        look_path = f"assets/characters/{req.character}/{look}"
        voice = load_character(req.character).get("voice_id")
        params["graph"], params["inputs"] = equivgraph.digital_human(
            req.text, req.character, look_path, voice, req.emotion, req.title)
    except Exception:
        pass
    jid = store.job_create("digital_human", params)
    return _bg(bg, lambda: _run_guarded(
        jid, pipeline.run, req.text, character=req.character,
        emotion=req.emotion, look=req.look, prompt=req.prompt,
        resolution=req.resolution, subtitles=req.subtitles,
        title=req.title, desc=req.desc, tags=req.tags, jid=jid))


@app.post("/api/jobs/video-transform")
def job_vt(req: VTReq, bg: BackgroundTasks):
    from pipelines.video_transform import pipeline
    params = req.model_dump()
    try:
        params["graph"], params["inputs"] = equivgraph.video_transform(
            _resolve(req.source), _resolve(req.face), req.prompt, req.title,
            body=_resolve(req.body), body_back=_resolve(req.body_back),
            body_side=_resolve(req.body_side), cloth=_resolve(req.cloth),
            refs=[_resolve(r) for r in req.refs])
    except Exception:
        pass
    jid = store.job_create("video_transform", params)
    return _bg(bg, lambda: _run_guarded(
        jid, pipeline.run, _resolve(req.source), prompt=req.prompt,
        face=_resolve(req.face), body=_resolve(req.body),
        body_back=_resolve(req.body_back), body_side=_resolve(req.body_side),
        cloth=_resolve(req.cloth),
        refs=[_resolve(r) for r in req.refs],
        background=_resolve(req.background), mask=_resolve(req.mask),
        workflow=req.workflow, mode=req.mode,
        pre_edit_prompt=req.pre_edit_prompt,
        keep_audio=req.keep_audio, bgm=req.bgm, resolution=req.resolution,
        ratio=req.ratio, duration=req.duration,
        title=req.title, desc=req.desc, tags=req.tags, jid=jid))


@app.post("/api/jobs/auto-content")
def job_ac(req: ACReq, bg: BackgroundTasks):
    from pipelines.auto_content import pipeline
    params = req.model_dump()
    try:
        params["graph"], params["inputs"] = equivgraph.auto_content(
            req.subject, req.script, req.title)
    except Exception:
        pass
    jid = store.job_create("auto_content", params)
    return _bg(bg, lambda: _run_guarded(
        jid, pipeline.run, req.subject, script=req.script,
        title=req.title, desc=req.desc, tags=req.tags, jid=jid))


def _run_guarded(job_id, fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        # 管线通常已经自行写过终态(含 provider_task / unknown); job_finish
        # 默认只允许 running -> 终态, 这里的兜底不会覆盖那条记录。
        log.exception("job %s failed: %s", job_id, e)
        store.job_finish(job_id, "error", {"error": str(e)})


# ---------------- B 线: 视觉编导型带货视频 ----------------

@app.post("/api/product-video/plan")
def pv_plan(req: PVPlanReq):
    """意图 + 人物照片 + 商品图 (+背景) -> DirectorPlan(已编译逐镜提示词)。"""
    from pipelines.product_video import plan as pvplan
    try:
        return pvplan.create(req.model_dump())
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/product-video/plans")
def pv_plans():
    from pipelines.product_video import plan as pvplan
    return pvplan.list_plans()


@app.get("/api/product-video/plan/{plan_id}")
def pv_plan_get(plan_id: str):
    from pipelines.product_video import plan as pvplan
    try:
        return pvplan.load(plan_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.put("/api/product-video/plan/{plan_id}")
def pv_plan_put(plan_id: str, data: dict):
    from pipelines.product_video import plan as pvplan
    try:
        return pvplan.update(plan_id, data)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.post("/api/product-video/plan/{plan_id}/compile")
def pv_plan_compile(plan_id: str):
    from pipelines.product_video import plan as pvplan
    try:
        return pvplan.save(pvplan.compile_plan(pvplan.load(plan_id)))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.post("/api/jobs/product-video")
def job_pv(req: PVJobReq, bg: BackgroundTasks):
    from pipelines.product_video import plan as pvplan, pipeline
    try:
        p = pvplan.load(req.plan_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    jid = store.job_create("product_video", req.model_dump())
    bg.add_task(_run_guarded, jid, pipeline.run,
                req.plan_id, jid, req.bgm or p.get("bgm"))
    return {"queued": True, "job": jid}


@app.post("/api/jobs/reference-fission")
def job_reference_fission(req: RefFissionReq, bg: BackgroundTasks):
    from . import reference_fission, reference_pool
    if req.ref_id not in {x.get("id") for x in reference_pool.list_items()}:
        raise HTTPException(404, "参考视频不存在")
    n = max(1, min(5, int(req.n)))
    params = req.model_dump()
    params["n"] = n
    jid = store.job_create("reference_fission", params)

    def _run():
        def cb(phase, current=0, total=0, **extra):
            store.job_update(jid, {"phase": phase, "current": current,
                                   "total": total, **extra})
        try:
            res = reference_fission.run_full(
                ref_id=req.ref_id, product_time=float(req.product_time),
                person=req.person or "assets/persons/半身照.png",
                n=n, bgm=req.bgm, dry_run=req.dry_run,
                no_generate=req.no_generate, progress_cb=cb)
            compact = {
                "run_dir": res.get("run_dir"),
                "export_dir": res.get("export_dir"),
                "manifest": res.get("manifest"),
                "validations": res.get("validations") or [],
                "dry_run": res.get("dry_run", False),
                "no_generate": res.get("no_generate", False),
                "variants": [
                    {"name": v.get("name"), "hook": v.get("hook")}
                    for v in (res.get("variants") or [])
                ] if res.get("dry_run") else [],
                "plans": res.get("plans") if res.get("no_generate") else [],
            }
            store.job_finish(jid, "done", compact)
        except Exception as e:
            log.exception("reference fission failed")
            store.job_finish(jid, "error", {"error": str(e)})

    bg.add_task(_run)
    return {"queued": True, "job": jid}


@app.get("/api/jobs")
def jobs():
    return store.job_list()


@app.get("/api/jobs/{jid}")
def job_detail(jid: str):
    for j in store.job_list(200):
        if j["id"] == jid:
            return j
    raise HTTPException(404)


@app.post("/api/jobs/{jid}/recover")
def job_recover(jid: str, bg: BackgroundTasks,
                task_id: str | None = None, via: str | None = None):
    """断连/超时判错的 video_transform 任务: 按 provider_task(秘塔/官方 task_id)
    取回已生成结果 -> 进审核队列, job 置回 done。
    task_id 参数: 任务记录里没有时(旧任务), 从秘塔/官方后台抄来手动指定,
    可用 ?via=official 或 task_id 前缀 official: 指定官方通道"""
    job = next((j for j in store.job_list(200) if j["id"] == jid), None)
    if not job:
        raise HTTPException(404)
    result = job.get("result") or {}
    tid = task_id or result.get("provider_task")
    via = via or result.get("provider_via") or "metaso"
    if tid and ":" in tid and tid.split(":")[0] in ("official", "metaso"):
        via, tid = tid.split(":", 1)
    if not tid:
        raise HTTPException(400, "该任务没有记录的秘塔 task_id(提交前就失败了); "
                                 "可传 ?task_id= 从秘塔后台抄来")
    if job["status"] == "done" and job["result"].get("item_id"):
        raise HTTPException(400, "任务已完成且有产出, 无需找回")

    def work():
        from . import minimax
        try:
            store.job_update(jid, status="running",
                             result={"recovering": True, "error": None,
                                     "recover_error": None})
            out = C.TMP_DIR / f"{jid}_recovered.mp4"
            minimax.Minimax.video_client(via).video_wait_download(tid, out)
            p = job.get("params") or {}
            item = store.add_review_item(out, "video_transform", {
                "title": p.get("title") or Path(p.get("source") or jid).stem,
                "desc": p.get("desc", ""), "tags": p.get("tags") or [],
                "source": Path(p.get("source") or "").name,
                "prompt": p.get("prompt", ""), "mode": p.get("mode"),
                "job": jid, "inputs": p.get("inputs") or [],
                "recovered_from": tid,
            })
            store.job_finish(jid, "done", {
                "item": str(item), "item_id": item.stem,
                "provider_task": tid, "provider_via": via,
                "recovered": True})
        except Exception as e:
            # 取回失败多半仍是传输问题: 远端任务依旧在, 保持 unknown
            store.job_update(
                jid, status="unknown" if minimax.is_ambiguous_error(e) else "error",
                result={"recover_error": str(e)})
    return _bg(bg, work)


@app.get("/api/dashboard")
def dashboard():
    """首页汇总: 队列计数 + 最近任务 + 服务状态要点"""
    jobs = store.job_list(100)
    return {
        "review": len(store.list_review()),
        "approved": len(store.list_approved()),
        "published": len(store._items_in(C.PUBLISHED_DIR)),
        "failed": len(store._items_in(C.FAILED_DIR)),
        "jobs_running": sum(1 for j in jobs if j["status"] == "running"),
        "jobs_total": len(jobs),
        "jobs_recent": jobs[:6],
        "schedules": scheduler.list_jobs() if scheduler._scheduler else [],
    }


# ---------------- 素材采集 (自动选材) ----------------

@app.get("/api/materials/search")
def materials_search(kind: str, query: str, count: int = 8,
                     orientation: str | None = None):
    """kind=video|image; 返回 {provider: pexels|commons, items:[{thumb,url,...}]}"""
    from . import materials
    try:
        return materials.search(kind, query, min(50, count), orientation)
    except Exception as e:
        raise HTTPException(400, str(e))


class MatDlReq(BaseModel):
    items: list[dict]                # [{url, kind, name?, headers?}]


@app.post("/api/materials/download")
def materials_download(req: MatDlReq):
    """勾选的远素材下载入素材库, 返回项目相对路径列表"""
    from . import materials
    paths, errs = [], []
    for it in req.items[:50]:
        try:
            paths.append(materials.download(it["url"], it.get("kind", "image"),
                                            it.get("name") or it.get("desc"),
                                            it.get("headers")))
        except Exception as e:
            errs.append(f"{it.get('url', '?')}: {e}")
    return {"paths": paths, "errors": errs}


# ---------------- 社交媒体采集 (小红书/抖音, MediaCrawler) ----------------

@app.get("/api/materials/social/status")
def social_status():
    """各平台登录资料目录 + 是否正在扫码登录"""
    from . import materials
    return materials.social_status()


@app.get("/api/materials/social/search")
def social_search(platform: str, query: str, count: int = 10):
    """搜小红书/抖音视频候选(慢接口, 服务端串行)。
    need_login=true 表示需先扫码登录"""
    from . import materials
    try:
        return materials.social_search(platform, query, count)
    except Exception as e:
        raise HTTPException(400, str(e))


class SocialLoginReq(BaseModel):
    platform: str                  # xhs | douyin


@app.post("/api/materials/social/login")
def social_login(req: SocialLoginReq):
    """有头拉起 Chrome 扫码登录(窗口弹在本机, 约5分钟有效)"""
    from . import materials
    try:
        return materials.social_login(req.platform)
    except Exception as e:
        raise HTTPException(400, str(e))


class MatPlanReq(BaseModel):
    brief: str                     # 主题描述, 如 "职场通勤西装口播"
    want_garment: bool = True      # 是否同时规划服装图检索词


@app.post("/api/materials/plan")
def materials_plan(req: MatPlanReq):
    """DeepSeek 把主题展开成平台检索词组; LLM 失败时回退原词直搜"""
    from . import materials
    if not req.brief.strip():
        raise HTTPException(400, "需要主题描述")
    return materials.plan_queries(req.brief, req.want_garment)


class MatRankReq(BaseModel):
    brief: str
    items: list[dict]              # [{id, desc, author?, likes?, duration?}]
    top: int = 10


@app.post("/api/materials/rank")
def materials_rank(req: MatRankReq):
    """DeepSeek 按标题/作者/互动数据给候选排序; 失败回退原顺序"""
    from . import materials
    return materials.rank_candidates(req.brief, req.items, req.top)


# ---------------- 每日备料 (directions + scout + pool) ----------------

@app.get("/api/directions")
def directions_get():
    from . import materials
    return materials.directions_load()


@app.put("/api/directions")
def directions_put(dirs: list[dict]):
    """整体回写内容方向配置(任务意图事实源)"""
    from . import materials
    for d in dirs:
        if not (d.get("name") or d.get("brief")):
            raise HTTPException(400, "每个方向需要 name 或 brief")
    materials.directions_save(dirs)
    return {"saved": len(dirs)}


@app.get("/api/materials/pool")
def materials_pool(days: int = 3):
    """近 N 天备料记录(agent 已筛好, 带理由/分数)"""
    from . import materials
    return {"items": materials.pool_list(min(14, days))}


class ScoutReq(BaseModel):
    direction: str | None = None   # 指定方向名; 空=全部 active 方向


@app.post("/api/materials/scout")
def materials_scout(req: ScoutReq, bg: BackgroundTasks):
    """手动触发备料(约1-3分钟): 规划->搜索->初筛->下载入池, 见任务中心"""
    from . import materials
    jid = store.job_create("material_scout", req.model_dump())

    def run():
        try:
            store.job_finish(jid, "done",
                             materials.scout(req.direction or None))
        except Exception as e:
            store.job_finish(jid, "error", {"error": str(e)})
    return _bg(bg, run)


class GenLooksReq(BaseModel):
    image: str                       # 形象图(项目相对路径), 作 subject_reference
    prompts: list[str]               # 服装/造型描述, 每行一条
    ratio: str = "3:4"
    n: int = 1


@app.post("/api/materials/gen-looks")
def materials_gen_looks(req: GenLooksReq):
    """AI 换装: 固定人物 + 多条服装描述 -> 形象变体图入 assets/images/"""
    from . import materials
    img = _resolve(req.image)
    if not img or not img.exists():
        raise HTTPException(404, f"形象图不存在: {req.image}")
    if not req.prompts:
        raise HTTPException(400, "需要至少一条服装描述")
    try:
        paths = materials.gen_looks(img, req.prompts[:6], req.ratio, req.n)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"paths": paths}


# ---------------- 抖音素材获取 (账号/关键词 -> 下载 + 参考池) ----------------

class DouyinResolveReq(BaseModel):
    name: str


class DouyinVideosReq(BaseModel):
    account: str | None = None
    sec_uid: str | None = None
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    max_videos: int = 50
    with_details: bool = False


class DouyinAcquireReq(BaseModel):
    account: str | None = None
    sec_uid: str | None = None
    queries: list[str] | None = None
    author_filter: str | None = None
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    max_videos: int = 50
    download: bool = True
    add_to_pool: bool = True
    tags: list[str] | None = None
    with_details: bool = False
    dry_run: bool = False


@app.post("/api/douyin/resolve")
def douyin_resolve(req: DouyinResolveReq):
    """按昵称解析抖音账号, 返回昵称/sec_uid/粉丝数等候选。"""
    from . import douyin_materials
    return douyin_materials.resolve_user(req.name)


@app.post("/api/douyin/videos")
def douyin_videos(req: DouyinVideosReq):
    """列出账号作品并筛选(不下载); 供 Agent 先看清单再决定。"""
    from . import douyin_materials
    sec_uid = req.sec_uid
    if not sec_uid:
        if not req.account:
            raise HTTPException(400, "需要 account 或 sec_uid")
        rr = douyin_materials.resolve_user(req.account)
        if rr.get("error") or rr.get("need_login"):
            return rr
        user = douyin_materials.pick_user(rr.get("users") or [], req.account)
        if not user:
            raise HTTPException(404, f"未找到账号: {req.account}")
        sec_uid = user.get("sec_uid")
    n = max(1, int(req.max_videos or 50))
    scan_limit = min(500, max(n * 5, 100))
    lr = douyin_materials.list_user_videos(
        sec_uid, max_videos=scan_limit,
        with_details=req.with_details)
    if lr.get("error") or lr.get("need_login"):
        return lr
    items = douyin_materials.filter_items(
        lr.get("items") or [], req.keywords, req.exclude_keywords)
    total = len(items)
    return {
        "provider": "douyin",
        "sec_uid": sec_uid,
        "author": lr.get("author") or "",
        "listed": len(lr.get("items") or []),
        "matched": total,
        "returned": min(total, n),
        "items": items[:n],
    }


@app.post("/api/jobs/douyin-acquire")
def douyin_acquire(req: DouyinAcquireReq, bg: BackgroundTasks):
    """创建抖音素材获取任务: 解析/列作品 -> 筛选 -> 下载 -> 入参考池。"""
    from . import douyin_materials
    jid = store.job_create("douyin_acquire", req.model_dump())

    def run():
        try:
            res = douyin_materials.acquire(**req.model_dump())
            status = "error" if res.get("error") else "done"
            store.job_finish(jid, status, res, force=True)
        except Exception as e:
            store.job_finish(jid, "error", {"error": str(e)}, force=True)

    return _bg(bg, run)


# ---------------- 提示词模板 ----------------

@app.get("/api/prompt-templates")
def tpl_list():
    from . import templates
    return templates.list_tpl()


class TplReq(BaseModel):
    name: str
    text: str


@app.post("/api/prompt-templates")
def tpl_save(req: TplReq):
    from . import templates
    if not req.name.strip() or not req.text.strip():
        raise HTTPException(400, "模板名和内容都不能为空")
    return {"items": templates.upsert(req.name, req.text)}


@app.delete("/api/prompt-templates/{name}")
def tpl_del(name: str):
    from . import templates
    return {"items": templates.delete(name)}


# ---------------- 定时任务 ----------------

@app.get("/api/schedules")
def schedules_list():
    return scheduler.list_jobs()


class SchedReq(BaseModel):
    id: str | None = None
    type: str                      # digital_human/video_transform/auto_content/publish_approved
    cron: str                      # "分 时 日 月 周"
    params: dict = {}


@app.post("/api/schedules")
def schedules_add(req: SchedReq):
    try:
        return scheduler.add_job(req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/schedules/{job_id}")
def schedules_del(job_id: str):
    return scheduler.remove_job(job_id)


@app.get("/api/outputs/{state}")
def outputs_list(state: str):
    """state: review/approved/published/failed/all

    all: 合并四类产出并按创建时间倒序, 每项带 state 字段(作品墙用)。
    """
    dirs = {"review": C.REVIEW_DIR, "approved": C.APPROVED_DIR,
            "published": C.PUBLISHED_DIR, "failed": C.FAILED_DIR}
    if state == "all":
        items = [{**it, "state": name}
                 for name, d in dirs.items() for it in store._items_in(d)]
        items.sort(key=lambda it: it.get("created_at") or 0, reverse=True)
        return items
    d = dirs.get(state)
    if not d:
        raise HTTPException(404)
    return store._items_in(d)


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
    jid = store.job_create("graph", {
        "nodes": len(req.nodes), "name": req.name,
        "graph": graph, "inputs": nodegraph.graph_inputs(graph)})
    def _run():
        try:
            res = nodegraph.run(graph, jid)
            store.job_finish(jid, "done", res)
        except Exception as e:
            from . import minimax
            # 合并写回(不覆盖 node_status/logs/provider_task); H3 任务在远端
            # 可能已建成/已完成时标 unknown, 供人工按 task_id 取回。
            store.job_update(
                jid, status="unknown" if minimax.is_ambiguous_error(e) else "error",
                result={"error": str(e)})
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


# ---------------- 前端静态托管(最后注册, 兜底) ----------------
# vite 构建产物 web/dist: index.html 引用 /assets/*, 挂在根路径;
# 路由均在其之前注册, /api /media /static 不受影响
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dist")
