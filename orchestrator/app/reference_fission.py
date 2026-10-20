"""参考案例 -> 约束模板 -> 5 条裂变素材（decoder + 生成 + 校验）。

流程：
  reference_retrieval.build_reference_brief()
    -> make_variant_briefs()        # 5 个方向
    -> product_video.plan.create()  # 复用现有 DirectorPlan/H3 编译
    -> pipeline.run()               # H3 生成
    -> validate_output()            # DeepSeek 视觉硬约束校验
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path

from . import config as C, llm, media, minimax, store
from .jsonutil import extract_json
from . import reference_pool, reference_retrieval
from pipelines.product_video import plan as pvplan, pipeline

log = logging.getLogger("reference_fission")

RUNS_DIR = C.ROOT / "data" / "reference_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

PRODUCT_DESC = (
    "奶白色/象牙白蕾丝无钢圈文胸。花卉刺绣蕾丝罩杯，金色/香槟金包边，"
    "前中桃色小蝴蝶结，下摆蕾丝花边，背面四排扣，软支撑无钢圈，立体杯型。"
)
PERSON_DESC = (
    "参考图1中的短发亚洲女性，保留脸型、发型、体型和肤色；"
    "不要复制她原有的运动内衣、短裤、鞋子。"
)
HARD_CONSTRAINTS = [
    "商品颜色不可变（奶白/象牙白）",
    "商品材质/蕾丝花纹不可变",
    "商品版型/杯型不可变",
    "金色包边与桃色蝴蝶结位置不可变",
    "背面四排扣结构不可变",
    "不新增商品图之外的服装部件",
    "无口播、无字幕、无品牌 logo、无额外人物",
    "9:16，4-15 秒，快节奏、正常速度",
]
PRODUCT_EVIDENCE = [
    "正面罩杯与花卉蕾丝纹理",
    "金色/香槟金包边",
    "前中桃色蝴蝶结",
    "背面四排扣",
    "内里无钢圈/软支撑结构",
]


def _log(msg: str):
    log.info(msg)
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _progress(cb, phase: str, current: int = 0, total: int = 0, **extra):
    if not cb:
        return
    try:
        cb(phase, current, total, **extra)
    except Exception:
        pass


def _run(cmd: list[str], timeout: int = 180):
    import subprocess
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])


def prepare_product_image(ref_id: str, t: float, out: Path) -> dict:
    items = {x.get("id"): x for x in reference_pool.list_items()}
    ref = items.get(ref_id)
    if not ref:
        raise ValueError(f"参考池没有: {ref_id}")
    video = Path(ref["path"])
    if not video.is_absolute():
        video = C.ROOT / video
    out.parent.mkdir(parents=True, exist_ok=True)
    full = out.parent / "product_frame.jpg"
    _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i",
          str(video), "-frames:v", "1", "-q:v", "2", str(full)])
    # 居中裁剪商品区域；保留手部作为“手持展示”的语境，提示词会声明忽略
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(full), "-vf",
          "crop=iw*0.88:ih*0.44:iw*0.06:ih*0.20,scale=720:-1",
          "-q:v", "2", str(out)])
    return {"ref_id": ref_id, "video": str(video), "time": t,
            "frame": str(full), "product_image": str(out)}


def _fallback_variants() -> list[dict]:
    return [
        {"name": "痛点反问", "hook": "不要再穿钢圈内衣了",
         "concept": "用一句痛点反问开场，直接切到无钢圈软支撑与蕾丝细节。",
         "beat_order": ["痛点反问", "产品特写", "柔软挤压", "无钢圈结构", "结尾"],
         "camera": "固定近景 + 手部快速演示",
         "lighting": "暖色柔光，背景虚化",
         "product_evidence": PRODUCT_EVIDENCE[:4],
         "on_screen_text": "无", "pacing": "快", "negative": []},
        {"name": "材质证明", "hook": "极近特写蕾丝纹理",
         "concept": "用微距和手拉回弹证明面料细腻、柔软、不扎。",
         "beat_order": ["蕾丝微距", "手拉回弹", "金边细节", "内里结构", "结尾"],
         "camera": "微距横移 + 近景推拉",
         "lighting": "侧逆光突出纹理",
         "product_evidence": PRODUCT_EVIDENCE[:3],
         "on_screen_text": "无", "pacing": "快", "negative": []},
        {"name": "结构拆解", "hook": "正面罩杯与四排扣",
         "concept": "像拆解产品一样依次展示正面、背面、肩带、内里。",
         "beat_order": ["正面罩杯", "背面四排扣", "肩带/侧翼", "内里软支撑", "结尾"],
         "camera": "固定近景 + 快速翻转",
         "lighting": "均匀柔光",
         "product_evidence": PRODUCT_EVIDENCE,
         "on_screen_text": "无", "pacing": "快", "negative": []},
        {"name": "对比实验", "hook": "普通内衣 vs 这件",
         "concept": "用手势和画面分区做对比，强调无钢圈、不勒、软支撑。",
         "beat_order": ["对比手势", "产品特写", "柔软证明", "无钢圈结构", "结尾"],
         "camera": "固定中近景 + 手部动作",
         "lighting": "明亮柔光",
         "product_evidence": PRODUCT_EVIDENCE[:4],
         "on_screen_text": "无", "pacing": "快", "negative": []},
        {"name": "晨间种草", "hook": "晨间衣柜前的选择",
         "concept": "用晨间通勤场景带出产品，落在舒适、无痕、不勒。",
         "beat_order": ["场景开场", "产品揭晓", "上身展示", "细节证明", "结尾"],
         "camera": "中景 + 近景切换",
         "lighting": "自然窗光",
         "product_evidence": PRODUCT_EVIDENCE[:3],
         "on_screen_text": "无", "pacing": "快", "negative": []},
    ]


def make_variant_briefs(template: dict, n: int = 5) -> list[dict]:
    prompt = f"""参考案例库归纳出的约束模板：
{json.dumps(template, ensure_ascii=False, indent=1)}

