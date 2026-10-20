"""B 线：视觉编导型带货视频的 DirectorPlan 生成 / 存取 / 编译。

输入：意图文本 + 人物照片 + 商品图 +（可选）背景图
流程：
  1a 组合算子发散 8-12 个创意种子
  1b 归纳 3 个方向 → 选 1 个 → treatment + 硬约束
  2  3-6 个逻辑分镜（face_arc / product_evidence / cut_to_next）
  3a 整条 timeline 一次写细（五 lens）
  3b detail critic 评审
  3c 按 issues 重写
输出：一条连续视频 prompt；pipeline 一次 H3 请求生成，不再逐镜拆分。
无口播：不生成台词/TTS/唇形；声音只保留 BGM/音效。
"""
import json
import logging
import re
import time
import uuid
from pathlib import Path

from orchestrator.app import config as C
from orchestrator.app import llm
from . import director
from .director import DEFAULT_NEGATIVE, SHOT_FUNCS
from .text import fast_text as _fast_text

log = logging.getLogger("product_video")
PLANS_DIR = C.ROOT / "data" / "plans"
PLANS_DIR.mkdir(parents=True, exist_ok=True)



def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _int(v, default: int) -> int:
    try:
        return int(float(v))
    except Exception:
        return default


def _clean_paths(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [x.strip() for x in v if isinstance(x, str) and x.strip()]


def _path(p: str) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else C.ROOT / pp


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    # 优先找最外层最大的 JSON 对象；兼容前后夹带解释/markdown
    matches = re.findall(r"\{.*\}", text, re.S)
    for raw in sorted(matches, key=len, reverse=True):
        for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
    return None


def _fallback(intent: str, duration: int, aspect: str, reason: str = "") -> dict:
    """LLM 不可用时的兜底方案：5 镜快节奏，前 1 秒就出商品。"""
    shots = [
        {"index": 1, "duration": 3, "shot_function": "视觉钩子",
         "camera": "极近特写，快速拉远", "lighting": "硬光扫过商品表面，高光清晰",
         "person_action": "手部快速入画触碰商品", "product_action": "商品局部材质充满画面",
         "start_state": "商品局部特写，手指刚入画", "end_state": "商品完整轮廓露出，手停在商品上",
         "on_screen_text": "", "transition": "快速拉远接人物全景",
         "prompt_hint": "前1秒就露出商品；正常速度，动作干脆"},
        {"index": 2, "duration": 3, "shot_function": "产品揭晓",
         "camera": "中景，快速跟拍人物转身", "lighting": "柔和自然光",
         "person_action": "人物转身把商品完整展示给镜头", "product_action": "商品完整出现，随动作自然摆动",
         "start_state": "承接上一镜手部位置", "end_state": "人物正面半身，商品完整可见",
         "on_screen_text": "", "transition": "动作匹配剪辑到细节",
         "prompt_hint": "商品完整出现；不要新增下装/配饰；正常速度"},
        {"index": 3, "duration": 3, "shot_function": "材质特写",
         "camera": "微距横移，快速扫过面料", "lighting": "侧逆光打出纹理",
         "person_action": "手指轻拉面料", "product_action": "纹理、缝线、细节依次入画",
         "start_state": "承接上一镜商品位置", "end_state": "面料细节清晰定格",
         "on_screen_text": "", "transition": "快切到使用场景",
         "prompt_hint": "材质细节清晰；动作快，不要慢动作"},
        {"index": 4, "duration": 3, "shot_function": "使用演示",
         "camera": "中近景，跟随人物动作", "lighting": "明亮柔光",
         "person_action": "人物快速演示商品使用过程", "product_action": "商品在使用中展示关键卖点",
         "start_state": "承接上一镜细节", "end_state": "使用完成，人物看向镜头",
         "on_screen_text": "", "transition": "动作匹配剪辑到结尾",
         "prompt_hint": "用动作证明卖点；节奏快"},
        {"index": 5, "duration": 3, "shot_function": "结尾卡",
         "camera": "正面固定机位，快速推近", "lighting": "均匀柔光",
         "person_action": "人物站定微笑，展示整体造型", "product_action": "商品正面完整展示",
         "start_state": "承接上一镜人物位置", "end_state": "商品与人物完整定格",
         "on_screen_text": "", "transition": "干净收尾",
         "prompt_hint": "干净留白，商品完整；不要新增服装部件"},
    ]
    return {
        "title": "带货视频方案",
        "interpretation": {
            "idea": intent[:80],
            "reading": "LLM 不可用，采用模板兜底：以商品画面证据为主，"
                       "前1秒出商品，快节奏、无口播。",
            "motif": "",
            "visual_carrier": "",
            "visual_thesis": "",
            "style_axes": {
                "texture": "真实质感商业广告",
                "camera": "快节奏、正常速度",
                "light": "自然光",
            },
            "render_base": "",
            "assumptions": ["LLM 不可用，使用模板兜底"],
        },
        "subject_definitions": [],
        "retention": [],
        "meta": {
            "duration": sum(s["duration"] for s in shots),
            "aspect_ratio": aspect,
            "style": "真实质感商业广告",
            "visual_concept": intent[:80],
            "hook": "商品细节 + 快速拉远",
            "pacing": "fast",
            "rhythm": "前1秒商品钩子，3-4次快切，结尾干净",
            "bgm_style": "电子节拍/轻快",
            "fallback_reason": reason[:200],
        },
        "shots": shots,
        "negative": DEFAULT_NEGATIVE,
    }


def _ref_legend(person: list[str], product: list[str],
                background: list[str]) -> str:
    """参考图编号必须与实际提交顺序一致（compiler 按同一顺序收集 refs）。"""
    bits: list[str] = []
    for i in range(min(2, len(person))):
        bits.append(f"参考图{len(bits) + 1}=固定人物照片{i + 1}")
    for i in range(min(2, len(product))):
        bits.append(f"参考图{len(bits) + 1}=商品图{i + 1}")
    for i in range(min(1, len(background))):
        bits.append(f"参考图{len(bits) + 1}=背景图{i + 1}")
    return "，".join(bits)


def _json_call(system: str, user: str, max_tokens: int,
               temperature: float, label: str, retry_hint: str = "") -> dict | None:
    """每次尝试新建客户端(避免断连后的坏连接); 最多 3 次。"""
    last: Exception | None = None
    for attempt in range(3):
        try:
            txt = llm.LLM(timeout=180).chat(
                user if attempt == 0 else
                user + "\n" + (retry_hint or
                                "上一次输出不是合法 JSON 或过长。这次只输出 JSON，严格遵守给定结构。"),
                system, max_tokens=max_tokens,
                temperature=temperature if attempt == 0 else 0.25,
                json_mode=True)
            data = _extract_json(txt)
            if not data:
                log.warning("%s 原始输出(无 JSON): %s", label, txt[:900])
                raise ValueError(f"{label} JSON 解析失败")
            return data
        except Exception as e:
            last = e
            log.warning("%s 第 %d 次尝试失败: %s", label, attempt + 1, e)
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    log.warning("%s 最终失败: %s", label, last)
    return None


def _minimal_intent(intent: str) -> dict:
    """Pass 1 不可用时的最小解读: 保证后续仍能继续。"""
    return {
        "title": "带货视频方案",
        "directions": [{
            "name": "直接执行",
            "concept": intent[:60],
            "visual_language": "真实质感、快节奏、直接展示商品",
            "why": "意图模型不可用，采用最小解读",
        }],
        "chosen": 0,
        "treatment": {
            "idea": intent[:60],
            "reading": "按用户意图直接执行；以商品画面证据为主。",
            "motif": "",
            "visual_carrier": "",
            "visual_thesis": "",
            "visual_language": {
                "质感": "真实质感",
                "节奏": "快节奏",
                "光": "自然光",
            },
            "render_base": "真实质感，正常速度，快节奏",
            "assumptions": ["意图解读模型不可用，使用最小解读"],
        },
        "meta": {},
    }


def _apply_timeline(shots: list[dict], timeline: list[dict]):
    """把 Pass 3 的 timeline 按 shot 号映射回逻辑分镜。"""
    by_shot: dict[int, list[dict]] = {}
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        try:
            si = int(entry.get("shot"))
        except (TypeError, ValueError):
            continue
        by_shot.setdefault(si, []).append(entry)
    for i, shot in enumerate(shots):
        try:
            idx = int(shot.get("index") or i + 1)
        except (TypeError, ValueError):
            idx = i + 1
        entries = by_shot.get(idx) or []
        if not entries:
            continue
        descs = [str(e.get("description") or "").strip() for e in entries]
        descs = [d for d in descs if d]
        if not descs:
            continue
        first, last = entries[0], entries[-1]
        shot["beats"] = [{
            "shot": idx,
            "time": first.get("time") or [0, shot.get("duration", 3)],
            "description": "\n\n".join(descs),
            "coverage": first.get("coverage") or [],
            "face_arc": first.get("face_arc") or shot.get("face_arc") or {},
            "product_evidence": first.get("product_evidence")
                               or shot.get("product_evidence") or [],
            "cut_to_next": last.get("cut_to_next")
                          or shot.get("cut_to_next") or "",
            "continuity": first.get("continuity") or {},
        }]
        shot["face_arc"] = shot["beats"][0]["face_arc"]
        shot["product_evidence"] = shot["beats"][0]["product_evidence"]
        shot["cut_to_next"] = shot["beats"][0]["cut_to_next"]


def _direct(intent: str, person: list[str], product: list[str],
            background: list[str], duration: int, aspect: str,
            pacing: str = "fast") -> dict:
    legend = _ref_legend(person, product, background)

    # Pass 1a: 组合式发散，8-12 个种子
    seed_user = f"""用户意图：{intent}
目标时长：{duration} 秒
画幅：{aspect}
请用组合算子输出 8-12 个创意种子。只输出 JSON。"""
    seed_data = _json_call(
        director.SEED_SYSTEM, seed_user,
        max_tokens=4000, temperature=0.95, label="创意种子",
        retry_hint="上一次输出不是合法 JSON 或过长。这次只输出 JSON；"
                   "8-12 个种子，至少 2 个反常规，保留每个种子的商品证据。")
    seeds = (seed_data or {}).get("seeds") if isinstance(seed_data, dict) else []
    if not isinstance(seeds, list):
        seeds = []

    # Pass 1b: 归纳 3 个方向 → 选 1 个 → treatment + 硬约束
    direction_user = f"""用户意图：{intent}
目标时长：{duration} 秒
画幅：{aspect}
节奏：{pacing}
创意种子：
{json.dumps(seeds, ensure_ascii=False, indent=1)}
请归纳 3 个真正不同的方向，选一个，输出 treatment/constraints/meta。只输出 JSON。"""
    intent_data = _json_call(
        director.DIRECTION_SYSTEM, direction_user,
        max_tokens=5000, temperature=0.65, label="方向与约束",
        retry_hint="上一次输出不是合法 JSON 或过长。这次只输出 JSON；"
                   "directions 3 个，constraints 完整，treatment 完整。")
    if not isinstance(intent_data, dict):
        intent_data = _minimal_intent(intent)
    if not isinstance(intent_data.get("treatment"), dict):
        raw = (intent_data.get("interpretation")
               if isinstance(intent_data.get("interpretation"), dict)
               else intent_data)
        intent_data = {**intent_data, "treatment": raw}
    treatment = intent_data.get("treatment") or _minimal_intent(intent)["treatment"]
    interp = director.normalize_interpretation(
        {**treatment, "directions": intent_data.get("directions"),
         "chosen": intent_data.get("chosen")}, intent)
    constraints_raw = intent_data.get("constraints") or {}
    meta = intent_data.get("meta") or {}

    # Pass 2: 逻辑分镜（不是独立生成任务）
    plan_user = f"""用户意图：{intent}
人物照片：{len(person)} 张
商品图：{len(product)} 张
背景图：{len(background)} 张
目标时长：{duration} 秒（H3 单次上限 15 秒）
画幅：{aspect}
节奏：{pacing}（fast=快节奏、正常速度、禁止慢动作、前1秒出商品）
参考图顺序（必须按此编号绑定，不要改动）：
{legend or "（无参考图）"}

treatment：
{json.dumps(interp, ensure_ascii=False, indent=1)}

constraints：
{json.dumps(constraints_raw, ensure_ascii=False, indent=1)}

请输出 subject_definitions/retention/shots/negative。3-6 个逻辑分镜，
总时长 12-15 秒，每镜 2-4 秒；每镜写 face_arc/product_evidence/cut_to_next。
这些是逻辑分镜，不是独立生成任务。只输出 JSON。"""
    data = _json_call(
        director.PLAN_SYSTEM, plan_user,
        max_tokens=5000, temperature=0.6, label="逻辑分镜",
        retry_hint="上一次输出不是合法 JSON 或过长。这次只输出 JSON；"
                   "3-6 个逻辑分镜，总时长 12-15 秒，每镜含 face_arc/"
                   "product_evidence/cut_to_next。")
    if not isinstance(data, dict):
        return _fallback(intent, duration, aspect, "逻辑分镜失败")
    if isinstance(data.get("plan"), dict):
        data = data["plan"]
    elif isinstance(data.get("result"), dict):
        data = data["result"]
    if not data.get("shots"):
        for key in ("分镜", "storyboard", "shot_list"):
            if isinstance(data.get(key), list):
                data["shots"] = data[key]
                break
    if not data.get("shots"):
        log.warning("逻辑分镜缺少 shots: %s", str(data)[:600])
        return _fallback(intent, duration, aspect, "逻辑分镜缺少 shots")

    shot_briefs = [dict(s) for s in data["shots"] if isinstance(s, dict)]

    # Pass 3a: 整条 timeline 一次写细
    timeline_user = f"""treatment：
{json.dumps(interp, ensure_ascii=False, indent=1)}

constraints：
{json.dumps(constraints_raw, ensure_ascii=False, indent=1)}

subject_definitions：
{json.dumps(data.get("subject_definitions") or [], ensure_ascii=False, indent=1)}

retention：
{json.dumps(data.get("retention") or [], ensure_ascii=False, indent=1)}

逻辑分镜：
{json.dumps(shot_briefs, ensure_ascii=False, indent=1)}

参考图顺序：
{legend or "（无参考图）"}

请一次写完整条 timeline。只输出 JSON。"""
    detail = _json_call(
        director.TIMELINE_SYSTEM, timeline_user,
        max_tokens=8192, temperature=0.7, label="整片时间轴",
        retry_hint="上一次输出不是合法 JSON 或过长。这次只输出 JSON；"
                   "减少到 3-4 个逻辑分镜，每段仍写细；保留 constraints。")
    timeline = (detail or {}).get("timeline") if isinstance(detail, dict) else []
    if not isinstance(timeline, list) or not timeline:
        log.warning("整片 timeline 生成失败，保留逻辑分镜总览")
        timeline = []
    else:
        _apply_timeline(shot_briefs, timeline)

    # Pass 3b: 细节评审
    critic = None
    if timeline:
        critic_user = f"""constraints：
{json.dumps(constraints_raw, ensure_ascii=False, indent=1)}

逻辑分镜：
{json.dumps(shot_briefs, ensure_ascii=False, indent=1)}

当前 timeline：
{json.dumps(timeline, ensure_ascii=False, indent=1)}

请检查空泛形容词、断因果、缺物理事实、face_arc 不可观察、商品证据不足、
must_not_change 违反、切镜不清、连续性断裂。只输出 JSON。"""
        critic = _json_call(
            director.CRITIC_SYSTEM, critic_user,
            max_tokens=6000, temperature=0.3, label="细节评审",
            retry_hint="上一次输出不是合法 JSON 或过长。这次只输出 issues/"
                       "missing_constraints/weak_shots/verdict。")
        if isinstance(critic, dict) and critic.get("verdict") == "revise" \
                and critic.get("issues"):
            rewrite_user = f"""constraints：
{json.dumps(constraints_raw, ensure_ascii=False, indent=1)}

当前 timeline：
{json.dumps(timeline, ensure_ascii=False, indent=1)}

critic issues：
{json.dumps(critic.get("issues"), ensure_ascii=False, indent=1)}

请按 issues 重写整条 timeline，只改有问题的部分。只输出 JSON。"""
            rewritten = _json_call(
                director.REWRITE_SYSTEM, rewrite_user,
                max_tokens=8192, temperature=0.6, label="评审重写",
                retry_hint="上一次输出不是合法 JSON 或过长。这次只输出 JSON；"
                           "修复 issues，保持 constraints 和逻辑分镜。")
            if isinstance(rewritten, dict) and rewritten.get("timeline"):
                timeline = rewritten["timeline"]
                _apply_timeline(shot_briefs, timeline)
                data["change_log"] = rewritten.get("change_log") or []
                if rewritten.get("director_notes"):
                    detail = {**(detail or {}),
                              "director_notes": rewritten["director_notes"]}
                if rewritten.get("self_check"):
                    detail = {**(detail or {}),
                              "self_check": rewritten["self_check"]}

    data["shots"] = shot_briefs
    data["seeds"] = seeds
    data["constraints"] = constraints_raw
    data["critic"] = critic or {}
    data["director_notes"] = (detail or {}).get("director_notes") or ""
    data["self_check"] = (detail or {}).get("self_check") or ""
    data["title"] = data.get("title") or intent_data.get("title") or "带货视频方案"
    data["interpretation"] = interp
    data["meta"] = {**meta, **(data.get("meta") or {})}
    return data


def _assemble(intent: str, spec: dict, person: list[str], product: list[str],
              background: list[str], duration: int, aspect: str,
              resolution: str, bgm: str | None,
              pacing: str = "fast") -> dict:
    meta = spec.get("meta") or {}
    interp = director.normalize_interpretation(spec.get("interpretation"), intent)
    raw_shots = (spec.get("shots") or [])[:7]
    shots = []
    for i, s in enumerate(raw_shots):
        if not isinstance(s, dict):
            continue
        func = (str(s.get("shot_function") or "").strip()
                or SHOT_FUNCS[min(i, len(SHOT_FUNCS) - 1)])
        shot_duration = max(2, min(4, _int(s.get("duration"), 3)))
        beats = director.normalize_beats(s.get("beats"), shot_duration)
        summary = director.summarize_shot(beats)
        face = s.get("face_arc") if isinstance(s.get("face_arc"), dict) else {}
        raw_evidence = s.get("product_evidence")
        if isinstance(raw_evidence, list):
            evidence = [str(x).strip() for x in raw_evidence if str(x).strip()]
        elif raw_evidence:
            evidence = [str(raw_evidence).strip()]
        else:
            evidence = []
        cut = str(s.get("cut_to_next") or s.get("transition") or "").strip()
        person_present = s.get("person_present", True)
        if isinstance(person_present, str):
            person_present = person_present.lower() not in ("false", "0", "no", "否")
        shots.append({
            "index": i + 1,
            "duration": shot_duration,
            "shot_function": func,
            "person_present": bool(person_present),
            "face_arc": {
                "start": str(face.get("start") or "").strip(),
                "turn": str(face.get("turn") or "").strip(),
                "end": str(face.get("end") or "").strip(),
            },
            "product_evidence": evidence,
            "cut_to_next": cut,
            "time": None,
            "camera": _fast_text(str(s.get("camera") or summary.get("camera") or "").strip()),
            "lighting": str(s.get("lighting") or summary.get("lighting") or "").strip(),
            "person_action": _fast_text(str(
                s.get("person_action") or summary.get("person_action") or "").strip()),
            "product_action": _fast_text(str(
                s.get("product_action") or summary.get("product_action") or "").strip()),
            "start_state": _fast_text(str(
                s.get("start_state") or summary.get("start_state") or "").strip()),
            "end_state": _fast_text(str(
                s.get("end_state") or summary.get("end_state") or "").strip()),
            "on_screen_text": str(s.get("on_screen_text") or "").strip(),
            "transition": cut or _fast_text(str(summary.get("transition") or "").strip()),
            "prompt_hint": _fast_text(str(
                s.get("prompt_hint") or summary.get("prompt_hint") or "").strip()),
            "beats": beats,
            "beat_plan": s.get("beat_plan") or [],
            "director_notes": str(s.get("director_notes") or "").strip(),
            "self_check": str(s.get("self_check") or "").strip(),
            "prompt": "",
            "refs": [],
            "status": "pending",
        })
    if not shots:
        fb = _fallback(intent, duration, aspect, "no shots")
        for i, s in enumerate(fb["shots"]):
            s.update(index=i + 1, prompt="", refs=[], status="pending")
        shots = fb["shots"]
        if not interp.get("reading"):
            interp = director.normalize_interpretation(
                fb.get("interpretation"), intent)

    # 一条视频一次生成：总时长压到 H3 上限 15 秒
    total_duration = sum(s["duration"] for s in shots)
    if total_duration > 15:
        factor = 15 / total_duration
        for shot in shots:
            shot["duration"] = max(2, round(shot["duration"] * factor, 1))
        total_duration = sum(s["duration"] for s in shots)
    cursor = 0.0
    for shot in shots:
        shot["time"] = [round(cursor, 2), round(cursor + shot["duration"], 2)]
        cursor += shot["duration"]
    total_duration = round(cursor, 2)

    subject_defs = director.normalize_subject_definitions(
        spec.get("subject_definitions"), person, product, background)
    retention = director.normalize_retention(
        spec.get("retention"), subject_defs, len(shots))
    constraints = director.normalize_constraints(
        spec.get("constraints"), subject_defs, total_duration, aspect)
    constraints["global"]["duration"] = min(15, max(4, round(total_duration)))
    negative = (director.normalize_negative(spec.get("negative"))
                or DEFAULT_NEGATIVE)
    meta_out = director.merge_meta(
        meta, interp, intent, total_duration, aspect, resolution, pacing)
    meta_out["generation_mode"] = "single"

    return {
        "id": f"pvplan-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}",
        "title": str(spec.get("title") or "带货视频方案")[:80],
        "intent": intent,
        "generation_mode": "single",
        "seeds": spec.get("seeds") or [],
        "interpretation": interp,
        "meta": meta_out,
        "constraints": constraints,
        "director_notes": str(spec.get("director_notes") or "").strip(),
        "self_check": str(spec.get("self_check") or "").strip(),
        "change_log": spec.get("change_log") or [],
        "critic": spec.get("critic") or {},
        "assets": {
            "person_photos": person[:5],
            "product_images": product[:6],
            "background_images": background[:3],
        },
        "subject_definitions": subject_defs,
        "retention": retention,
        "shots": shots,
        "negative": negative,
        "bgm": bgm or None,
        "status": "draft",
        "created_at": _now(),
        "updated_at": _now(),
    }


def create(req: dict) -> dict:
    """意图 + 素材 -> 完整的 DirectorPlan（已编译逐镜提示词）。"""
    intent = (req.get("intent") or "").strip()
    if not intent:
        raise ValueError("需要意图文本")
    person = _clean_paths(req.get("person_photos"))
    product = _clean_paths(req.get("product_images"))
    background = _clean_paths(req.get("background_images"))
    if not person:
        raise ValueError("至少上传 1 张人物照片")
    if not product:
        raise ValueError("至少上传 1 张商品图")
    for p in person + product + background:
        if not _path(p).is_file():
            raise ValueError(f"素材不存在: {p}")

    duration = _int(req.get("duration"), 15)
    aspect = str(req.get("aspect_ratio") or "9:16")
    resolution = str(req.get("resolution") or "768P")
    pacing = str(req.get("pacing") or "fast")
    spec = _direct(intent, person, product, background, duration, aspect,
                   pacing=pacing)
    plan = _assemble(intent, spec, person, product, background,
                     duration, aspect, resolution, req.get("bgm"),
                     pacing=pacing)
    return save(compile_plan(plan))


def _fit_timeline(plan: dict) -> float:
    """单次生成上限 15s：编辑后重新压时长并重算逻辑分镜时间轴。"""
    shots = plan.get("shots") or []
    total = sum(float(s.get("duration") or 0) for s in shots)
    if total > 15:
        factor = 15 / total
        for s in shots:
            s["duration"] = max(2, round(float(s.get("duration") or 3) * factor, 1))
    cursor = 0.0
    for s in shots:
        d = float(s.get("duration") or 3)
        s["time"] = [round(cursor, 2), round(cursor + d, 2)]
        cursor += d
    c = plan.get("constraints")
    if isinstance(c, dict):
        g = c.setdefault("global", {})
        g["duration"] = min(15, max(4, round(cursor)))
    return round(cursor, 2)


def compile_plan(plan: dict) -> dict:
    from .compiler import compile_shot, compile_video
    mode = (plan.get("generation_mode")
            or (plan.get("meta") or {}).get("generation_mode") or "per_shot")
    shots = plan.get("shots") or []
    for shot in shots:
        # 用户可能改过 duration：编译前把 beat 时间重新贴合镜头时长
        if shot.get("beats"):
            shot["beats"] = director.normalize_beats(
                shot["beats"], float(shot.get("duration") or 3))
    if mode == "single":
        total = _fit_timeline(plan)
        prompt, refs = compile_video(plan)
        plan["prompt"] = prompt
        plan["refs"] = refs
        for shot in shots:
            beat = (shot.get("beats") or [{}])[0]
            seg = str(beat.get("description") or "").strip()
            cut = str(shot.get("cut_to_next")
                      or beat.get("cut_to_next") or "").strip()
            shot["prompt"] = (seg + (f"\n切镜：{cut}" if cut else "")) if seg else ""
            shot["refs"] = refs
    else:
        for shot in shots:
            prompt, refs = compile_shot(plan, shot)
            shot["prompt"] = prompt
            shot["refs"] = refs
        total = sum(float(s.get("duration") or 0) for s in shots)
    meta = plan.setdefault("meta", {})
    meta["duration"] = int(total) if total == int(total) else total
    meta["generation_mode"] = mode
    plan["generation_mode"] = mode
    plan["lint"] = director.lint_plan(plan)
    lint = plan["lint"]
    if director.strict() and not (
            lint.get("ok") and lint.get("granularity_ok")
            and lint.get("constraints_ok", True)):
        detail = "；".join((lint.get("errors") or []) + (lint.get("warnings") or []))[:500]
        raise ValueError("提示词校验未通过（PV_PROMPT_LINT_STRICT=1）: " + detail)
    plan["updated_at"] = _now()
    return plan


def save(plan: dict) -> dict:
    pid = plan.get("id") or (
        f"pvplan-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}")
    plan["id"] = pid
    plan["updated_at"] = _now()
    (PLANS_DIR / f"{pid}.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def load(plan_id: str) -> dict:
    path = PLANS_DIR / f"{plan_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"方案不存在: {plan_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def update(plan_id: str, data: dict) -> dict:
    """前端编辑结构化字段后保存；不自动重编译，由 /compile 触发。"""
    plan = load(plan_id)
    for k in ("title", "intent", "generation_mode", "seeds",
              "interpretation", "meta", "constraints", "assets",
              "subject_definitions", "retention", "shots", "negative",
              "director_notes", "self_check", "change_log",
              "bgm", "status"):
        if k in data:
            plan[k] = data[k]
    plan["id"] = plan_id
    for i, s in enumerate(plan.get("shots") or []):
        s["index"] = i + 1
        s["duration"] = max(2, min(5, _int(s.get("duration"), 3)))
        s.setdefault("status", "pending")
    return save(plan)


def list_plans(limit: int = 20) -> list[dict]:
    items = []
    files = sorted(PLANS_DIR.glob("*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for f in files:
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            items.append({
                "id": p.get("id"), "title": p.get("title"),
                "status": p.get("status"), "created_at": p.get("created_at"),
                "shots": len(p.get("shots") or []),
                "duration": (p.get("meta") or {}).get("duration"),
            })
        except Exception:
            continue
    return items
