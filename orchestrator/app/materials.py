"""素材采集: 对标视频/服饰图 搜索下载 + AI 换装生成

素材源:
- Pexels (PEXELS_API_KEY, 视频/图 优选, 免费 200req/h)
- Wikimedia Commons (免 key 兜底, 质量参差但零配置)
- MiniMax 官方站 image_generation: subject_reference 固定人物换装
"""
import json
import mimetypes
import re
import subprocess
import threading
import time
from pathlib import Path

import httpx

from . import config as C

PEXELS_API = "https://api.pexels.com/v1"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "aimf-materials/1.0 (media workflow; contact: local)"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}


class MaterialsError(RuntimeError):
    pass


def _pexels_key() -> str:
    return C.env("PEXELS_API_KEY")


def provider() -> str:
    return "pexels" if _pexels_key() else "commons"


# ---------------- Pexels ----------------

def _pexels_get(path: str, **params) -> dict:
    r = httpx.get(f"{PEXELS_API}{path}", params=params, timeout=30,
                  headers={"Authorization": _pexels_key()})
    if r.status_code != 200:
        raise MaterialsError(f"Pexels HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _pexels_videos(query: str, count: int, orientation: str | None = None):
    params = {"query": query, "per_page": min(80, count)}
    if orientation in ("portrait", "landscape", "square"):
        params["orientation"] = orientation
    items = []
    for v in _pexels_get("/videos/search", **params).get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("link")]
        if not files:
            continue
        files.sort(key=lambda f: f.get("width") or 0)
        pick = next((f for f in files if (f.get("width") or 0) >= 720), files[-1])
        items.append({
            "id": f"pexels-v{v['id']}", "provider": "pexels", "kind": "video",
            "thumb": v.get("image"), "url": pick["link"],
            "duration": v.get("duration"), "w": pick.get("width"),
            "h": pick.get("height"),
            "desc": (v.get("user") or {}).get("name", ""),
        })
    return items


def _pexels_photos(query: str, count: int):
    items = []
    for p in _pexels_get("/search", query=query,
                         per_page=min(80, count)).get("photos", []):
        src = p.get("src") or {}
        items.append({
            "id": f"pexels-p{p['id']}", "provider": "pexels", "kind": "image",
            "thumb": src.get("medium"), "url": src.get("large2") or src.get("large"),
            "w": p.get("width"), "h": p.get("height"),
            "desc": p.get("alt", ""),
        })
    return items


# ---------------- Wikimedia Commons ----------------

def _commons_files(query: str, count: int, kind: str):
    """免 key 兜底源。kind=video|image"""
    filetype = "video" if kind == "video" else "bitmap"
    r = httpx.get(COMMONS_API, timeout=30, headers=UA, params={
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": 6, "gsrlimit": min(50, count),
        "gsrsearch": f"{query} filetype:{filetype}",
        "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 320,
    })
    data = r.json()
    items = []
    for pg in (data.get("query") or {}).get("pages", {}).values():
        ii = (pg.get("imageinfo") or [{}])[0]
        if not ii.get("url"):
            continue
        items.append({
            "id": f"commons-{pg.get('pageid')}", "provider": "commons",
            "kind": kind, "thumb": ii.get("thumburl") or ii.get("url"),
            "url": ii["url"], "w": ii.get("width"), "h": ii.get("height"),
            "desc": pg.get("title", "").removeprefix("File:"),
        })
    return items


# ---------------- 对外接口 ----------------

def search(kind: str, query: str, count: int = 8,
           orientation: str | None = None) -> dict:
    """统一搜索入口, 返回 {provider, items}"""
    if not query.strip():
        raise MaterialsError("需要搜索关键词")
    if _pexels_key():
        items = (_pexels_videos if kind == "video" else _pexels_photos)(
            query, count, orientation) if kind == "video" else _pexels_photos(query, count)
    else:
        items = _commons_files(query, count, kind)
        if orientation == "portrait" and kind == "video":
            items = [i for i in items if (i.get("h") or 0) > (i.get("w") or 0)]
    return {"provider": provider(), "items": items}


_KIND_DIR = {
    "video": ("sources", VIDEO_EXT), "source": ("sources", VIDEO_EXT),
    "garment": ("garments", IMAGE_EXT), "cloth": ("garments", IMAGE_EXT),
    "image": ("images", IMAGE_EXT),
}