商品：{PRODUCT_DESC}
人物：{PERSON_DESC}

请生成 {n} 个真正不同的裂变方向。要求：
- 差异必须体现在 hook、叙事结构、证明方式或观看方式上，不是换形容词；
- 每个方向都保留硬约束：{json.dumps(HARD_CONSTRAINTS, ensure_ascii=False)}；
- 每个方向至少覆盖 3 个商品画面证据：{json.dumps(PRODUCT_EVIDENCE, ensure_ascii=False)}；
- 9:16、8-12 秒、快节奏、无口播、无字幕；
- 只输出 JSON：
{{"variants":[{{"name":"","hook":"","concept":"","beat_order":[],"camera":"","lighting":"","product_evidence":[],"on_screen_text":"","pacing":"","negative":[]}}]}}"""
    try:
        txt = llm.LLM(model=C.env("REFERENCE_LLM_MODEL", "deepseek-chat"), timeout=180).chat(
            prompt, max_tokens=5000, temperature=0.75, json_mode=True)
        data = extract_json(txt) or {}
        variants = data.get("variants") or []
        if isinstance(variants, list) and len(variants) >= 2:
            return variants[:n]
    except Exception as e:
        log.warning("裂变方向生成失败，使用兜底: %s", e)
    return _fallback_variants()[:n]


def intent_for(variant: dict, template: dict) -> str:
    return f"""这是一条从参考视频池裂变出来的带货素材。

商品：{PRODUCT_DESC}
人物：{PERSON_DESC}
参考图顺序：参考图1=固定人物照片1（只负责人物身份）；参考图2=商品图1（只负责商品本身，忽略图中的手、背景、文字）。
参考图2中有手在托举商品，这是拍摄语境；不要复制那只手，也不要复制背景花朵/纱帘。

本条方向：{variant.get('name')} · {variant.get('concept')}
hook：{variant.get('hook')}
beat_order：{' → '.join(map(str, variant.get('beat_order') or []))}
camera：{variant.get('camera')}
lighting：{variant.get('lighting')}
product_evidence：{json.dumps(variant.get('product_evidence') or PRODUCT_EVIDENCE, ensure_ascii=False)}

