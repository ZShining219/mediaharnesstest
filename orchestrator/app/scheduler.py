"""定时调度: 基于 APScheduler。任务定义在 config.yaml schedules.jobs,
运行时可通过 /api/schedules 增删(会写回 config.yaml 持久化)"""
import logging
import time
from pathlib import Path

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config as C
from . import publisher, store

log = logging.getLogger("scheduler")

_scheduler: BackgroundScheduler | None = None


def run_job(jtype: str, params: dict):
    from pipelines.auto_content import pipeline as auto_content
    from pipelines.digital_human import pipeline as digital_human
    from pipelines.video_transform import pipeline as video_transform

    log.info("scheduled job start: %s %s", jtype, params)
    jid = store.job_create(f"cron:{jtype}", params)
    try:
        if jtype == "material_scout":
            from . import materials
            store.job_finish(jid, "done",
                             materials.scout(params.get("direction")))
            return
        if jtype == "digital_human":
            text = params.get("text")
            if not text and params.get("text_file"):
                text = (C.ROOT / params["text_file"]).read_text(encoding="utf-8").strip()
            digital_human.run(text, character=params.get("character", "default"),
                              emotion=params.get("emotion"), tags=params.get("tags"))
        elif jtype == "video_transform":
            video_transform.run(C.ROOT / params["source"],
                                prompt=params.get("prompt", ""),
                                face=_p(params.get("face")),
                                cloth=_p(params.get("cloth")),
                                background=_p(params.get("background")),
                                tags=params.get("tags"))
        elif jtype == "auto_content":
            auto_content.run(params["subject"], script=params.get("script", ""),
                             tags=params.get("tags"))
        elif jtype == "publish_approved":
            publish_approved(params.get("platform", "douyin"))
        else:
            raise ValueError(f"unknown job type: {jtype}")
        store.job_finish(jid, "done", {})
    except Exception as e:
        log.exception("scheduled job failed")
        store.job_finish(jid, "error", {"error": str(e)})


def _p(v) -> Path | None:
    return C.ROOT / v if v else None


def publish_approved(platform: str = "douyin"):
    """把 approved 队列里的作品逐个发布"""
    for item in store.list_approved():
        meta = item
        try:
            publisher.upload_video(
                Path(item["path"]), title=meta.get("title") or item["id"],
                desc=meta.get("desc", ""), tags=meta.get("tags") or [],
                platform=meta.get("platform") or platform,
                schedule=meta.get("schedule"))
            store.move_item(item["id"], C.APPROVED_DIR, C.PUBLISHED_DIR)
            log.info("published %s", item["id"])
        except Exception as e:
            log.error("publish %s failed: %s", item["id"], e)
            store.move_item(item["id"], C.APPROVED_DIR, C.FAILED_DIR)


def _register(job: dict):
    minute, hour, day, month, dow = job["cron"].split()
    _scheduler.add_job(
        run_job, CronTrigger(minute=minute, hour=hour, day=day,
                             month=month, day_of_week=dow),
        args=[job["type"], job.get("params", {})],
        id=job.get("id", job["type"]), replace_existing=True)


def start():
    global _scheduler
    sc = C.section("schedules")
    if _scheduler:
        return
    _scheduler = BackgroundScheduler()
    for job in sc.get("jobs") or []:
        _register(job)
        log.info("registered cron job %s (%s)", job.get("id"), job["cron"])
    if sc.get("enabled", True):
        _scheduler.start()


def list_jobs() -> list[dict]:
    """当前生效的定时任务(含下次触发时间)"""
    out = []
    live = {j.id: j for j in _scheduler.get_jobs()} if _scheduler else {}
    cfg_jobs = C.section("schedules").get("jobs") or []
    seen = set()
    for j in cfg_jobs:
        jid = j.get("id", j["type"])
        seen.add(jid)
        lj = live.get(jid)
        out.append({**j, "id": jid, "enabled": True,
                    "next_run": lj.next_run_time.isoformat() if lj and lj.next_run_time else None,
                    "source": "config"})
    for jid, lj in live.items():
        if jid not in seen:
            out.append({"id": jid, "type": jid.split(":")[0], "cron": str(lj.trigger),
                        "params": {}, "enabled": True,
                        "next_run": lj.next_run_time.isoformat() if lj.next_run_time else None,
                        "source": "runtime"})
    return out


def _save_cfg(mutate):
    """读改 config.yaml 并回写(保留其它 section)"""
    p = C.ROOT / "config.yaml"
    if not p.exists():
        p = C.ROOT / "config.example.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    mutate(data)
    (C.ROOT / "config.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    C.cfg.cache_clear()


def add_job(job: dict):
    """新增/覆盖定时任务: {id,type,cron,params}"""
    if not job.get("cron") or not job.get("type"):
        raise ValueError("需要 cron 和 type")
    job.setdefault("id", f"{job['type']}_{int(time.time())}")

    def mut(data):
        sc = data.setdefault("schedules", {})
        jobs = sc.setdefault("jobs", [])
        jobs[:] = [x for x in jobs if x.get("id") != job["id"]]
        jobs.append({"id": job["id"], "type": job["type"],
                     "cron": job["cron"], "params": job.get("params", {})})
    _save_cfg(mut)
    if _scheduler:
        _register(job)
    return job


def remove_job(job_id: str):
    def mut(data):
        jobs = data.get("schedules", {}).get("jobs", [])
        jobs[:] = [x for x in jobs if x.get("id") != job_id]
    _save_cfg(mut)
    if _scheduler:
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass
    return {"removed": job_id}
