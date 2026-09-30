"""自动化创作管线: 主题 -> MoneyPrinterTurbo 生成短视频 -> 审核队列

适用于: AI 工具教程、知识科普、资讯类自动成片。
MPT 支持 MiniMax/DeepSeek 等 LLM 写稿, Pexels/Pixabay/AI生成 素材, 自动字幕BGM。
"""
from pathlib import Path

from orchestrator.app import mpt, store
from orchestrator.app import config as C


class PipelineError(RuntimeError):
    pass


def run(subject: str, script: str = "", title: str | None = None,
        desc: str = "", tags: list[str] | None = None,
        jid: str | None = None, **overrides) -> dict:
    cfg = C.section("auto_content")
    jid = jid or store.job_create("auto_content", {"subject": subject})
    try:
        client = mpt.MPT()
        if not client.health():
            raise PipelineError(
                f"MoneyPrinterTurbo 不可达: {client.base}, "
                f"启动: cd services/MoneyPrinterTurbo && uv run python main.py")
        task_id = client.create_video(
            subject, script=script,
            aspect=cfg.get("video_aspect", "9:16"),
            source=cfg.get("video_source", "pexels"),
            voice_name=cfg.get("voice_name", ""),
            clip_duration=cfg.get("video_clip_duration", 5),
            count=cfg.get("video_count", 1),
            **overrides)
        t = client.wait(task_id)
        videos = t.get("videos") or []
        if not videos:
            raise PipelineError(f"MPT 任务完成但无产出: {t}")
        out = C.TMP_DIR / f"{jid}_mpt.mp4"
        client.download(videos[0], out)

        item = store.add_review_item(out, "auto_content", {
            "title": title or subject[:20], "desc": desc or subject,
            "tags": tags or [], "mpt_task": task_id,
        })
        store.job_finish(jid, "done", {"item": str(item), "item_id": item.stem,
                                       "task_id": task_id})
        return {"job": jid, "item": str(item)}
    except Exception as e:
        store.job_finish(jid, "error", {"error": str(e)})
        raise


def main():
    import argparse
    ap = argparse.ArgumentParser(description="自动化创作短视频")
    ap.add_argument("--subject", required=True, help="主题, 如 'Kimi 新功能教程'")
    ap.add_argument("--script", default="", help="自定义文案, 空则 AI 生成")
    ap.add_argument("--title", default=None)
    ap.add_argument("--tags", default="")
    a = ap.parse_args()
    print(run(a.subject, script=a.script, title=a.title,
              tags=[t for t in a.tags.split(",") if t]))


if __name__ == "__main__":
    main()