参考案例库的硬约束：
{json.dumps(HARD_CONSTRAINTS, ensure_ascii=False)}

制作要求：
- 4-6 个逻辑分镜，总时长 12 秒左右，H3 单次生成；每镜 2-4 秒。
- 第 1 镜 1 秒内出现商品或商品动作；每个镜头至少一个商品画面证据。
- 快节奏、正常速度；禁止慢动作、慢速推拉。
- 无口播、无字幕、无品牌 logo、无额外人物。
- 商品必须保持：奶白色蕾丝、金色包边、桃色蝴蝶结、四排扣、无钢圈软支撑；不得变形、变色、增减部件。
- 人物只负责身份与穿着展示；不要复制人物照片里原有的运动内衣/短裤。
- 9:16 竖屏，真实质感商业广告，暖色柔光或自然窗光。"""


def harden_plan(plan: dict) -> dict:
    c = plan.setdefault("constraints", {})
    product = c.setdefault("product", {})
    product["must_show"] = list(PRODUCT_EVIDENCE)
    product["must_not_change"] = [
        "颜色", "版型", "材质", "蕾丝花纹", "金色包边",
        "蝴蝶结位置", "四排扣结构",
    ]
    product["wear_state"] = "正常穿着，不反穿，不遮挡关键细节"
    product["matching"] = "不新增商品图之外的服装部件"
    g = c.setdefault("global", {})
    g["no_voiceover"] = True
    g["aspect_ratio"] = "9:16"
    g["duration"] = min(15, max(4, int(g.get("duration") or 12)))
    neg = list(plan.get("negative") or [])
    for x in ["不要出现钢圈", "不要改变商品颜色", "不要改变蕾丝花纹",
              "不要新增商品图之外的服装部件", "不要出现品牌logo",
              "不要出现字幕", "不要口播"]:
        if x not in neg:
            neg.append(x)
    plan["negative"] = neg
    try:
        plan = pvplan.compile_plan(plan)
    except Exception as e:
        log.warning("重编译失败，保留原 plan: %s", e)
    return pvplan.save(plan)


def _product_only_subjects() -> list[dict]:
    return [{
        "symbol": "<Product 1>", "ref": "参考图1",
        "identity": "奶白色蕾丝无钢圈文胸",
        "immutable": ["奶白/象牙白色", "花卉蕾丝花型与密度",
                      "金色/香槟金包边", "前中桃色蝴蝶结",
                      "背面四排扣结构", "无钢圈软支撑"],
    }]


def _product_only_retention(n_shots: int) -> list[dict]:
    return [{
        "symbol": "<Product 1>",
        "shots": list(range(1, n_shots + 1)),
        "preserved": ["奶白色", "蕾丝花型", "金色包边",
                      "桃色蝴蝶结", "四排扣", "无钢圈软支撑"],
    }]


def _product_only_constraints(duration: int) -> dict:
    return {
        "identity": {
            "subject": "<Product 1>", "face_consistency": False,
            "wardrobe_lock": True, "forbidden": [],
        },
        "performance": {
            "require_face_arc": False, "min_expression_changes": 1,
            "require_gaze_change": False, "require_breath": False,
            "require_secondary_motion": ["布料"], "forbidden": [],
        },
        "product": {
            "symbol": "<Product 1>", "must_show": list(PRODUCT_EVIDENCE),
            "must_not_change": ["奶白色", "版型", "蕾丝花型",
                                "金色包边", "桃色蝴蝶结", "四排扣结构"],
            "wear_state": "平铺/手持展示，不反折遮挡关键细节",
            "matching": "不新增商品图之外的服装部件",
        },
        "global": {
            "duration": duration, "aspect_ratio": "9:16",
            "no_voiceover": True, "fast_pacing": True, "max_subjects": 1,
        },
    }


def _order_from_beat_order(variant: dict) -> list[str]:
    """把变体里的 beat_order 映射到 4 个固定镜头模块的播放顺序。"""
    order: list[str] = []
    for step in variant.get("beat_order") or []:
        s = str(step)
        key = None
        if any(k in s for k in ("材质", "蕾丝", "微距", "手感", "面料")):
            key = "material"
        elif any(k in s for k in ("结构", "背面", "四排扣", "内里",
                                  "肩带", "侧翼", "软支撑", "无钢圈")):
            key = "structure"
        elif any(k in s for k in ("结尾", "CTA", "购买", "收尾")):
            key = "end"
        elif any(k in s for k in ("痛点", "hook", "反问", "开场", "钩子")):
            key = "hook"
        if key and key not in order:
            order.append(key)
    for key in ("hook", "material", "structure", "end"):
        if key not in order:
            order.append(key)
    # 结尾永远放最后
    order = [k for k in order if k != "end"] + ["end"]
    return order


def _controlled_shots(variant: dict) -> list[dict]:
    ev = list(variant.get("product_evidence") or PRODUCT_EVIDENCE)
    while len(ev) < 5:
        ev.append(PRODUCT_EVIDENCE[len(ev) % len(PRODUCT_EVIDENCE)])
    camera = variant.get("camera") or "固定近景 + 手部快速演示"
    lighting = variant.get("lighting") or "明亮暖光，背景虚化"
    hook = variant.get("hook") or "前 1 秒产品特写"
    concept = variant.get("concept") or "产品结构证明"
    rows = {
        "hook": ("视觉钩子", camera, lighting,
                 f"{hook}；双手托举产品正面入画，展示{ev[0]}与{ev[1]}",
                 "产品正面特写，手刚入画", "产品完整正面，蝴蝶结与金边同框",
                 [ev[0], ev[1]], "硬切"),
        "material": ("材质特写", "微距横移 + 近景推拉", "侧逆光突出蕾丝纹理",
                     f"手指轻拉蕾丝与金色包边，展示{ev[0]}的纹理与回弹",
                     "承接上一镜，镜头贴近蕾丝", "纹理与回弹清晰定格",
                     [ev[0], ev[1], ev[2]], "硬切"),
        "structure": ("结构证明", "固定近景 + 快速翻转", "均匀柔光，产品清晰",
                      f"翻转产品，依次展示{ev[3]}与{ev[4]}",
                      "承接上一镜，手开始翻转", "背面结构与内里完整入画",
                      [ev[3], ev[4]], "硬切"),
        "end": ("结尾卡", "正面固定近景，轻微推近", "明亮柔光，干净背景",
                f"产品正面完整定格，展示{ev[0]}、{ev[1]}与{ev[2]}",
                "承接上一镜，产品回到正面", "产品正面完整定格",
                [ev[0], ev[1], ev[2]], "结尾定格/淡出"),
    }
    order = _order_from_beat_order(variant)
    shots = []
    for i, key in enumerate(order, 1):
        fn, cam, light, action, start, end, evidence, cut = rows[key]
        desc = f"{cam}。{light}。{action}。"
        shots.append({
            "index": i, "duration": 3, "shot_function": fn,
            "person_present": False,
            "camera": cam, "lighting": light,
            "person_action": "无人物，仅手部入画",
            "product_action": action,
            "start_state": start, "end_state": end,
            "cut_to_next": cut,
            "face_arc": {},
            "product_evidence": evidence,
            "prompt_hint": concept,
            "on_screen_text": "",
            "beats": [{"time": [0, 3], "description": desc}],
        })
    return shots


def _product_only_intent(variant: dict, template: dict) -> str:
    return f"""这是从参考视频池裂变出来的一条产品展示素材。

