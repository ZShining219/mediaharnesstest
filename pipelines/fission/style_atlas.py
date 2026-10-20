"""StyleAtlas：把视频池 facet 抽成可采样的风格属性，不定义固定车道。

每条参考保留：
- visual：人物呈现、声音呈现、机位、场景、节奏、字幕密度、证明方式；
- copy：语气、人称、hook、句式、CTA、文本密度；
- signatures：给 planner 做 max-min 距离计算；
- evidence_refs：回到池子的 ref:shot。
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACETS_DIR = ROOT / "data" / "reference_facets"

VISUAL_WEIGHTS = {
    "person_visibility": 4, "presenter_mode": 4, "camera_family": 2,
    "scene_family": 2, "pacing_bucket": 1, "text_density": 1,
}
COPY_WEIGHTS = {
    "tone": 3, "person": 3, "hook_type": 2, "sentence_style": 2,
    "cta_style": 3, "text_density": 1,
}


def _join(*parts) -> str:
    return " ".join(str(x) for x in parts if x)


def _facet_text(f: dict) -> str:
    st = f.get("structure") or {}
    style = f.get("style") or {}
    scene = f.get("scene") or {}
    text = f.get("text") or {}
    shots = []
    for s in f.get("timeline") or []:
        shots.append(_join(s.get("subject"), s.get("action"),
                           s.get("composition"), s.get("product")))
    transcripts = " ".join(str(x.get("text") or "")
                           for x in (text.get("transcript") or []))
    onscreen = " ".join(str(x.get("on_screen_text") or "")
                        for x in (text.get("by_shot") or []))
    return _join(st.get("hook"), st.get("proof"), st.get("cta"),
                 style.get("global_style"), style.get("camera_language"),
                 style.get("pacing"), scene.get("description"),
                 transcripts, onscreen, " ".join(shots))


def _visual_text(f: dict) -> str:
    """只看画面/角色，不把口播里的“上身舒服”误判成真人出镜。"""
    style = f.get("style") or {}
    scene = f.get("scene") or {}
    roles = f.get("roles") or {}
    shots = []
    for s in f.get("timeline") or []:
        shots.append(_join(s.get("subject"), s.get("action"),
                           s.get("composition"), s.get("product")))
    return _join(style.get("global_style"), style.get("camera_language"),
                 scene.get("description"),
                 " ".join(shots),
                 json.dumps(roles.get("director") or {}, ensure_ascii=False),
                 json.dumps(roles.get("cinematographer") or {},
                            ensure_ascii=False))


def _person_visibility(f: dict, text: str) -> str:
    vtext = _visual_text(f)
    mannequin = any(x in vtext for x in (
        "臀模", "人体模型", "模特道具", "模特模型", "模型穿着", "模型展示"))
    no_person = any(x in vtext for x in ("无人物", "没有人物", "无人出镜"))
    live = any(x in vtext for x in (
        "女性", "真人出镜", "真人模特", "女主播", "主播出镜",
        "主播口播", "人物面对镜头", "人物中景", "真人试穿",
        "女性模特", "女生出镜"))
    positive = live or any(x in vtext for x in (
        "模特", "试穿", "对镜头", "半身", "全身"))
    side = any(x in vtext for x in ("侧身", "背影", "转身", "局部人物", "侧脸"))
    hand = any(x in vtext for x in ("双手", "手部", "手指", "手持", "手托",
                                    "手掌", "手腕", "单手"))
    if mannequin and not live:
        return "hands_only"
    if live:
        return "partial" if side else "full"
    if positive and not no_person:
        return "partial" if side else "full"
    if hand:
        return "hands_only"
    return "none"


def _shot_person_visibility(text: str, fallback: str) -> str:
    live = any(x in text for x in (
        "女性", "真人出镜", "真人模特", "女主播", "主播出镜",
        "主播口播", "人物面对镜头", "人物中景", "真人试穿",
        "女性模特", "女生出镜"))
    hand = any(x in text for x in ("双手", "手部", "手指", "手持", "手托",
                                   "手掌", "手腕", "单手"))
    if live:
        return "partial" if any(x in text for x in ("侧身", "背影", "转身", "侧脸")) else "full"
    if hand:
        return "hands_only"
    if any(x in text for x in ("静态", "平铺", "陈列", "无人", "没有人物")):
        return "none"
    return fallback


def _presenter_mode(f: dict, text: str, person: str) -> str:
    transcript = (f.get("text") or {}).get("transcript") or []
    onscreen = (f.get("text") or {}).get("by_shot") or []
    has_speech = sum(len(str(x.get("text") or "")) for x in transcript) > 20
    if has_speech:
        direct = person in ("full", "partial") and any(
            x in text for x in ("口播", "对镜头", "讲解", "主播", "面向镜头"))
        return "direct_speech" if direct else "voiceover"
    if any(str(x.get("on_screen_text") or "").strip() for x in onscreen):
        return "text_only"
    return "ambient"


def _camera_family(camera: str) -> str:
    if "多机位" in camera or "交替" in camera or "切换" in camera:
        return "multi"
    if "手持" in camera:
        return "handheld"
    if "俯拍" in camera or "桌面" in camera:
        return "tabletop"
    if any(x in camera for x in ("推", "拉", "跟拍", "运镜", "移动")):
        return "moving"
    if any(x in camera for x in ("微距", "特写")):
        return "macro"
    return "static"


def _scene_family(scene: str) -> str:
    if any(x in scene for x in ("桌面", "台面", "平铺", "木质", "编织")):
        return "tabletop"
    if any(x in scene for x in ("户外", "停车场", "天台", "机场", "街")):
        return "outdoor"
    if any(x in scene for x in ("影棚", "背景墙", "纯色")):
        return "studio"
    return "home"


def _pacing_bucket(pacing: str) -> str:
    if any(x in pacing for x in ("缓慢", "慢", "均匀")):
        return "slow"
    if any(x in pacing for x in ("快", "急", "密集")):
        return "fast"
    return "medium"


def _text_density(f: dict, presenter: str) -> str:
    shots = f.get("timeline") or []
    texts = [x for x in ((f.get("text") or {}).get("by_shot") or [])
             if str(x.get("on_screen_text") or "").strip()]
    if presenter == "text_only":
        return "high"
    ratio = len(texts) / max(1, len(shots))
    if ratio >= 0.75:
        return "high"
    if ratio <= 0.25:
        return "low"
    return "medium"


def _tone(text: str) -> str:
    rules = (
        ("痛点否定", ("不要再", "别再", "宁愿", "后悔", "还好", "卡裆",
                      "尴尬", "闷", "勒")),
        ("朋友安利", ("姐妹", "家人们", "真的", "一定要", "听我")),
        ("价格直给", ("活动", "价格", "划算", "买", "冲", "下单")),
        ("结构评测", ("面料", "结构", "细节", "排扣", "支撑", "材质",
                      "版型", "肩带")),
    )
    for name, words in rules:
        if any(w in text for w in words):
            return name
    return "产品说明"


def _hook_type(hook: str) -> str:
    if any(x in hook for x in ("痛点", "不要再", "别再", "宁愿", "尴尬")):
        return "痛点否定"
    if any(x in hook for x in ("？", "?", "为什么", "怎么", "吗")):
        return "反问"
    if any(x in hook for x in ("还好", "发现", "找到", "救星")):
        return "发现/救星"
    if any(x in hook for x in ("价格", "活动", "划算")):
        return "价格钩子"
    if any(x in hook for x in ("细节", "特写", "颜色")):
        return "细节开场"
    return "产品亮相"


def _copy_person(text: str, presenter: str) -> str:
    if presenter in ("ambient", "text_only"):
        return "none"
    if any(x in text for x in ("测评", "实测", "对比")):
        return "reviewer"
    if any(x in text for x in ("姐妹", "家人们")):
        return "friend"
    if "我" in text:
        return "first_person"
    return "narrator"


def _sentence_style(f: dict) -> str:
    transcript = (f.get("text") or {}).get("transcript") or []
    texts = [str(x.get("text") or "") for x in transcript
             if str(x.get("text") or "").strip()]
    if texts:
        avg = sum(len(x) for x in texts) / len(texts)
        if avg < 12:
            return "短句口语"
        if avg < 22:
            return "口语短句"
        return "口语长句"
    onscreen = [str(x.get("on_screen_text") or "")
                for x in ((f.get("text") or {}).get("by_shot") or [])
                if str(x.get("on_screen_text") or "").strip()]
    avg = sum(len(x) for x in onscreen) / max(1, len(onscreen))
    return "关键词标签" if avg < 10 else "短句"


def _cta_style(cta: str) -> str:
    if any(x in cta for x in ("活动", "价格", "划算", "买", "下单")):
        return "活动价直给"
    if any(x in cta for x in ("点下方", "下方", "购物车")):
        return "下方引导"
    if any(x in cta for x in ("评论", "关注")):
        return "互动引导"
    return "轻收口"


def _evidence_refs(f: dict) -> list[str]:
    ref = f.get("ref_id")
    shots = f.get("timeline") or []
    if not shots:
        return [str(ref)]
    picks = sorted(set([0, len(shots) // 2, len(shots) - 1]))
    return [f"{ref}:shot:{shots[i].get('index', i + 1)}" for i in picks]


def _item(f: dict) -> dict:
    text = _facet_text(f)
    style = f.get("style") or {}
    scene = (f.get("scene") or {}).get("description") or ""
    st = f.get("structure") or {}
    visa = _person_visibility(f, text)
    pres = _presenter_mode(f, text, visa)
    camera = style.get("camera_language") or ""
    density = _text_density(f, pres)
    tone = _tone(text)
    hook = _hook_type(str(st.get("hook") or ""))
    cta = _cta_style(str(st.get("cta") or ""))
    copy_person = _copy_person(text, pres)
    sentence = _sentence_style(f)
    visual = {
        "person_visibility": visa,
        "presenter_mode": pres,
        "camera": camera,
        "camera_family": _camera_family(camera),
        "scene": scene,
        "scene_family": _scene_family(scene),
        "lighting": style.get("lighting") or "",
        "pacing": style.get("pacing") or "",
        "pacing_bucket": _pacing_bucket(str(style.get("pacing") or "")),
        "text_style": style.get("on_screen_text_style") or "",
        "text_density": density,
        "proof_style": st.get("proof") or "",
        "narrative_device": " → ".join(str(x) for x in
                                       (st.get("beat_order") or [])[:6]),
        "audio_design": {
            "direct_speech": "同期口播 + 场景底噪 + 轻 BGM",
            "voiceover": "画外口播 + 场景底噪 + 轻 BGM",
            "ambient": "无口播 + 环境音/操作音 + 轻 BGM",
            "text_only": "无口播 + 轻 BGM/音效，字幕承载信息",
        }.get(pres, "按风格配声音"),
    }
    transcript = (f.get("text") or {}).get("transcript") or []
    onscreen = (f.get("text") or {}).get("by_shot") or []
    text_by_shot = {int(x.get("index") or 0): str(x.get("on_screen_text") or "")
                    for x in onscreen}
    shot_styles = []
    for s in f.get("timeline") or []:
        idx = int(s.get("index") or 0)
        stext = _join(s.get("subject"), s.get("action"),
                      s.get("composition"), s.get("product"))
        sc = str(s.get("camera") or camera)
        shot_styles.append({
            "index": idx,
            "time": s.get("time"),
            "person_visibility": _shot_person_visibility(stext, visa),
            "camera_family": _camera_family(sc),
            "scene_family": _scene_family(scene),
            "text_present": bool(text_by_shot.get(idx, "").strip()),
            "shot_size": s.get("shot_size"),
            "action": str(s.get("action") or "")[:80],
            "evidence_ref": f"{f.get('ref_id')}:shot:{idx}",
        })
    sample_hook = (transcript[0].get("text") if transcript else
                   (onscreen[0].get("on_screen_text") if onscreen else ""))
    sample_cta = (st.get("cta") or "")
    copy = {
        "tone": tone,
        "person": copy_person,
        "hook_type": hook,
        "sentence_style": sentence,
        "cta_style": cta,
        "text_density": density,
        "sample_hook": str(sample_hook or "")[:40],
        "sample_cta": str(sample_cta or "")[:60],
    }
    return {
        "ref_id": f.get("ref_id"),
        "title": (f.get("meta") or {}).get("title") or "",
        "category": (f.get("meta") or {}).get("category") or "",
        "duration": (f.get("meta") or {}).get("duration"),
        "visual": visual,
        "copy": copy,
        "shot_styles": shot_styles,
        "visual_signature": {k: visual[k] for k in VISUAL_WEIGHTS},
        "copy_signature": {k: copy[k] for k in COPY_WEIGHTS},
        "evidence_refs": _evidence_refs(f),
        "source": {
            "facet": f"data/reference_facets/{f.get('ref_id')}.json",
            "source_sha256": (f.get("provenance") or {}).get("source_sha256"),
        },
    }


def build_style_atlas(facets_dir: Path | None = None) -> dict:
    d = facets_dir or FACETS_DIR
    items = []
    for p in sorted(d.glob("ref-*.json")):
        try:
            f = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(f, dict) and f.get("ref_id"):
            items.append(_item(f))
    counts = {
        "person_visibility": dict(Counter(
            x["visual"]["person_visibility"] for x in items)),
        "presenter_mode": dict(Counter(
            x["visual"]["presenter_mode"] for x in items)),
        "camera_family": dict(Counter(
            x["visual"]["camera_family"] for x in items)),
        "scene_family": dict(Counter(
            x["visual"]["scene_family"] for x in items)),
        "tone": dict(Counter(x["copy"]["tone"] for x in items)),
        "cta_style": dict(Counter(x["copy"]["cta_style"] for x in items)),
    }
    return {
        "schema_version": "style-atlas/v0",
        "generated_at": int(time.time()),
        "count": len(items),
        "counts": counts,
        "items": items,
        "provenance": {"facets_dir": str(d.relative_to(ROOT))},
    }


def _distance(a: dict, b: dict, weights: dict, sig_key: str) -> float:
    total = sum(weights.values())
    if not total:
        return 0.0
    diff = sum(w for k, w in weights.items()
               if (a.get(sig_key) or {}).get(k) != (b.get(sig_key) or {}).get(k))
    return round(diff / total, 4)


def visual_distance(a: dict, b: dict) -> float:
    return _distance(a, b, VISUAL_WEIGHTS, "visual_signature")


def copy_distance(a: dict, b: dict) -> float:
    return _distance(a, b, COPY_WEIGHTS, "copy_signature")
