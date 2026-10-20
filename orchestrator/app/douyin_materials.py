"""抖音素材获取模块: 账号解析 -> 作品清单 -> 关键词筛选 -> 下载入库 -> 参考池。

底层通过 services/MediaCrawler/mc_creator.py 操作已登录的抖音会话；
本模块不直接碰浏览器, 只负责编排和落盘, 便于 API / CLI / Agent 复用。

典型用法:
    from orchestrator.app import douyin_materials as dm
    dm.resolve_user("都市丽人服饰内衣旗舰店")
    dm.list_user_videos(sec_uid, max_videos=50)
    dm.acquire(account="都市丽人服饰内衣旗舰店",
               keywords=["文胸", "高开衩"], max_videos=50,
               download=True, add_to_pool=True)
    dm.acquire(queries=["都市丽人 文胸"], author_filter="都市丽人",
               keywords=["文胸"], max_videos=20)
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import config as C, materials, media, reference_pool

MC_DIR = C.ROOT / "services" / "MediaCrawler"
SRC_DIR = C.ASSETS / "sources"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
DL_HEADERS = {"Referer": "https://www.douyin.com/", "User-Agent": UA}
# 与 materials.social_search 共用同一把锁: 抖音持久化 profile 同时只能被一个 Chrome 使用
_LOCK = getattr(materials, "_social_lock", None) or threading.Lock()


def _run_creator(args: list[str], timeout: int = 900) -> dict:
    if not MC_DIR.is_dir():
        return {"error": "MediaCrawler 未部署 (services/MediaCrawler 不存在)"}
    cmd = ["uv", "run", "mc_creator.py", *args]
    try:
        with _LOCK:
            r = subprocess.run(cmd, cwd=MC_DIR, capture_output=True,
                               text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"抖音操作超时({timeout}s)"}
    except Exception as e:
        return {"error": f"抖音操作失败: {e}"}
    for line in reversed((r.stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    tail = ((r.stderr or "").strip().splitlines() or [""])[-1]
    return {"error": f"采集进程异常(exit {r.returncode}): {tail[:300]}"}


def resolve_user(name: str) -> dict:
    """按昵称搜索抖音账号, 返回候选 users。"""
    name = (name or "").strip()
    if not name:
        return {"error": "需要账号昵称"}
    return _run_creator(["--resolve-user", name], timeout=180)


def pick_user(users: list[dict], name: str) -> dict | None:
    exact = [u for u in users if (u.get("nickname") or "").strip() == name.strip()]
    if exact:
        return exact[0]
    return users[0] if users else None


def list_user_videos(sec_uid: str, max_videos: int = 200,
                     with_details: bool = False) -> dict:
    """列出账号主页作品; with_details=True 会逐条补商品锚点/播放地址。"""
    if not sec_uid:
        return {"error": "需要 sec_uid"}
    n = max(1, min(500, int(max_videos or 200)))
    args = ["--sec-uid", sec_uid, "--list",
            "--max-videos", str(n), "--max-pages", "30"]
    if with_details:
        args.append("--with-details")
    return _run_creator(args, timeout=1500 if with_details else 600)


def _haystack(it: dict) -> str:
    parts = [it.get("desc") or "", it.get("author") or ""]
    for p in it.get("products") or []:
        parts.append(p.get("title") or "")
    return " ".join(parts).casefold()


def filter_items(items: list[dict], keywords: list[str] | None = None,
                 exclude_keywords: list[str] | None = None) -> list[dict]:
    kw = [k.strip().casefold() for k in (keywords or []) if k and k.strip()]
    ex = [k.strip().casefold() for k in (exclude_keywords or []) if k and k.strip()]
    out = []
    for it in items:
        hay = _haystack(it)
        if kw and not any(k in hay for k in kw):
            continue
        if ex and any(k in hay for k in ex):
            continue
        out.append(it)
    return out


def _normalize_search_item(it: dict) -> dict:
    raw_id = str(it.get("id") or it.get("aweme_id") or "")
    aid = raw_id[3:] if raw_id.startswith("dy-") else raw_id
    urls = [u for u in (it.get("urls") or []) if u]
    if not urls and it.get("url"):
        urls = [it["url"]]
    return {
        **it,
        "aweme_id": aid,
        "id": raw_id,
        "urls": urls,
        "url": urls[0] if urls else "",
        "is_video": bool(urls),
        "products": it.get("products") or [],
        "dl_headers": it.get("dl_headers") or DL_HEADERS,
    }


def search_videos(queries: list[str], count: int = 20) -> dict:
    """关键词搜索抖音视频(用于抓其他都市丽人账号的文胸/品类素材)。"""
    seen = set()
    items: list[dict] = []
    errors = []
    for q in [x.strip() for x in (queries or []) if x and x.strip()]:
        r = materials.social_search("douyin", q, min(20, max(1, count)))
        if r.get("need_login"):
            return {"error": "抖音需要扫码登录", "need_login": True, "items": []}
        if r.get("error"):
            errors.append(f"{q}: {r['error']}")
        for it in r.get("items") or []:
            norm = _normalize_search_item(it)
            if norm["aweme_id"] and norm["aweme_id"] not in seen:
                seen.add(norm["aweme_id"])
                norm["matched_query"] = q
                items.append(norm)
    return {"provider": "douyin", "items": items, "errors": errors}


def _valid_file(path: Path) -> tuple[float, int] | None:
    try:
        dur = media.ffprobe_duration(path)
        size = path.stat().st_size
        if dur and dur > 0 and size > 0:
            return float(dur), size
    except Exception:
        pass
    return None


def _existing(aid: str) -> tuple[Path, float, int] | None:
    if not SRC_DIR.is_dir():
        return None
    best = None
    for p in SRC_DIR.iterdir():
        if not p.is_file() or aid not in p.name:
            continue
        v = _valid_file(p)
        if not v:
            continue
        dur, size = v
        if best is None or size > best[2]:
            best = (p, dur, size)
    return best


def _clean_new_files(before: set[str], aid: str):
    """materials.download 失败时可能留下残片; 只清理本次新增且带 aweme_id 的文件。"""
    try:
        for name in set(os.listdir(SRC_DIR)) - before:
            if aid in name:
                try:
                    os.remove(SRC_DIR / name)
                except OSError:
                    pass
    except OSError:
        pass


def _download_item(it: dict, prefix: str) -> tuple[str | None, float | None, list[str]]:
    aid = str(it.get("aweme_id") or "")
    desc = (it.get("desc") or "").strip().replace("\n", " ")
    urls = [u for u in (it.get("urls") or []) if u]
    if not urls and it.get("url"):
        urls = [it["url"]]
    if not urls:
        return None, None, ["没有播放地址"]
    headers = it.get("dl_headers") or DL_HEADERS
    name = f"{prefix}_{aid}_{desc[:36]}"
    errs = []
    for j, url in enumerate(urls[:4], 1):
        before = set(os.listdir(SRC_DIR)) if SRC_DIR.is_dir() else set()
        try:
            rel = materials.download(url, "source", name, headers=headers)
            p = C.ROOT / rel
            v = _valid_file(p)
            if v:
                return rel, v[0], errs
            errs.append(f"candidate{j}: 文件不可播放")
            try:
                p.unlink()
            except OSError:
                pass
        except Exception as e:
            errs.append(f"candidate{j}: {e}")
            _clean_new_files(before, aid)
    return None, None, errs


def _add_pool(it: dict, rel: str, extra_tags: list[str] | None = None) -> dict | None:
    aid = str(it.get("aweme_id") or "")
    desc = (it.get("desc") or "").strip().replace("\n", " ")
    author = it.get("author") or ""
    tags = ["抖音", "抖音获取"] + list(extra_tags or [])
    for k in ("文胸", "内衣", "内裤", "高开衩", "开叉", "三角", "无痕", "冰丝",
              "性感", "抗菌", "纯棉", "蕾丝", "聚拢", "无钢圈"):
        if k in desc:
            tags.append(k)
    tags = list(dict.fromkeys(t for t in tags if t))
    return reference_pool.add(
        path=rel,
        title=desc[:80] or aid,
        note=(f"{author} · {desc}" if author else desc),
        tags=tags,
        source_url=it.get("page_url") or "",
    )


def acquire(account: str | None = None, sec_uid: str | None = None,
            queries: list[str] | None = None,
            author_filter: str | None = None,
            keywords: list[str] | None = None,
            exclude_keywords: list[str] | None = None,
            max_videos: int = 50,
            download: bool = True, add_to_pool: bool = True,
            tags: list[str] | None = None,
            with_details: bool = False,
            dry_run: bool = False) -> dict:
    """一条龙获取素材。

    - account: 按昵称解析账号, 抓主页作品
    - sec_uid: 已知账号 sec_uid, 直接抓主页
    - queries: 关键词搜索模式(可与 author_filter 组合)
    - keywords: 标题/商品名关键词, 任一命中即保留
    - exclude_keywords: 命中即排除
    - dry_run: 只返回匹配清单, 不下载、不入池
    """
    n = max(1, min(200, int(max_videos or 50)))
    download = bool(download) and not dry_run
    add_to_pool = bool(add_to_pool) and not dry_run
    report = {
        "provider": "douyin", "mode": "search" if queries else "account",
        "account": account, "sec_uid": sec_uid,
        "keywords": keywords or [], "exclude_keywords": exclude_keywords or [],
        "max_videos": n, "download": download, "add_to_pool": add_to_pool,
        "dry_run": dry_run, "listed": 0, "matched": 0,
        "downloaded": 0, "existing": 0, "failed": 0, "pool_added": 0,
        "items": [], "errors": [],
    }

    if queries:
        sr = search_videos(queries, count=min(20, n * 2))
        if sr.get("error"):
            report["error"] = sr["error"]
            report["need_login"] = sr.get("need_login")
            return report
        report["errors"].extend(sr.get("errors") or [])
        listed = sr.get("items") or []
        if author_filter:
            listed = [x for x in listed if author_filter in (x.get("author") or "")]
    else:
        if not sec_uid:
            rr = resolve_user(account or "")
            if rr.get("error") or rr.get("need_login"):
                report["error"] = rr.get("error") or "抖音需要扫码登录"
                report["need_login"] = rr.get("need_login")
                return report
            user = pick_user(rr.get("users") or [], account or "")
            if not user:
                report["error"] = f"未找到账号: {account}"
                return report
            sec_uid = user.get("sec_uid")
            report["sec_uid"] = sec_uid
            report["resolved_user"] = user
        # 关键词筛选前先多扫一些作品, 否则 max_videos 很小会截断候选
        scan_limit = min(500, max(n * 5, 100))
        lr = list_user_videos(sec_uid, max_videos=scan_limit,
                              with_details=with_details)
        if lr.get("error") or lr.get("need_login"):
            report["error"] = lr.get("error") or "抖音需要扫码登录"
            report["need_login"] = lr.get("need_login")
            return report
        listed = lr.get("items") or []
        report["author"] = lr.get("author") or ""
        report["pages"] = lr.get("pages")

    report["listed"] = len(listed)
    matched = filter_items(listed, keywords, exclude_keywords)
    # 只保留视频; 图文/无地址作品跳过并记录
    videos, skipped = [], []
    for it in matched:
        if not it.get("is_video", bool(it.get("urls"))):
            skipped.append({"aweme_id": it.get("aweme_id"),
                            "desc": (it.get("desc") or "")[:80],
                            "reason": "not_video_or_no_url"})
            continue
        videos.append(it)
    report["matched"] = len(videos)
    report["skipped_non_video"] = skipped[:50]
    target = videos[:n]

    for i, it in enumerate(target, 1):
        aid = str(it.get("aweme_id") or "")
        row = {
            "aweme_id": aid,
            "desc": (it.get("desc") or "")[:120],
            "author": it.get("author") or "",
            "duration": it.get("duration"),
            "page_url": it.get("page_url") or "",
        }
        ex = _existing(aid)
        if ex:
            p, dur, size = ex
            rel = os.path.relpath(p, C.ROOT)
            row.update({"status": "existing", "file": rel, "duration": dur,
                        "size": size})
            report["existing"] += 1
            if add_to_pool:
                ref = _add_pool(it, rel, tags)
                row["pool_id"] = (ref or {}).get("id")
                report["pool_added"] += 1
            report["items"].append(row)
            continue
        if not download:
            row["status"] = "matched"
            report["items"].append(row)
            continue
        rel, dur, errs = _download_item(it, "douyin")
        if rel:
            report["downloaded"] += 1
            row.update({"status": "downloaded", "file": rel, "duration": dur})
            if add_to_pool:
                ref = _add_pool(it, rel, tags)
                row["pool_id"] = (ref or {}).get("id")
                report["pool_added"] += 1
            print(f"[{i}/{len(target)}] OK {aid} -> {rel}")
        else:
            report["failed"] += 1
            row.update({"status": "failed", "errors": errs})
            report["errors"].append(f"{aid}: {'; '.join(errs)[:300]}")
        report["items"].append(row)

    report["finished_at"] = int(time.time())
    return report