商品：{PRODUCT_DESC}
参考图1=商品图1（只负责商品本身；忽略图中的手、背景、文字和原有字幕）。
画面以产品特写/手部演示为主，不需要真人出镜。

本条方向：{variant.get('name')} · {variant.get('concept')}
hook：{variant.get('hook')}
beat_order：{' → '.join(map(str, variant.get('beat_order') or []))}
camera：{variant.get('camera')}
lighting：{variant.get('lighting')}
product_evidence：{json.dumps(variant.get('product_evidence') or PRODUCT_EVIDENCE, ensure_ascii=False)}

硬约束：
{json.dumps(HARD_CONSTRAINTS, ensure_ascii=False)}

制作要求：
- 4 个逻辑分镜，总时长 12 秒，H3 单次生成；每镜 3 秒。
- 第 1 镜 1 秒内出现商品；每个镜头至少一个商品画面证据。
- 快节奏、正常速度；禁止慢动作、慢速推拉。
- 无口播、无字幕、无品牌 logo、无人物出镜。
- 商品必须保持：奶白色蕾丝、金色包边、桃色蝴蝶结、四排扣、无钢圈软支撑；不得变形、变色、增减部件。
- 明亮、真实质感商业广告；不要暗调、不要门缝/实验性概念。
- 9:16 竖屏。"""


def build_controlled_plan(variant: dict, template: dict, product: str,
                          duration: int = 12) -> dict:
    intent = _product_only_intent(variant, template)
    shots = _controlled_shots(variant)
    spec = {
        "title": variant.get("name") or "产品展示",
        "interpretation": {
            "idea": variant.get("concept") or "产品结构证明",
            "reading": "用可见的商品结构证明卖点，快节奏、无口播。",
            "motif": variant.get("name") or "",
            "visual_carrier": "奶白蕾丝、金色包边、桃色蝴蝶结、四排扣",
            "visual_thesis": "观众记住奶白蕾丝、金色包边和桃色蝴蝶结。",
            "visual_language": {
                "质感": "真实商业广告，产品清晰",
                "节奏": "快节奏、正常速度",
                "光": variant.get("lighting") or "明亮暖光",
            },
            "render_base": "真实质感，正常速度，浅景深，产品清晰，无滤镜过度",
            "assumptions": ["产品图来自参考视频静帧，忽略图中的手与背景"],
            "directions": [
                {"name": variant.get("name") or "方向 A",
                 "concept": variant.get("concept") or "",
                 "why": "参考案例库归纳出的可执行结构",
                 "cost": "产品展示为主，叙事性较弱"},
                {"name": "直接展示",
                 "concept": "正面特写 → 材质 → 结构 → 结尾",
                 "why": "最稳的商品证据路径",
                 "cost": "变化较少"},
            ],
            "chosen": 0,
        },
        "subject_definitions": _product_only_subjects(),
        "retention": _product_only_retention(len(shots)),
        "constraints": _product_only_constraints(duration),
        "shots": shots,
        "negative": [
            "无口播", "无字幕", "无文字", "无品牌logo", "无多余人物",
            "商品不变形", "手部结构稳定", "不要慢动作", "不要慢速推拉",
            "不要新增商品图之外的服装部件", "不要出现钢圈",
            "不要改变商品颜色", "不要改变蕾丝花纹",
        ],
        "meta": {
            "duration": duration, "aspect_ratio": "9:16",
            "style": "明亮商业产品广告",
            "visual_concept": variant.get("concept") or "",
            "hook": variant.get("hook") or "",
            "pacing": "fast",
            "rhythm": "4 次快切，前 1 秒出商品，结尾定格",
            "bgm_style": "", "sound_policy": "无口播、无台词；只有环境底噪与 BGM",
        },
    }
    plan = pvplan._assemble(
        intent, spec, [], [product], [], duration, "9:16", "768P",
        None, pacing="fast")
    plan = pvplan.compile_plan(plan)
    plan["fission_variant"] = variant
    plan["fission_template"] = template
    return pvplan.save(plan)


def create_plans(variants: list[dict], template: dict,
                 person: str, product: str,
                 duration: int = 12, progress_cb=None) -> list[dict]:
    plans = []
    for i, v in enumerate(variants, 1):
        _log(f"生成方案 {i}/{len(variants)} · {v.get('name')}")
        _progress(progress_cb, "planning", i - 1, len(variants))
        try:
            plan = build_controlled_plan(v, template, product, duration)
            plans.append(plan)
            _log(f"方案 {i} 完成: {plan.get('id')} · {plan.get('title')} "
                 f"· shots={len(plan.get('shots') or [])}")
        except Exception as e:
            log.exception("受控方案 %s 失败，回退到 plan.create", i)
            try:
                intent = intent_for(v, template)
                plan = pvplan.create({
                    "intent": intent,
                    "person_photos": [person],
                    "product_images": [product],
                    "background_images": [],
                    "duration": duration,
                    "aspect_ratio": "9:16",
                    "resolution": "768P",
                    "pacing": "fast",
                    "bgm": None,
                })
                plan = harden_plan(plan)
                plan["fission_variant"] = v
                plan["fission_template"] = template
                plans.append(plan)
                _log(f"方案 {i} 回退完成: {plan.get('id')} · {plan.get('title')}")
            except Exception as e2:
                log.exception("方案 %s 最终失败", i)
                plans.append({"id": None,
                              "error": f"{type(e2).__name__}: {e2}",
                              "variant": v})
    _progress(progress_cb, "planning", len(variants), len(variants))
    return plans


def run_plans(plans: list[dict], run_dir: Path,
              bgm: str | None = None, progress_cb=None) -> list[dict]:
    out_dir = run_dir / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, plan in enumerate(plans, 1):
        if not plan.get("id"):
            results.append({"index": i, "ok": False,
                            "error": plan.get("error")})
            _progress(progress_cb, "generating", i, len(plans))
            continue
        pid = plan["id"]
        _log(f"生成视频 {i}/{len(plans)} · {pid}")
        _progress(progress_cb, "generating", i - 1, len(plans),
                  plan_id=pid, title=plan.get("title"))
        jid = store.job_create("product_video", {
            "plan_id": pid, "title": plan.get("title"), "fission": True,
        })
        try:
            pipeline.run(pid, jid, bgm)
            res = store.job_result(jid)
            item = res.get("item")
            dst = out_dir / f"variant_{i:02d}.mp4"
            if item and Path(item).exists():
                shutil.copy2(item, dst)
                results.append({"index": i, "ok": True, "plan_id": pid,
                                "job": jid, "video": str(dst),
                                "review_item": item})
                _log(f"视频 {i} 完成 -> {dst}")
            else:
                results.append({"index": i, "ok": False, "plan_id": pid,
                                "job": jid, "error": "未找到产出",
                                "result": res})
        except Exception as e:
            status = "unknown" if minimax.is_ambiguous_error(e) else "error"
            try:
                store.job_finish(jid, status, {"error": str(e)})
            except Exception:
                pass
            results.append({"index": i, "ok": False, "plan_id": pid,
                            "job": jid, "error": f"{type(e).__name__}: {e}"})
            _log(f"视频 {i} 失败: {e}")
        _progress(progress_cb, "generating", i, len(plans))
    return results


def _extract_frames(video: Path, out_dir: Path, n: int = 4) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = media.ffprobe_duration(video) or 10
    frames = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        p = out_dir / f"frame_{i + 1}.jpg"
        try:
            _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}",
                  "-i", str(video), "-frames:v", "1",
                  "-vf", "scale=560:-1", "-q:v", "3", str(p)])
            if p.exists():
                frames.append(p)
        except Exception as e:
            log.warning("校验抽帧失败: %s", e)
    return frames


def validate_output(video: Path, product_image: Path, out_dir: Path,
                    idx: int, extra_images: list[Path] | None = None) -> dict:
    frames = _extract_frames(video, out_dir / f"validation_{idx:02d}")
    if not frames:
        return {"index": idx, "ok": False, "error": "没有抽到校验帧"}
    refs = [product_image] + [p for p in (extra_images or []) if p.exists()]
    ref_n = len(refs)
    extra_line = ("图2-{}是商品背面/内里参考图。".format(ref_n)
                  if ref_n > 1 else "没有额外商品视角图。")
    prompt = f"""图1是商品正面参考图（只关注文胸本身，忽略图中的手、背景、文字）。
{extra_line}
图{ref_n + 1}-{ref_n + len(frames)}是生成视频的帧。请判断生成视频是否保持商品身份与硬约束。
只输出 JSON：
{{"product_present": true, "identity_match": 0, "color_match": 0,
 "detail_match": 0, "product_visibility": "full|partial|none",
 "extra_garments": [], "on_screen_text": [], "issues": [],
 "verdict": "pass|fail"}}