def download(url: str, kind: str, name: str | None = None,
             headers: dict | None = None) -> str:
    """下载远 url -> assets/<桶>/, 返回项目相对路径"""
    sub, exts = _KIND_DIR.get(kind, _KIND_DIR["image"])
    d = C.ASSETS / sub
    d.mkdir(parents=True, exist_ok=True)
    h = {**UA, **(headers or {})}
    with httpx.stream("GET", url, timeout=300, headers=h,
                      follow_redirects=True) as r:
        r.raise_for_status()
        suffix = Path(url.split("?")[0]).suffix.lower()
        if suffix not in exts:
            suffix = mimetypes.guess_extension(
                r.headers.get("content-type", "").split(";")[0]) or ""
        if suffix not in exts:
            raise MaterialsError(f"不支持的文件类型: {suffix or r.headers.get('content-type')}")
        base = re.sub(r"[^\w.-]+", "_", name or Path(url.split("?")[0]).stem
                      or f"{kind}_{int(time.time())}")[:80]
        dst = d / f"{int(time.time())}_{base}{suffix}"
        with open(dst, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    return str(dst.relative_to(C.ROOT))


def gen_looks(image: Path, prompts: list[str], ratio: str = "3:4",
              n: int = 1) -> list[str]:
    """AI 换装: 固定人物参考图 + 每条提示词生成服装造型图 -> assets/images/"""
    from . import minimax
    mm = minimax.Minimax.official()
    subj = [{"type": "character", "image_file": minimax.as_url(image)}]
    out_dir = C.ASSETS / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, p in enumerate(prompts):
        if not p.strip():
            continue
        data = mm.gen_images(
            f"全身正面照，人物保持参考图的长相和发型，换上：{p.strip()}。服装展示清晰",
            subject=subj, aspect_ratio=ratio, n=min(4, n))
        for j, b64 in enumerate(data):
            dst = out_dir / f"look_{int(time.time())}_{i + 1}_{j + 1}.png"
            import base64
            dst.write_bytes(base64.b64decode(b64))
            paths.append(str(dst.relative_to(C.ROOT)))
    return paths


# ---------------- 社交媒体采集 (MediaCrawler 子进程) ----------------

MC_DIR = C.ROOT / "services" / "MediaCrawler"
SOCIAL_PLATFORMS = ("xhs", "douyin")
_social_lock = threading.Lock()          # user_data_dir 同时只允许一个 Chrome
_login_procs: dict[str, subprocess.Popen] = {}


def social_status() -> dict:
    """各平台登录资料目录是否存在 + 是否正在扫码登录"""
    out = {}
    for p in SOCIAL_PLATFORMS:
        d = MC_DIR / "browser_data" / f"{p}_user_data_dir"
        proc = _login_procs.get(p)
        out[p] = {
            "profile": d.is_dir() and any(d.iterdir()),
            "logging_in": bool(proc and proc.poll() is None),
        }
    return out


def social_search(platform: str, query: str, count: int = 10,
                  timeout: int = 300) -> dict:
    """调用 services/MediaCrawler/mc_search.py 搜索, 返回标准化 items"""
    if platform not in SOCIAL_PLATFORMS:
        raise MaterialsError(f"不支持的平台: {platform}")
    if not MC_DIR.is_dir():
        raise MaterialsError("MediaCrawler 未部署(services/MediaCrawler 不存在)")
    cmd = ["uv", "run", "mc_search.py", "--platform", platform,
           "--query", query, "--count", str(min(20, count))]
    try:
        with _social_lock:
            r = subprocess.run(cmd, cwd=MC_DIR, capture_output=True,
                               text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"provider": platform, "items": [],
                "error": f"搜索超时({timeout}s), 平台可能风控或网络不佳"}
    for line in reversed(r.stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "provider" in data:
            return data
    tail = (r.stderr or "").strip().splitlines()
    return {"provider": platform, "items": [],
            "error": f"采集进程异常(exit {r.returncode}): "
                     f"{(tail[-1] if tail else '无输出')[:200]}"}


def social_login(platform: str) -> dict:
    """有头拉起 Chrome 扫码登录, 登录态存 browser_data/。进程后台运行"""
    if platform not in SOCIAL_PLATFORMS:
        raise MaterialsError(f"不支持的平台: {platform}")
    proc = _login_procs.get(platform)
    if proc and proc.poll() is None:
        return {"started": True, "already": True}
    log_dir = C.ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log = open(log_dir / f"mc_login_{platform}.log", "ab")
    _login_procs[platform] = subprocess.Popen(
        ["uv", "run", "mc_search.py", "--platform", platform, "--login"],
        cwd=MC_DIR, stdout=log, stderr=log, start_new_session=True)
    return {"started": True}


# ---------------- DeepSeek 检索规划 / 候选初筛 ----------------

_PLAN_SYS = """你是自媒体素材检索策划。根据用户主题输出 JSON(不要多余文本):
{"xhs_queries":[<=4个小红书检索词],"douyin_queries":[<=4个抖音检索词],"garment_queries":[<=4个服装/穿搭图检索词],"rank_rule":"<一句话筛选偏好>"}
检索词要短、口语化、贴近平台内容生态; garment_queries 为服饰图片搜索用(可留空数组)。"""


def plan_queries(brief: str, want_garment: bool = True,
                 garment_themes: list[str] | None = None) -> dict:
    """DeepSeek 主题->平台检索词组; 失败回退原词(fallback=True)"""
    from . import llm
    user = f"主题: {brief}"
    if garment_themes:
        user += f"\n服装方向偏好: {'、'.join(garment_themes)}"
    try:
        txt = llm.LLM().chat(user, _PLAN_SYS, max_tokens=600, temperature=0.4)
        m = re.search(r"\{.*\}", txt, re.S)
        data = json.loads(m.group(0)) if m else {}
        plan = {
            "xhs_queries": [q for q in data.get("xhs_queries", []) if str(q).strip()][:4],
            "douyin_queries": [q for q in data.get("douyin_queries", []) if str(q).strip()][:4],
            "garment_queries": ([q for q in data.get("garment_queries", [])
                                 if str(q).strip()][:4] if want_garment else []),
            "rank_rule": str(data.get("rank_rule") or ""),
        }
        if not plan["xhs_queries"] and not plan["douyin_queries"]:
            raise ValueError("空检索词")
        return plan
    except Exception as e:
        return {"xhs_queries": [brief], "douyin_queries": [brief],
                "garment_queries": [brief] if want_garment else [],
                "rank_rule": "", "fallback": True, "error": str(e)}


_RANK_SYS = """你是自媒体素材筛选。按用户主题与筛选偏好, 从候选视频里挑最适合做"对标视频/参考素材"的。
只输出 JSON: {"order":["按推荐度排序的id"...],"reasons":{"id":"<一句话理由>"},"scores":{"id":0-100}}。不要多余文本。"""


def rank_candidates(brief: str, items: list[dict], top: int = 10,
                    rule: str = "") -> dict:
    """DeepSeek 按标题/作者/互动数据排序+打分; 失败回退原顺序(fallback=True)"""
    from . import llm
    items = items[:40]
    if not items:
        return {"order": [], "reasons": {}, "scores": {}}
    cand = [{"id": it.get("id"), "标题": (it.get("desc") or "")[:80],
             "作者": it.get("author"), "点赞": it.get("likes"),
             "时长s": it.get("duration")} for it in items]
    try:
        txt = llm.LLM().chat(
            f"主题: {brief}\n筛选偏好: {rule or '无特别偏好'}\n"
            f"候选:\n{json.dumps(cand, ensure_ascii=False)}",
            _RANK_SYS, max_tokens=1400, temperature=0.3)
        m = re.search(r"\{.*\}", txt, re.S)
        data = json.loads(m.group(0)) if m else {}
        ids = {it.get("id") for it in items}
        order = [i for i in data.get("order", []) if i in ids][:top]
        order += [it["id"] for it in items
                  if it.get("id") not in set(order)][:max(0, top - len(order))]
        return {"order": order, "reasons": data.get("reasons") or {},
                "scores": data.get("scores") or {}}
    except Exception as e:
        return {"order": [it.get("id") for it in items][:top],
                "reasons": {}, "scores": {}, "fallback": True, "error": str(e)}


# ---------------- 内容方向 + 每日备料池 ----------------

DIRECTIONS_FILE = C.ROOT / "data" / "directions.json"
POOL_FILE = C.ROOT / "data" / "material_pool.json"


DEFAULT_DIRECTIONS = [{
    "name": "职场西装口播",
    "active": True,
    "brief": "25-35岁都市白领通勤西装穿搭口播",
    "daily_quota": {"xhs": 8, "douyin": 8},
    "rank_rule": "真人出镜口播, 有搭配干货讲解, 非纯带货广告, 竖屏优先",
    "garment_themes": ["西装套装", "通勤大衣", "商务衬衫"],
    "transform_prompt": "保留原视频口播内容与节奏, 人物换成参考形象, 服装参考图示",
}]


def directions_load() -> list[dict]:
    """data/directions.json — 内容方向配置(任务意图的唯一事实源)。
    文件不存在时落盘默认值, 方便用户直接在文件上改。"""
    if not DIRECTIONS_FILE.exists():
        directions_save(DEFAULT_DIRECTIONS)
        return list(DEFAULT_DIRECTIONS)
    try:
        return json.loads(DIRECTIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def directions_save(dirs: list[dict]):
    DIRECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DIRECTIONS_FILE.write_text(
        json.dumps(dirs, ensure_ascii=False, indent=2), encoding="utf-8")


def _pool() -> list[dict]:
    if not POOL_FILE.exists():
        return []
    try:
        return json.loads(POOL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _pool_save(items: list[dict]):
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def pool_list(days: int = 3) -> list[dict]:
    """近 N 天备料记录, 新的在前。文件被删的标 gone=true"""
    cutoff = time.time() - days * 86400
    out = []
    for it in reversed(_pool()):
        if (it.get("stocked_at") or 0) < cutoff:
            continue
        p = it.get("path")
        out.append({**it, "gone": bool(p) and not (C.ROOT / p).exists()})
    return out


def _known_ids() -> set[str]:
    """已入池过的平台 id — 跨天去重, 保证每日固定量不重复"""
    return {it.get("id") for it in _pool() if it.get("id")}


def _pool_add(direction: str, items: list[dict]):
    pool = _pool()
    now = int(time.time())
    pool += [{**it, "direction": direction, "stocked_at": now,
              "status": "new"} for it in items]
    _pool_save(pool[-2000:])


def scout(direction_name: str | None = None) -> dict:
    """每日备料: 方向 -> DeepSeek规划 -> 双平台搜索 -> 去重 -> DeepSeek初筛
    -> 下载topK进素材库 -> 记入备料池。零生成开销(DeepSeek 仅几千token)"""
    summary = {"directions": [], "stocked": 0, "errors": []}
    for d in directions_load():
        if not d.get("active", True):
            continue
        if direction_name and d.get("name") != direction_name:
            continue
        name = d.get("name") or "未命名方向"
        brief = (d.get("brief") or name).strip()
        quota = d.get("daily_quota") or {}
        entry = {"name": name, "searched": 0, "stocked": 0}
        try:
            plan = plan_queries(brief, want_garment=True,
                                garment_themes=d.get("garment_themes"))
            cands: list[dict] = []
            need_login_pfs = []
            for pf, qs in (("xhs", plan["xhs_queries"]),
                           ("douyin", plan["douyin_queries"])):
                target = int(quota.get(pf) or 8)
                for q in qs[:3]:
                    have = sum(1 for c in cands if c.get("provider") == pf)
                    if have >= target:
                        break
                    r = social_search(pf, q, min(12, target - have))
                    entry["searched"] += len(r.get("items") or [])
                    if r.get("need_login"):
                        need_login_pfs.append(pf)
                        break
                    cands += [c for c in r.get("items") or [] if c.get("url")]
            for pf in set(need_login_pfs):
                summary["errors"].append(f"{name}/{pf}: 需要扫码登录")

            known, seen, uniq = _known_ids(), set(), []
            for c in cands:
                if c.get("id") in known or c.get("id") in seen:
                    continue
                seen.add(c.get("id"))
                uniq.append(c)

            top = min(8, len(uniq))
            ranked = rank_candidates(brief, uniq, top=top,
                                   rule=d.get("rank_rule") or plan.get("rank_rule"))
            reasons, scores = ranked.get("reasons") or {}, ranked.get("scores") or {}
            byid = {c["id"]: c for c in uniq}
            stocked: list[dict] = []
            for cid in (ranked.get("order") or [])[:8]:
                c = byid.get(cid)
                if not c:
                    continue
                try:
                    rel = download(c["url"], "video",
                                   (c.get("desc") or c["id"])[:60],
                                   c.get("dl_headers"))
                    stocked.append({**c, "path": rel, "reason": reasons.get(cid),
                                    "score": scores.get(cid)})
                except Exception as e:
                    summary["errors"].append(f"{cid}: 下载失败 {e}")

            for q in (plan.get("garment_queries") or [])[:2]:
                try:
                    for g in (search("image", q, 4).get("items") or []):
                        if not g.get("url") or g.get("id") in known:
                            continue
                        try:
                            rel = download(g["url"], "garment",
                                           (g.get("desc") or q)[:60],
                                           g.get("headers"))
                            stocked.append({**g, "path": rel})
                        except Exception:
                            pass
                except Exception as e:
                    summary["errors"].append(f"{name}/服装搜索[{q}]: {e}")

            _pool_add(name, stocked)
            entry["stocked"] = len(stocked)
        except Exception as e:
            summary["errors"].append(f"{name}: {e}")
        summary["directions"].append(entry)
    summary["stocked"] = sum(x["stocked"] for x in summary["directions"])
    return summary
