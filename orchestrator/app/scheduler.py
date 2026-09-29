"""定时调度: 基于 APScheduler, 任务定义在 config.yaml schedules.jobs"""
import logging
from pathlib import Path

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
        log.warning("unknown job type: %s", jtype)


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


def start():
    global _scheduler
    sc = C.section("schedules")
    if not sc.get("enabled") or _scheduler:
        return
    _scheduler = BackgroundScheduler()
    for job in sc.get("jobs") or []:
        minute, hour, day, month, dow = job["cron"].split()
        _scheduler.add_job(
            run_job, CronTrigger(minute=minute, hour=hour, day=day,
                                 month=month, day_of_week=dow),
            args=[job["type"], job.get("params", {})],
            id=job.get("id", job["type"]), replace_existing=True)
        log.info("registered cron job %s (%s)", job.get("id"), job["cron"])
    _scheduler.start()