评分 0-10；identity_match 看版型/杯型/蕾丝结构，color_match 看奶白色与金边，
detail_match 看蝴蝶结/包边/四排扣。商品不出现或严重变形直接 fail。"""
    try:
        txt = llm.LLM(model=C.env("REFERENCE_LLM_MODEL", "deepseek-chat"), timeout=180).chat_vision(
            prompt, refs + frames, max_tokens=2500,
            temperature=0.1, json_mode=True)
        data = extract_json(txt) or {"raw": txt[:1000]}
    except Exception as e:
        data = {"error": f"{type(e).__name__}: {e}"}
    data["index"] = idx
    data["video"] = str(video)
    (out_dir / f"validation_{idx:02d}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def run_full(ref_id: str, product_time: float = 8.0,
             person: str = "assets/persons/半身照.png",
             n: int = 5, bgm: str | None = None,
             dry_run: bool = False, no_generate: bool = False,
             progress_cb=None) -> dict:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / f"fission-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _log(f"run_dir={run_dir}")
    _progress(progress_cb, "retrieving", 0, 1)

    product = prepare_product_image(ref_id, product_time,
                                    run_dir / "product.jpg")
    person_path = Path(person)
    if not person_path.is_absolute():
        person_path = C.ROOT / person_path
    if not person_path.is_file():
        raise FileNotFoundError(f"人物图不存在: {person}")

    query = ("奶白色蕾丝无钢圈文胸，抖音竖屏 9:16，快节奏，无口播，"
             "产品特写 / 手部演示 / 结构拆解 / 材质证明，带货素材裂变")
    brief = reference_retrieval.build_reference_brief(
        query, PRODUCT_DESC, k=12, run_dir=run_dir)
    _log(f"检索 {len(brief['docs'])} 条，模板结构 "
         f"{len((brief['template'] or {}).get('structure_options') or [])} 个")
    _progress(progress_cb, "retrieving", 1, 1,
              docs=len(brief["docs"]),
              structures=len((brief["template"] or {}).get("structure_options") or []))

    variants = make_variant_briefs(brief["template"], n=n)
    (run_dir / "brief.json").write_text(
        json.dumps({"query": query, "product": product,
                    "person": str(person_path),
                    "brief": brief, "variants": variants},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"裂变方向 {len(variants)} 个: " +
         ", ".join(str(v.get('name')) for v in variants))

    if dry_run:
        _progress(progress_cb, "done", 1, 1,
                  run_id=run_dir.name, dry_run=True)
        return {"run_dir": str(run_dir), "dry_run": True,
                "variants": variants, "template": brief["template"]}

    plans = create_plans(variants, brief["template"],
                         str(person_path), product["product_image"],
                         progress_cb=progress_cb)
    (run_dir / "plans.json").write_text(
        json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
    if no_generate:
        _progress(progress_cb, "done", len(plans), len(plans),
                  run_id=run_dir.name, no_generate=True)
        return {"run_dir": str(run_dir), "no_generate": True,
                "plans": [{"id": p.get("id"), "title": p.get("title"),
                           "variant": p.get("fission_variant"),
                           "error": p.get("error")} for p in plans]}

    results = run_plans(plans, run_dir, bgm=bgm,
                        progress_cb=progress_cb)
    validations = []
    for idx, r in enumerate(results, 1):
        if r.get("ok") and r.get("video"):
            _progress(progress_cb, "validating", idx - 1, len(results),
                      index=r.get("index"))
            v = validate_output(Path(r["video"]),
                                Path(product["product_image"]),
                                run_dir, r["index"])
            validations.append(v)
            _log(f"校验 {r['index']}: {v.get('verdict')} "
                 f"identity={v.get('identity_match')} "
                 f"color={v.get('color_match')} detail={v.get('detail_match')}")
        _progress(progress_cb, "validating", idx, len(results),
                  index=r.get("index"))
    summary = {"run_dir": str(run_dir), "product": product,
               "person": str(person_path), "query": query,
               "variants": variants, "plans": [
                   {"id": p.get("id"), "title": p.get("title"),
                    "variant": p.get("fission_variant"),
                    "error": p.get("error")} for p in plans],
               "results": results, "validations": validations,
               "created_at": int(time.time())}
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = export_run(run_dir, summary)
    summary["manifest"] = manifest
    summary["export_dir"] = manifest["export_dir"]
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # 把带 export 信息的 summary 同步到导出目录
    try:
        shutil.copy2(run_dir / "summary.json",
                     C.OUTPUTS / "fission" / run_dir.name / "summary.json")
    except Exception:
        pass
    _progress(progress_cb, "done", len(results), len(results),
              run_id=run_dir.name, export_dir=manifest["export_dir"])
    return summary


EXPORT_DIR = C.OUTPUTS / "fission"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def export_run(run_dir: Path, summary: dict) -> dict:
    """把一次裂变的 5 条视频/校验/清单复制到 outputs/fission/{run_id}/。"""
    export_dir = EXPORT_DIR / run_dir.name
    export_dir.mkdir(parents=True, exist_ok=True)
    for name in ("summary.json", "brief.json", "plans.json",
                 "product.jpg", "product_frame.jpg"):
        src = run_dir / name
        if src.exists():
            try:
                shutil.copy2(src, export_dir / name)
            except Exception:
                pass
    vals = {v.get("index"): v for v in summary.get("validations") or []}
    plans = summary.get("plans") or []
    items = []
    for r in summary.get("results") or []:
        if not r.get("ok") or not r.get("video"):
            continue
        i = r.get("index")
        src = Path(r["video"])
        if not src.is_file():
            continue
        dst = export_dir / f"variant_{i:02d}.mp4"
        try:
            shutil.copy2(src, dst)
        except Exception:
            continue
        v = vals.get(i, {})
        plan = next((p for p in plans
                     if p.get("id") == r.get("plan_id")), {})
        items.append({
            "index": i,
            "name": plan.get("title") or f"方向 {i}",
            "plan_id": r.get("plan_id"),
            "video": str(dst.relative_to(C.ROOT)),
            "verdict": v.get("verdict"),
            "identity": v.get("identity_match"),
            "color": v.get("color_match"),
            "detail": v.get("detail_match"),
            "product_present": v.get("product_present"),
            "visibility": v.get("product_visibility"),
            "issues": v.get("issues") or [],
        })
    product = dict(summary.get("product") or {})
    pimg = product.get("product_image")
    if pimg:
        p = Path(pimg)
        if p.is_file():
            dst = export_dir / "product.jpg"
            try:
                shutil.copy2(p, dst)
                product["product_image"] = str(dst.relative_to(C.ROOT))
            except Exception:
                pass
    manifest = {
        "run_id": run_dir.name,
        "created_at": summary.get("created_at") or int(time.time()),
        "product": product,
        "query": summary.get("query"),
        "items": items,
        "export_dir": str(export_dir.relative_to(C.ROOT)),
    }
    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def list_runs(limit: int = 30) -> list[dict]:
    out = []
    files = sorted(EXPORT_DIR.glob("*/manifest.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[:limit]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("读取裂变记录失败 %s: %s", p, e)
    return out


def load_run(run_id: str) -> dict:
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError("非法 run_id")
    p = EXPORT_DIR / run_id / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"裂变记录不存在: {run_id}")
    data = json.loads(p.read_text(encoding="utf-8"))
    sp = p.parent / "summary.json"
    if sp.exists():
        try:
            data["summary"] = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return data
