"""H3 提示词规范：创意发散 + 硬约束 + 逻辑分镜时间轴 + 渲染 + 校验。

设计原则：
- 不维护风格/材质/光源词库；用组合算子引导创意，具体描述由模型推导；
- 硬约束独立成层：人物一致性、表演（face_arc）、商品 must_show/must_not_change、
  全局视频约束；创意负责“怎么拍”，约束负责“必须有什么/绝不能变什么”；
- 逻辑分镜不是独立生成任务：最终拼成一条连续 H3 prompt，一次生成整条视频；
- 渲染器不做创作，只把 treatment/constraints/timeline 拼成 H3 可读的纯文本；
- 细度由五 lens、自评和 critic 判断，不设目标字数。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from orchestrator.app import config as C
from .text import fast_text as _fast

SHOT_FUNCS = ["视觉钩子", "产品揭晓", "材质特写", "使用演示",
              "对比证明", "场景融入", "颜色切换", "结尾卡"]

DEFAULT_NEGATIVE = ["无口播", "无字幕", "无文字", "无品牌logo",
                    "无多余人物", "商品不变形", "手部结构稳定",
                    "不要慢动作", "不要慢速推拉",
                    "不要新增商品图之外的服装部件"]

FIXED_NEGATIVE = [
    "不要口播", "不要字幕", "不要文字", "不要品牌logo", "不要水印",
    "不要多余人物", "商品不变形", "手部结构稳定",
    "不要慢动作", "不要慢速推拉", "不要新增商品图之外的服装部件",
    "不要变脸", "不要镜像漂移", "不要匀速直线运动", "不要假人滑行",
]

# 仅用于 lint 的反模式词：不是生成词库，只拦截“一个词当一句”的空洞描述。
ABSTRACT_ONLY = {"高级感", "氛围感", "唯美", "震撼", "治愈", "电影感",
                 "ins风", "高级", "质感", "自然", "好看"}

AXIS_LABELS = {"texture": "渲染质感", "palette": "色彩", "contrast": "对比",
               "camera": "运镜行为", "light": "光质"}

BEAT_DIMENSIONS = ["time", "framing", "camera", "light", "action",
                   "micro", "product", "environment", "audio", "continuity"]

COVERAGE_DIMS = ["framing", "camera", "light", "action", "micro", "product",
                 "environment", "audio", "continuity", "render_texture"]

_DIM_ALIASES = {
    "时间": "time", "取景": "framing", "景别": "framing",
    "运镜": "camera", "镜头": "camera", "机位": "camera",
    "光线": "light", "光": "light", "灯光": "light",
    "动作": "action", "微状态": "micro", "微表情": "micro",
    "商品": "product", "产品": "product",
    "环境": "environment", "场景": "environment",
    "声音": "audio", "音效": "audio", "声音设计": "audio",
    "连续性": "continuity", "衔接": "continuity",
    "渲染质感": "render_texture", "质感": "render_texture",
    "texture": "render_texture",
}


def _norm_dimension(v) -> str:
    s = _text(v).strip().lower()
    return _DIM_ALIASES.get(s, s)

SEED_SYSTEM = """你是创意总监。现在不要写分镜，也不要收敛。用组合算子生成 8-12 个创意种子。
只输出一个 JSON 对象，不要 markdown，不要解释。

# 输出
{
  "seeds": [
    {
      "operator": "跨域碰撞/元素叠加/约束突变/视角迁移/时间实验/尺度跳跃",
      "name": "种子名（≤12字）",
      "concept": "一句话概念（≤80字）",
      "visual_mechanism": "画面怎么成立（≤80字）",
      "product_evidence": "商品在画面里怎么被证明（≤60字）",
      "why": "为什么适合这个商品（≤60字）",
      "risk": "风险/代价（≤40字）"
    }
  ]
}

# 要求
- 8-12 个种子；6 类算子每类至少 1 个；至少 2 个反常规/高风险/不像广告的。
- 种子之间的差异必须是叙事结构、观看方式、时间结构或视角的差异，不是换形容词。
- 允许怪、允许作者感；但每个种子必须能拍出来，并且有商品画面证据。
- 只输出 JSON。
"""

DIRECTION_SYSTEM = """你是导演。基于创意种子，归纳 3 个真正不同的方向，选一个，写 treatment 和硬约束。
只输出一个 JSON 对象，不要 markdown，不要解释。

# 输出
{
  "title": "一句话标题（≤30字）",
  "directions": [
    {
      "name": "方向名（≤12字）",
      "concept": "核心想法（≤80字）",
      "why": "为什么成立（≤80字）",
      "cost": "代价/风险（≤50字）"
    }
  ],
  "chosen": 0,
  "treatment": {
    "idea": "核心想法（≤80字）",
    "reading": "潜台词、情绪从哪到哪、观众该读出什么（2-3句，≤160字）",
    "motif": "抽象母题（≤40字）",
    "visual_carrier": "母题在画面里的具体载体（≤80字）",
    "visual_thesis": "如果观众只记住一个画面，是什么（≤60字）",
    "visual_language": {
      "自由键名1": "从质感/色彩/对比/运镜/光/构图/节奏/声音等任意角度写；不要套固定5轴",
      "自由键名2": "..."
    },
    "render_base": "全局渲染底座：介质、颗粒/噪点、快门、景深、压缩、曝光行为（≤120字）",
    "assumptions": ["≤4条，每条≤40字"]
  },
  "constraints": {
    "identity": {
      "subject": "<Subject 1>",
      "face_consistency": true,
      "wardrobe_lock": true,
      "forbidden": ["换脸", "发色变化", "体型变化", "新增配饰"]
    },
    "performance": {
      "require_face_arc": true,
      "min_expression_changes": 2,
      "require_gaze_change": true,
      "require_breath": true,
      "require_secondary_motion": ["头发", "布料"],
      "forbidden": ["面无表情", "只有身体动作", "假人式匀速动作"]
    },
    "product": {
      "symbol": "<Product 1>",
      "must_show": ["整体版型", "材质/面料细节", "上身效果"],
      "must_not_change": ["颜色", "版型", "材质", "图案", "部件位置", "logo"],
      "wear_state": "正常穿着，不反穿，不遮挡关键细节",
      "matching": "下装/配饰以人物照片为准；不新增参考图之外的部件"
    },
    "global": {
      "duration": 15,
      "aspect_ratio": "9:16",
      "no_voiceover": true,
      "fast_pacing": true,
      "max_subjects": 3
    }
  },
  "meta": {
    "duration": 15,
    "aspect_ratio": "9:16",
    "style": "≤30字",
    "visual_concept": "≤50字",
    "hook": "前1-2秒的视觉钩子（≤50字）",
    "pacing": "fast",
    "rhythm": "≤60字",
    "bgm_style": "≤30字",
    "sound_policy": "无口播、无台词；只有环境底噪与 BGM"
  }
}

# 要求
- 3 个方向必须有真正的结构差异，写清代价；不要只是换形容词。
- constraints 必须具体到可检查：must_show 是这条片必须出现的商品画面证据，3-6 条；must_not_change 是绝不能变的商品属性。
- 允许作者感、允许怪，但必须可执行；总时长不超过 15 秒。
- 只输出 JSON。
"""

PLAN_SYSTEM = """你是导演。基于 treatment 和 constraints 设计逻辑分镜。
重要：这些是**同一条连续视频内的逻辑分镜**，不是多个独立生成任务。后续会合成一条连续 H3 prompt，一次生成整条视频。
只输出一个 JSON 对象，不要 markdown，不要解释。

# 输出
{
  "subject_definitions": [
    {
      "symbol": "<Subject 1>",
      "ref": "参考图1、参考图2",
      "identity": "身份/类别（≤30字）",
      "immutable": ["3-6条不可变特征，每条≤20字"]
    }
  ],
  "retention": [
    {
      "symbol": "<Subject 1>",
      "shots": [1, 2, 3],
      "preserved": ["3-6条必须保留的具体特征，每条≤20字"]
    }
  ],
  "shots": [
    {
      "index": 1,
      "start": 0.0,
      "duration": 3,
      "shot_function": "自由命名，如：触感钩子 / 身份确认 / 材质证据 / 生活情境 / 反差 / 结尾余韵",
      "person_present": true,
      "camera": "本镜镜头/运镜总览（1句）",
      "lighting": "本镜光线总览（1句）",
      "person_action": "人物动作总览（1句）",
      "product_action": "商品画面证据（1句）",
      "start_state": "起始画面/承接上一镜（1句）",
      "end_state": "结束画面（1句）",
      "cut_to_next": "切镜描述：硬切/动作匹配/下摇/遮挡/光线变化/结尾定格（1句）",
      "face_arc": {
        "start": "起始面部/视线/呼吸状态（可观察）",
        "turn": "动作中的表情/视线转折（可观察）",
        "end": "结束时的表情/呼吸回落（可观察）"
      },
      "product_evidence": ["本镜必须出现的商品画面证据1", "证据2"],
      "prompt_hint": "这一镜的导演意图（1句）",
      "on_screen_text": ""
    }
  ],
  "negative": ["无口播", "无字幕", "无品牌logo", "商品不变形", "不要慢动作"]
}

# 硬性要求
- 3-6 个逻辑分镜；总时长 12-15 秒（H3 单次上限 15 秒）；每镜 2-4 秒。
- 这些不是独立生成任务：共享同一时间轴、同一场景、同一人物/商品；不要写成多个独立视频。
- 每个有人物的镜头必须有 face_arc（start/turn/end，可观察的面部、视线、呼吸变化）；纯商品镜头可 person_present=false 并省略 face_arc。
- 每个镜头的 product_evidence 至少 1 项；constraints.product.must_show 必须全部覆盖。
- 每个镜头必须有 cut_to_next；最后一镜写“结尾定格/淡出”。
- 第 1 镜必须在 1 秒内出现商品或商品动作。
- 节奏 fast：正常速度、动作干脆；禁止慢动作、慢速推拉。
- 服装锁定/商品不变/身份一致/空间原点锁定，按 constraints 执行。
- 参考图编号必须按用户给出的顺序绑定，不要改动。
- 主体/商品/场景绑定符号，后续只引用符号，不重描述外观。
- 只输出 JSON。
"""

TIMELINE_SYSTEM = """你是 H3 整片导演。把整条视频写成一个连续的时间轴，不是多个独立镜头任务。
输入会给出：treatment、constraints、subject_definitions、retention、逻辑分镜列表、参考图顺序。
只输出一个 JSON 对象，不要 markdown，不要解释。

# 输出
{
  "timeline": [
    {
      "shot": 1,
      "time": [0.0, 3.0],
      "description": "一段连贯的导演执行说明。不要按字段列清单；用完整句子自然覆盖五个 lens：Optics（景别/机位/距离、运镜类型/方向/速度曲线/幅度/焦点、光源/方向/软硬/色温/对比/高光/阴影/轮廓光）、Body（动作蓄力-爆发-阻尼、重心/呼吸、面部表情/视线变化、布料/头发二次运动）、Object（商品位置/朝向/接触/形变/高光/细节）、World（前景/中景/背景/空气/景深、环境声/拟音/BGM/静音）、Continuity（继承上一镜、本镜结束状态、怎么切到下一镜）。允许长句和细节；不要空泛形容词。",
      "face_arc": {"start": "...", "turn": "...", "end": "..."},
      "product_evidence": ["本镜出现的商品证据"],
      "cut_to_next": "本镜怎么切到下一镜；最后一镜写结尾定格/淡出",
      "coverage": ["framing", "camera", "light", "action", "micro", "product", "environment", "audio", "continuity", "render_texture"]
    }
  ],
  "director_notes": "整条片的创作选择/取舍（≤160字）",
  "self_check": "逐镜检查五 lens 和 constraints（≤200字）"
}

# 粒度要求（不是目标字数，是理解细度）
- 每条 description 必须让五个 lens 都能被具体回答；长度由细节决定，不设目标字数。
- 每句都要回答一个“摄影机/灯/身体/材料/声音”的问题；删掉也不影响画面的句子不要写。
- 必须落实 constraints：有人物的镜头写 face_arc（可观察，和动作有因果）；每镜写 product_evidence；must_show 全局覆盖；不得违反 must_not_change / wear_state / matching。
- 每个 shot 结尾写 cut_to_next；下一镜开头写继承。
- 只引用 <Subject 1>/<Product 1> 等符号，不重描外观。
- 一个逻辑分镜是一个连续时间段；不要把多个独立镜头写进同一段。
- 只输出 JSON。
"""

CRITIC_SYSTEM = """你是细节评审。检查整条 timeline，不写新内容。
只输出一个 JSON 对象，不要 markdown，不要解释。

# 输出
{
  "issues": [
    {
      "shot": 1,
      "type": "空泛形容词/断因果/缺物理事实/face_arc不可观察/商品证据不足/违反must_not_change/切镜不清/连续性断裂",
      "quote": "原文片段",
      "fix": "怎么改"
    }
  ],
  "missing_constraints": ["没有被满足的 constraint"],
  "weak_shots": [1, 3],
  "verdict": "pass/revise"
}

# 检查要求
- 逐条对照 constraints（identity / performance / product / global）。
- 逐句问：删掉这句，画面会变模糊吗？不会就是废话。
- 检查 face_arc 是否可观察、与动作有因果；商品 must_show 是否全覆盖；must_not_change 是否被违反。
- 检查每个 cut_to_next 是否清楚；最后一镜是否有结尾。
- 只输出 JSON。
"""

REWRITE_SYSTEM = """你是导演。根据 critic 的 issues 重写整条 timeline，只改有问题的部分；保持已经达标的镜头不变。
只输出一个 JSON 对象，不要 markdown，不要解释。

# 输出
{
  "timeline": [
    {
      "shot": 1,
      "time": [0.0, 3.0],
      "description": "...",
      "face_arc": {"start": "...", "turn": "...", "end": "..."},
      "product_evidence": ["..."],
      "cut_to_next": "...",
      "coverage": ["framing", "camera", "light", "action", "micro", "product", "environment", "audio", "continuity", "render_texture"]
    }
  ],
  "director_notes": "≤160字",
  "change_log": ["改了哪几处，为什么"]
}

# 要求
- 修复所有 issues；不要引入新的空泛句；保持逻辑分镜、时间轴和 constraints。
- 只输出 JSON。
"""


# ---------------- 基础清洗 ----------------

def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "；".join(x for x in (_text(i) for i in v) if x)
    if isinstance(v, dict):
        return "；".join(f"{k}={_text(x)}" for k, x in v.items() if _text(x))
    return str(v).strip()


def _list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[；;\n]", v) if x.strip()]
    if isinstance(v, (list, tuple)):
        return [x for x in (_text(i) for i in v) if x]
    return [_text(v)] if _text(v) else []


def _items(v) -> list[str]:
    """不可变特征/保留项/微状态：兼容逗号、顿号分隔的字符串。"""
    pattern = r"[；;，,、\n]"
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(pattern, v) if x.strip()]
    if isinstance(v, (list, tuple)):
        out: list[str] = []
        for i in v:
            if isinstance(i, str):
                out.extend(x.strip() for x in re.split(pattern, i) if x.strip())
            else:
                t = _text(i)
                if t:
                    out.append(t)
        return out
    return [_text(v)] if _text(v) else []


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _norm_ref(v) -> str:
    s = _text(v)
    s = re.sub(r"<\s*Picture\s*(\d+)\s*>", r"参考图\1", s, flags=re.I)
    s = re.sub(r"\bPicture\s*(\d+)\b", r"参考图\1", s, flags=re.I)
    return s


def _norm_symbol(v, i: int) -> str:
    s = _text(v).strip("<> ")
    return f"<{s}>" if s else f"<Subject {i + 1}>"


def _int_list(v) -> list[int]:
    if isinstance(v, (int, float)):
        return [int(v)]
    if isinstance(v, (list, tuple)):
        out: list[int] = []
        for x in v:
            out.extend(_int_list(x))
        return sorted(set(out))
    s = _text(v)
    out = set()
    for part in re.split(r"[,，、;\s]+", s):
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.update(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            out.add(int(part))
    return sorted(out)


def _nonempty(d, keys: list[str]) -> list[str]:
    d = _dict(d)
    return [k for k in keys if _text(d.get(k))]


def _join_dict(d, keys: list[str] | None = None) -> str:
    d = _dict(d)
    keys = keys or list(d.keys())
    return "；".join(f"{k}={_text(d.get(k))}" for k in keys if _text(d.get(k)))


def normalize_negative(v) -> list[str]:
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[；;，,、\n]", v) if x.strip()]
    if isinstance(v, (list, tuple)):
        return [x for x in (_text(i) for i in v) if x]
    return []


def _neg_key(s: str) -> str:
    """负面约束去重：把“无X/不要X/禁止X”归一成同一个 key。"""
    s = re.sub(r"^(无|不要|禁止|避免|杜绝|别|无需|不能|不得)", "", _text(s))
    return s.strip().lower()


def _merge_negative(items) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        x = _text(x)
        key = _neg_key(x)
        if x and key not in seen:
            out.append(x)
            seen.add(key)
    return out


# ---------------- 规范化 ----------------

def normalize_interpretation(data, intent: str = "") -> dict:
    d = _dict(data)
    # 新 schema: treatment 包一层；兼容旧的平铺 interpretation
    if isinstance(d.get("treatment"), dict):
        d = {**d["treatment"], "directions": d.get("directions"),
             "chosen": d.get("chosen")}
    axes = _dict(d.get("style_axes"))
    vl = d.get("visual_language")
    if isinstance(vl, str):
        vl = {"自由描述": vl.strip()} if vl.strip() else {}
    elif not isinstance(vl, dict):
        vl = {}
    vl = {k: _text(v) for k, v in vl.items() if _text(v)}
    dirs = []
    raw_dirs = d.get("directions")
    if isinstance(raw_dirs, list):
        for x in raw_dirs:
            if isinstance(x, dict):
                dirs.append({k: _text(x.get(k)) for k in
                             ("name", "concept", "visual_language", "why")})
            elif _text(x):
                dirs.append({"name": _text(x)[:20], "concept": _text(x),
                             "visual_language": "", "why": ""})
    try:
        chosen = int(d.get("chosen", 0))
    except (TypeError, ValueError):
        chosen = 0
    chosen = max(0, min(chosen, len(dirs) - 1)) if dirs else 0
    return {
        "idea": _text(d.get("idea")) or intent[:80],
        "reading": _text(d.get("reading")),
        "motif": _text(d.get("motif")),
        "visual_carrier": _text(d.get("visual_carrier")),
        "visual_thesis": _text(d.get("visual_thesis")),
        "style_axes": {k: _text(v) for k, v in axes.items() if _text(v)},
        "visual_language": vl,
        "directions": dirs,
        "chosen": chosen,
        "render_base": _text(d.get("render_base")),
        "assumptions": _list(d.get("assumptions")),
    }


def _int_or(v, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _bool_or(v, default: bool = True) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "off", "否")
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def _match_symbol(raw, subject_defs: list[dict], fallback_index: int) -> str:
    """把约束里的描述性名称对齐到 subject_definitions 的符号。"""
    text = _text(raw)
    symbols = [_text(x.get("symbol")) for x in subject_defs
               if _text(x.get("symbol"))]
    if text in symbols:
        return text
    if not text:
        return (symbols[fallback_index] if len(symbols) > fallback_index
                else f"<Subject {fallback_index + 1}>")
    # “短发女生（灰白针织套装）”这种混合描述：先看第一个短句和哪个 identity 对齐
    head = re.split(r"[（(，,、;；]", text)[0].strip()
    if head:
        for d in subject_defs:
            ident = _text(d.get("identity"))
            sym = _text(d.get("symbol"))
            if sym and ident and (ident.startswith(head) or head in ident):
                return sym
    # 参考图编号也可作为对齐依据
    refs = re.findall(r"参考图(\d+)", text)
    if refs:
        for d in subject_defs:
            sym = _text(d.get("symbol"))
            drefs = re.findall(r"参考图(\d+)", _text(d.get("ref")))
            if sym and set(refs) & set(drefs):
                return sym
    best_sym, best_score = None, 0.0
    for d in subject_defs:
        ident = _text(d.get("identity"))
        sym = _text(d.get("symbol"))
        if not ident or not sym:
            continue
        score = SequenceMatcher(None, text, ident).ratio()
        if score > best_score:
            best_sym, best_score = sym, score
    if best_sym and best_score >= 0.55:
        return best_sym
    return (symbols[fallback_index] if len(symbols) > fallback_index
            else f"<Subject {fallback_index + 1}>")


def normalize_constraints(raw, subject_defs: list[dict], duration: int,
                          aspect: str) -> dict:
    d = _dict(raw)
    ident = _dict(d.get("identity"))
    perf = _dict(d.get("performance"))
    prod = _dict(d.get("product"))
    glob = _dict(d.get("global"))
    subject = _match_symbol(ident.get("subject"), subject_defs, 0)
    product_symbol = _match_symbol(prod.get("symbol"), subject_defs, 1)
    must_show = _items(prod.get("must_show"))
    must_not = _items(prod.get("must_not_change"))
    return {
        "identity": {
            "subject": subject,
            "face_consistency": _bool_or(ident.get("face_consistency"), True),
            "wardrobe_lock": _bool_or(ident.get("wardrobe_lock"), True),
            "forbidden": _items(ident.get("forbidden")) or
                         ["换脸", "发色变化", "体型变化", "新增配饰"],
        },
        "performance": {
            "require_face_arc": _bool_or(perf.get("require_face_arc"), True),
            "min_expression_changes": max(
                1, _int_or(perf.get("min_expression_changes"), 2)),
            "require_gaze_change": _bool_or(perf.get("require_gaze_change"), True),
            "require_breath": _bool_or(perf.get("require_breath"), True),
            "require_secondary_motion": _items(perf.get("require_secondary_motion"))
                                        or ["头发", "布料"],
            "forbidden": _items(perf.get("forbidden"))
                         or ["面无表情", "只有身体动作", "假人式匀速动作"],
        },
        "product": {
            "symbol": product_symbol,
            "must_show": must_show or ["整体版型", "材质/面料细节", "上身效果"],
            "must_not_change": must_not or
                               ["颜色", "版型", "材质", "图案", "部件位置", "logo"],
            "wear_state": _text(prod.get("wear_state")) or
                          "正常穿着，不反穿，不遮挡关键细节",
            "matching": _text(prod.get("matching")) or
                        "下装/配饰以人物照片为准；不新增参考图之外的部件",
        },
        "global": {
            "duration": max(4, min(15, _int_or(
                glob.get("duration") or duration, duration or 15))),
            "aspect_ratio": _text(glob.get("aspect_ratio")) or aspect or "9:16",
            "no_voiceover": _bool_or(glob.get("no_voiceover"), True),
            "fast_pacing": _bool_or(glob.get("fast_pacing"), True),
            "max_subjects": max(1, _int_or(glob.get("max_subjects"), 3)),
        },
    }


def default_subject_definitions(person: list[str], product: list[str],
                                background: list[str]) -> list[dict]:
    items: list[dict] = []
    n_person = min(2, len(person))
    n_product = min(2, len(product))
    if person:
        refs = "、".join(f"参考图{i + 1}" for i in range(n_person))
        items.append({"symbol": "<Subject 1>", "ref": refs,
                      "identity": "固定人物",
                      "immutable": ["五官", "发型", "体型", "肤色", "服装状态"]})
    if product:
        start = n_person
        refs = "、".join(f"参考图{start + i + 1}" for i in range(n_product))
        items.append({"symbol": "<Product 1>", "ref": refs,
                      "identity": "商品",
                      "immutable": ["颜色", "版型", "材质", "细节"]})
    if background:
        items.append({"symbol": "<Scene 1>", "ref": f"参考图{n_person + n_product + 1}",
                      "identity": "场景",
                      "immutable": ["空间结构", "背景元素", "光线氛围"]})
    return items


def normalize_subject_definitions(raw, person: list[str], product: list[str],
                                  background: list[str]) -> list[dict]:
    items = raw
    if isinstance(raw, dict):
        items = [{"symbol": k, **(v if isinstance(v, dict) else {"identity": v})}
                 for k, v in raw.items()]
    if not isinstance(items, list):
        items = []
    out = []
    for i, x in enumerate(items):
        if not isinstance(x, dict):
            continue
        out.append({
            "symbol": _norm_symbol(x.get("symbol"), i),
            "ref": _norm_ref(x.get("ref")),
            "identity": _text(x.get("identity")),
            "immutable": _items(x.get("immutable")),
        })
    return out or default_subject_definitions(person, product, background)


def normalize_retention(raw, defs: list[dict], shot_count: int) -> list[dict]:
    items = raw
    if isinstance(raw, dict):
        items = [{"symbol": k, **(v if isinstance(v, dict) else {"preserved": v})}
                 for k, v in raw.items()]
    if not isinstance(items, list):
        items = []
    out = []
    for x in items:
        if not isinstance(x, dict):
            continue
        sym = _text(x.get("symbol"))
        if not sym:
            continue
        if not sym.startswith("<"):
            sym = f"<{sym}>"
        out.append({
            "symbol": sym,
            "shots": _int_list(x.get("shots") or x.get("beats")),
            "preserved": _items(x.get("preserved") or x.get("retain")),
        })
    all_shots = list(range(1, shot_count + 1))
    seen = {r["symbol"] for r in out}
    for d in defs:
        sym = d.get("symbol")
        if sym and sym not in seen:
            out.append({"symbol": sym, "shots": all_shots,
                        "preserved": d.get("immutable") or []})
            seen.add(sym)
    return out


def _norm_camera(v) -> dict:
    if isinstance(v, str):
        return {"type": _text(v)}
    d = _dict(v)
    return {
        "type": _text(d.get("type") or d.get("movement") or d.get("shot")),
        "direction": _text(d.get("direction")),
        "speed_curve": _text(d.get("speed_curve") or d.get("speed")),
        "amplitude": _text(d.get("amplitude") or d.get("range")),
        "focus": _text(d.get("focus")),
    }


def _norm_light(v) -> dict:
    if isinstance(v, str):
        return {"source": _text(v)}
    d = _dict(v)
    return {
        "source": _text(d.get("source")),
        "direction": _text(d.get("direction")),
        "quality": _text(d.get("quality") or d.get("hardness")),
        "color": _text(d.get("color") or d.get("color_temp")),
        "contrast": _text(d.get("contrast")),
        "highlight": _text(d.get("highlight") or d.get("highlights")),
        "shadow": _text(d.get("shadow") or d.get("shadows")),
        "rim": _text(d.get("rim") or d.get("rim_light")),
    }


def _norm_action(v) -> dict:
    if isinstance(v, str):
        return {"burst": _text(v)}
    d = _dict(v)
    return {
        "anticipation": _text(d.get("anticipation")),
        "burst": _text(d.get("burst")),
        "settle": _text(d.get("settle")),
        "weight": _text(d.get("weight") or d.get("breath") or d.get("breathing")),
        "secondary": _text(d.get("secondary") or d.get("secondary_motion")),
    }


def _norm_product(v) -> dict:
    if isinstance(v, str):
        return {"position": _text(v)}
    d = _dict(v)
    return {
        "position": _text(d.get("position")),
        "orientation": _text(d.get("orientation")),
        "contact": _text(d.get("contact")),
        "deformation": _text(d.get("deformation")),
        "highlight": _text(d.get("highlight")),
        "detail": _text(d.get("detail") or d.get("detail_visibility")),
    }


def _norm_env(v) -> dict:
    if isinstance(v, str):
        return {"midground": _text(v)}
    d = _dict(v)
    return {
        "foreground": _text(d.get("foreground")),
        "midground": _text(d.get("midground")),
        "background": _text(d.get("background")),
        "atmosphere": _text(d.get("atmosphere")),
        "depth": _text(d.get("depth") or d.get("depth_layers")),
    }


def _norm_audio(v) -> dict:
    if isinstance(v, str):
        return {"ambience": _text(v), "speech": "none"}
    d = _dict(v)
    return {
        "ambience": _text(d.get("ambience")),
        "foley": _text(d.get("foley")),
        "music": _text(d.get("music")),
        "speech": _text(d.get("speech")) or "none",
    }


def _norm_continuity(v) -> dict:
    if isinstance(v, str):
        return {"inherited": _text(v)}
    d = _dict(v)
    return {
        "inherited": _text(d.get("inherited") or d.get("inherit")),
        "end_state": _text(d.get("end_state")),
        "transition": _text(d.get("transition")),
    }


def _norm_beat(b: dict) -> dict:
    face = _dict(b.get("face_arc") or b.get("face"))
    return {
        "shot": b.get("shot"),
        "time": b.get("time"),
        "description": _text(b.get("description") or b.get("text") or b.get("prose")),
        "coverage": _items(b.get("coverage") or b.get("dimensions")),
        "face_arc": {k: _text(face.get(k)) for k in ("start", "turn", "end")},
        "product_evidence": _items(b.get("product_evidence")),
        "cut_to_next": _text(b.get("cut_to_next") or b.get("cut") or b.get("transition")),
        "framing": _text(b.get("framing") or b.get("shot_size") or b.get("composition")),
        "camera": _norm_camera(b.get("camera")),
        "light": _norm_light(b.get("light") or b.get("lighting")),
        "action": _norm_action(b.get("action")),
        "micro_state": _items(b.get("micro_state") or b.get("micro") or b.get("micro_expression")),
        "product": _norm_product(b.get("product") or b.get("product_state")),
        "environment": _norm_env(b.get("environment") or b.get("scene")),
        "audio": _norm_audio(b.get("audio") or b.get("sound")),
        "continuity": _norm_continuity(b.get("continuity")),
        "render_texture": _text(b.get("render_texture") or b.get("texture")),
    }


def _beat_time(b: dict):
    t = b.get("time")
    if isinstance(t, (list, tuple)) and len(t) >= 2:
        try:
            return float(t[0]), float(t[1])
        except (TypeError, ValueError):
            return None
    if isinstance(t, dict):
        try:
            return float(t.get("start")), float(t.get("end"))
        except (TypeError, ValueError):
            return None
    if isinstance(t, str):
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:-|~|—|至)\s*(\d+(?:\.\d+)?)",
                     t)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


def normalize_beats(raw, shot_duration: float) -> list[dict]:
    if isinstance(raw, dict):
        raw = raw.get("beats") or [raw]
    if not isinstance(raw, list):
        return []
    items = [b for b in raw if isinstance(b, dict)]
    if not items:
        return []
    beats = [_norm_beat(b) for b in items]
    n = len(beats)
    default_len = shot_duration / n if n else shot_duration

    # 先补齐缺失时间
    for i, b in enumerate(beats):
        t = _beat_time(b)
        if not t:
            start = i * default_len
            t = (start, start + default_len)
        if t[1] <= t[0]:
            t = (t[0], t[0] + max(0.2, default_len))
        b["time"] = [round(t[0], 2), round(t[1], 2)]

    # 整体缩放到镜头时长，保证 beats 覆盖 0..shot_duration
    base = beats[0]["time"][0]
    total = beats[-1]["time"][1] - base
    if total <= 0:
        for i, b in enumerate(beats):
            b["time"] = [round(i * default_len, 2), round((i + 1) * default_len, 2)]
        return beats
    scale = shot_duration / total
    for b in beats:
        b["time"] = [round((b["time"][0] - base) * scale, 2),
                     round((b["time"][1] - base) * scale, 2)]
    beats[0]["time"][0] = 0.0
    beats[-1]["time"][1] = round(float(shot_duration), 2)
    return beats


def summarize_shot(beats: list[dict]) -> dict:
    if not beats:
        return {}
    first, last = beats[0], beats[-1]
    cont_first = _dict(first.get("continuity"))
    cont_last = _dict(last.get("continuity"))
    return {
        "camera": _join_dict(first.get("camera")),
        "lighting": _join_dict(first.get("light")),
        "person_action": _join_dict(first.get("action")),
        "product_action": _join_dict(first.get("product")),
        "start_state": _text(cont_first.get("inherited")),
        "end_state": _text(cont_last.get("end_state")),
        "transition": _text(cont_last.get("transition")),
        "prompt_hint": _text(first.get("framing")),
    }


def merge_meta(meta, interp: dict, intent: str, duration: int, aspect: str,
               resolution: str, pacing: str) -> dict:
    m = _dict(meta)
    axes = interp.get("style_axes") or {}
    vl = interp.get("visual_language") or {}
    style_fallback = (next(iter(vl.values()), "") if isinstance(vl, dict) else "")
    style = (_text(m.get("style")) or _text(style_fallback)
             or _text(axes.get("texture")) or "真实质感商业广告")
    dirs = interp.get("directions") or []
    try:
        chosen = int(interp.get("chosen") or 0)
    except (TypeError, ValueError):
        chosen = 0
    chosen_dir = dirs[chosen] if dirs and 0 <= chosen < len(dirs) else {}
    out = {
        "duration": duration,
        "aspect_ratio": _text(m.get("aspect_ratio")) or aspect,
        "resolution": resolution,
        "style": style,
        "visual_concept": _text(m.get("visual_concept")) or interp.get("idea") or intent[:80],
        "hook": _text(m.get("hook")),
        "pacing": _text(m.get("pacing")) or pacing,
        "rhythm": _text(m.get("rhythm")) or "前1秒商品钩子，中段快切，结尾干净",
        "wardrobe_lock": True,
        "bgm_style": _text(m.get("bgm_style")),
        "idea": interp.get("idea", ""),
        "reading": interp.get("reading", ""),
        "motif": interp.get("motif", ""),
        "visual_carrier": interp.get("visual_carrier", ""),
        "visual_thesis": interp.get("visual_thesis", ""),
        "style_axes": axes,
        "visual_language": vl,
        "directions": dirs,
        "chosen": chosen,
        "direction_name": _text(chosen_dir.get("name")),
        "direction_concept": _text(chosen_dir.get("concept")),
        "render_base": interp.get("render_base", ""),
        "assumptions": interp.get("assumptions", []),
        "sound_policy": _text(m.get("sound_policy")) or "无口播、无台词；只有环境底噪与 BGM",
    }
    if m.get("fallback_reason"):
        out["fallback_reason"] = m["fallback_reason"]
    return out


# ---------------- 渲染 ----------------

def _fmt_time(sec: float) -> str:
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:04.1f}"


def _render_subject_definitions(defs: list[dict]) -> list[str]:
    if not defs:
        return []
    lines = ["【主体定义】"]
    for d in defs:
        sym = _text(d.get("symbol")) or "<Subject>"
        ref = _norm_ref(d.get("ref"))
        identity = re.sub(r"^参考图\s*\d*\s*(?:中)?的?",
                          "", _text(d.get("identity")))
        immutable = _items(d.get("immutable"))
        line = sym
        if ref:
            line += f" = {ref}"
        if identity:
            line += f" 中的{identity}"
        line += "。"
        if immutable:
            line += "不可变特征：" + "、".join(immutable) + "。"
        lines.append(line)
    lines.append("")
    return lines


def _render_intent(plan: dict) -> list[str]:
    interp = _dict(plan.get("interpretation"))
    lines: list[str] = []
    dirs = interp.get("directions") or []
    try:
        chosen = int(interp.get("chosen") or 0)
    except (TypeError, ValueError):
        chosen = 0
    if dirs and 0 <= chosen < len(dirs):
        d = dirs[chosen]
        name, concept = _text(d.get("name")), _text(d.get("concept"))
        if name or concept:
            lines.append("创意方向：" + name + (f"——{concept}" if concept else ""))
    if _text(interp.get("idea")):
        lines.append("核心想法：" + _text(interp["idea"]))
    if _text(interp.get("reading")):
        lines.append("解读：" + _text(interp["reading"]))
    motif = _text(interp.get("motif"))
    carrier = _text(interp.get("visual_carrier"))
    if motif:
        lines.append("母题：" + motif + (f"；载体：{carrier}" if carrier else ""))
    if _text(interp.get("visual_thesis")):
        lines.append("记忆画面：" + _text(interp["visual_thesis"]))
    vl = _dict(interp.get("visual_language"))
    if vl:
        lines.append("视觉语言：" + "；".join(
            f"{k}：{_text(v)}" for k, v in vl.items() if _text(v)) + "。")
    else:
        axes = _dict(interp.get("style_axes"))
        if axes:
            lines.append("视觉语言：" + "；".join(
                f"{AXIS_LABELS.get(k, k)}：{_text(v)}"
                for k, v in axes.items() if _text(v)) + "。")
    return ["【创作意图】", *lines, ""] if lines else []


def _render_global(plan: dict, shot: dict, legend: str) -> list[str]:
    meta = _dict(plan.get("meta"))
    interp = _dict(plan.get("interpretation"))
    lines = ["【全局合同】"]
    unit = "整条" if shot.get("whole_video") else "单镜"
    lines.append(
        f"{_text(meta.get('style') or '真实质感商业广告')}；"
        f"{meta.get('aspect_ratio') or '9:16'} 竖屏；"
        f"{meta.get('resolution') or '768P'}；{unit} {shot.get('duration')} 秒。")
    lines.append(
        f"节奏：{meta.get('pacing') or 'fast'}；"
        f"{_fast(meta.get('rhythm') or '前1秒商品钩子，中段快切，结尾干净')}。"
        "正常速度，动作干脆，镜头运动有速度感。")
    if legend:
        lines.append("参考图顺序：" + legend + "。")
    if interp.get("render_base"):
        lines.append("渲染底座：" + _text(interp["render_base"]))
    assets = _dict(plan.get("assets"))
    if assets.get("person_photos"):
        lines.append("固定人物照片中的人物保持五官、发型、体型、肤色一致。")
    if assets.get("background_images"):
        lines.append("背景与参考图一致。")
    if assets.get("person_photos") and meta.get("wardrobe_lock", True):
        lines.append("服装锁定：只使用商品图中出现的服装部件；商品图未覆盖的"
                     "下装、鞋子、配饰、发型以人物照片为准，不要新增或改变。")
    lines.append("商品保持颜色、版型、材质、细节一致，商品必须清晰可见。")
    max_subjects = ((_dict(plan.get("constraints")).get("global") or {})
                    .get("max_subjects") or 3)
    lines.append(f"同框清晰主体不超过 {max_subjects} 个；"
                 "次要主体用前景遮挡或浅景深虚化。")
    lines.append("机位变化必须锁定场景物理原点与主体站位；不要变脸、不要镜像漂移。")
    lines.append("声音：" + _fast(meta.get("sound_policy")
                                or "无口播、无台词；只有环境底噪与 BGM") + "。")
    lines.append("")
    return lines


def _render_retention(plan: dict, shot: dict) -> list[str]:
    items = plan.get("retention") or []
    if not items:
        return []
    try:
        idx = int(shot.get("index"))
    except (TypeError, ValueError):
        idx = None
    lines: list[str] = []
    for r in items:
        sym = _text(r.get("symbol"))
        shots = _int_list(r.get("shots") or r.get("beats"))
        if shots and idx not in shots:
            continue
        preserved = _items(r.get("preserved"))
        lines.append(f"{sym}：完全保留——"
                     f"{'、'.join(preserved) if preserved else '参考图中的不可变特征'}。")
    return ["【本镜保留】", *lines, ""] if lines else []


def _shot_brief(shot: dict) -> str:
    pairs = [
        ("镜头", shot.get("camera")),
        ("光线", shot.get("lighting")),
        ("人物动作", shot.get("person_action")),
        ("商品动作", shot.get("product_action")),
        ("起始", shot.get("start_state")),
        ("结束", shot.get("end_state")),
        ("转场", shot.get("transition")),
        ("画面要点", shot.get("prompt_hint")),
    ]
    return "；".join(f"{k}={_fast(v)}" for k, v in pairs if _text(v))


def render_beat(beat: dict, index: int) -> str:
    t = _beat_time(beat) or (0.0, 0.0)
    lines = [f"[beat {index} | {_fmt_time(t[0])}-{_fmt_time(t[1])}]"]
    desc = _text(beat.get("description"))
    if desc:
        lines.append(desc)
        cont = _dict(beat.get("continuity"))
        if any(_text(v) for v in cont.values()):
            lines.append("连续性：" + _join_dict(cont))
        return "\n".join(lines)
    if _text(beat.get("framing")):
        lines.append("取景：" + _fast(beat["framing"]))
    cam = _join_dict(beat.get("camera"))
    if cam:
        lines.append("运镜：" + _fast(cam))
    light = _join_dict(beat.get("light"))
    if light:
        lines.append("光线：" + light)
    action = _join_dict(beat.get("action"))
    if action:
        lines.append("动作：" + _fast(action))
    micro = _items(beat.get("micro_state"))
    if micro:
        lines.append("微状态：" + "；".join(micro))
    product = _join_dict(beat.get("product"))
    if product:
        lines.append("商品：" + _fast(product))
    env = _join_dict(beat.get("environment"))
    if env:
        lines.append("环境：" + _fast(env))
    audio = _dict(beat.get("audio"))
    audio_bits = [f"{k}={_text(audio[k])}" for k in ("ambience", "foley", "music")
                  if _text(audio.get(k))]
    audio_bits.append("口播=none")
    lines.append("声音：" + "；".join(audio_bits))
    cont = _join_dict(beat.get("continuity"))
    if cont:
        lines.append("连续性：" + cont)
    if _text(beat.get("render_texture")):
        lines.append("渲染质感：" + _fast(beat["render_texture"]))
    return "\n".join(lines)


def render_shot(plan: dict, shot: dict, legend: str = "") -> str:
    parts: list[str] = []
    meta = _dict(plan.get("meta"))
    parts.extend(_render_subject_definitions(plan.get("subject_definitions") or []))
    parts.extend(_render_intent(plan))
    parts.extend(_render_global(plan, shot, legend))
    parts.extend(_render_retention(plan, shot))

    parts.append(f"【镜头 {shot.get('index')} | "
                 f"{shot.get('shot_function') or '产品展示'} | "
                 f"{shot.get('duration')}s】")
    if shot.get("index") == 1 and meta.get("hook"):
        parts.append("视觉钩子：" + _fast(meta["hook"])
                     + "；前1秒必须出现商品或商品动作。")
    brief = _shot_brief(shot)
    if brief:
        parts.append("本镜总览：" + brief + "。")
    if _text(shot.get("director_notes")):
        parts.append("导演注：" + _text(shot["director_notes"]))
    beats = shot.get("beats") or []
    if beats:
        for i, b in enumerate(beats, 1):
            parts.append(render_beat(b, i))
    elif not brief:
        parts.append("本镜按全局合同执行；商品清晰可见，动作干脆。")
    if shot.get("on_screen_text"):
        parts.append(f"后期叠加文字：{shot['on_screen_text']}（不要生成在画面里）。")
    parts.append("")

    merged = _merge_negative(
        normalize_negative(plan.get("negative")) + FIXED_NEGATIVE)
    parts.append("【负面约束】" + "；".join(merged) + "。")
    return "\n".join(parts)


def _render_retention_all(plan: dict) -> list[str]:
    items = plan.get("retention") or []
    if not items:
        return []
    lines = ["【保留审计】"]
    for r in items:
        sym = _text(r.get("symbol"))
        shots = _int_list(r.get("shots") or r.get("beats"))
        where = ("全片" if not shots else
                 "第" + "、".join(str(x) for x in shots) + "镜")
        preserved = _items(r.get("preserved"))
        lines.append(f"{sym} 出现在{where}：完全保留——"
                     f"{'、'.join(preserved) if preserved else '参考图中的不可变特征'}。")
    lines.append("")
    return lines


def _render_constraints(plan: dict) -> list[str]:
    c = _dict(plan.get("constraints"))
    if not c:
        return []
    ident = _dict(c.get("identity"))
    perf = _dict(c.get("performance"))
    prod = _dict(c.get("product"))
    glob = _dict(c.get("global"))
    has_person = bool((plan.get("assets") or {}).get("person_photos"))
    lines = ["【硬约束】"]
    if ident and has_person:
        bits = []
        if _text(ident.get("subject")):
            bits.append(f"人物符号 {_text(ident['subject'])}")
        if ident.get("face_consistency"):
            bits.append("五官/发型/体型/肤色一致")
        if ident.get("wardrobe_lock"):
            bits.append("服装锁定")
        forbidden = _items(ident.get("forbidden"))
        if forbidden:
            bits.append("禁止：" + "、".join(forbidden))
        if bits:
            lines.append("人物：" + "；".join(bits) + "。")
    if perf and has_person:
        bits = []
        if perf.get("require_face_arc"):
            bits.append("每个有人物的镜头必须有可观察的面部/视线/呼吸变化")
        n = perf.get("min_expression_changes")
        if n:
            bits.append(f"至少 {n} 次表情变化")
        if perf.get("require_gaze_change"):
            bits.append("视线必须有变化")
        if perf.get("require_breath"):
            bits.append("呼吸要有变化")
        sec = _items(perf.get("require_secondary_motion"))
        if sec:
            bits.append("二次运动：" + "、".join(sec))
        forbidden = _items(perf.get("forbidden"))
        if forbidden:
            bits.append("禁止：" + "、".join(forbidden))
        if bits:
            lines.append("表演：" + "；".join(bits) + "。")
    if prod:
        bits = []
        if _text(prod.get("symbol")):
            bits.append(f"商品符号 {_text(prod['symbol'])}")
        must = _items(prod.get("must_show"))
        if must:
            bits.append("必须出现：" + "、".join(must))
        not_change = _items(prod.get("must_not_change"))
        if not_change:
            bits.append("不得改变：" + "、".join(not_change))
        if _text(prod.get("wear_state")):
            bits.append("穿着状态：" + _text(prod["wear_state"]))
        if _text(prod.get("matching")):
            bits.append("匹配：" + _text(prod["matching"]))
        if bits:
            lines.append("商品：" + "；".join(bits) + "。")
    if glob:
        bits = []
        if glob.get("duration"):
            bits.append(f"总时长 {glob['duration']} 秒")
        if _text(glob.get("aspect_ratio")):
            bits.append(_text(glob["aspect_ratio"]))
        if glob.get("no_voiceover"):
            bits.append("无口播")
        if glob.get("fast_pacing"):
            bits.append("快节奏")
        if glob.get("max_subjects"):
            bits.append(f"同框主体 ≤{glob['max_subjects']}")
        if bits:
            lines.append("视频：" + "；".join(bits) + "。")
    lines.append("")
    return lines


def render_video(plan: dict, legend: str = "") -> str:
    """整条视频一次生成的 H3 prompt：逻辑分镜 + 切镜描述 + 硬约束。"""
    meta = _dict(plan.get("meta"))
    shots = plan.get("shots") or []
    total = meta.get("duration") or sum(
        float(s.get("duration") or 0) for s in shots)
    parts: list[str] = []
    parts.extend(_render_subject_definitions(plan.get("subject_definitions") or []))
    parts.extend(_render_intent(plan))
    parts.extend(_render_global(
        plan, {"duration": total, "whole_video": True}, legend))
    parts.extend(_render_retention_all(plan))
    parts.extend(_render_constraints(plan))

    parts.append("【逻辑分镜时间轴】")
    parts.append("这是一条连续视频内的逻辑分镜，不是多个独立生成任务。"
                 "请按时间轴连续生成，在切镜处按切镜描述执行。")
    cursor = 0.0
    for shot in shots:
        dur = float(shot.get("duration") or 3)
        t = shot.get("time")
        if isinstance(t, (list, tuple)) and len(t) >= 2:
            try:
                start, end = float(t[0]), float(t[1])
            except (TypeError, ValueError):
                start, end = cursor, cursor + dur
        else:
            start, end = cursor, cursor + dur
        cursor = end
        beats = shot.get("beats") or []
        beat = beats[0] if beats else {}
        desc = _text(beat.get("description"))
        parts.append(f"[{_fmt_time(start)}-{_fmt_time(end)} | "
                     f"镜头 {shot.get('index')} | "
                     f"{shot.get('shot_function') or '产品展示'}]")
        if desc:
            parts.append(desc)
        else:
            brief = _shot_brief(shot)
            if brief:
                parts.append("本镜执行：" + brief + "。")
            for j, b in enumerate(beats, 1):
                parts.append(render_beat(b, j))
        face = _dict(beat.get("face_arc") or shot.get("face_arc"))
        labels = {"start": "起始", "turn": "转折", "end": "结束"}
        face_bits = [f"{labels[k]}：{_text(face.get(k))}"
                     for k in ("start", "turn", "end") if _text(face.get(k))]
        if face_bits:
            parts.append("表演：" + "；".join(face_bits) + "。")
        evidence = _items(beat.get("product_evidence")
                          or shot.get("product_evidence"))
        if evidence:
            parts.append("商品证据：" + "、".join(evidence) + "。")
        cut = _text(beat.get("cut_to_next") or shot.get("cut_to_next"))
        if cut:
            parts.append("切镜：" + cut + "。")
        if shot.get("on_screen_text"):
            parts.append(f"后期叠加文字：{shot['on_screen_text']}"
                         "（不要生成在画面里）。")
        parts.append("")

    merged = _merge_negative(
        normalize_negative(plan.get("negative")) + FIXED_NEGATIVE)
    parts.append("【负面约束】" + "；".join(merged) + "。")
    return "\n".join(parts)


# ---------------- 粒度校验 ----------------

def _beat_duration(beat: dict, default: float) -> float:
    t = _beat_time(beat)
    return (t[1] - t[0]) if t else default


def lint_plan(plan: dict) -> dict:
    """结构 + 粒度检查。优先检查 prose description，旧结构化 beat 仍兼容。"""
    errors: list[str] = []
    warnings: list[str] = []
    beat_reports: list[dict] = []

    interp = _dict(plan.get("interpretation"))
    if not _text(interp.get("idea")):
        errors.append("interpretation.idea 为空")
    if not _text(interp.get("reading")):
        errors.append("interpretation.reading 为空（需要潜台词与情绪弧）")
    if not _text(interp.get("motif")):
        warnings.append("interpretation.motif 为空（建议写抽象母题）")
    if not _text(interp.get("visual_thesis")):
        warnings.append("interpretation.visual_thesis 为空（建议写记忆画面）")
    if not _text(interp.get("render_base")):
        warnings.append("interpretation.render_base 为空（建议写全局渲染底座）")

    vl = _dict(interp.get("visual_language"))
    axes = _dict(interp.get("style_axes"))
    n_vl = len(_nonempty(vl, list(vl.keys()))) if vl else 0
    n_axes = len(_nonempty(axes, list(axes.keys()))) if axes else 0
    if n_vl == 0 and n_axes == 0:
        warnings.append("visual_language 为空（视觉语言需要有可观察描述）")
    elif n_vl == 1:
        warnings.append("visual_language 只有 1 个维度，建议更具体")
    dirs = interp.get("directions") or []
    if len(dirs) < 2:
        warnings.append("directions 少于 2 个（建议先提出 2-3 个真正不同的方向）")
    try:
        chosen = int(interp.get("chosen") or 0)
    except (TypeError, ValueError):
        chosen = 0
    if dirs and not (0 <= chosen < len(dirs)):
        warnings.append("chosen 索引越界")

    defs = plan.get("subject_definitions") or []
    if not defs:
        errors.append("subject_definitions 为空")
    symbols = set()
    for i, d in enumerate(defs):
        sym = _text(d.get("symbol")) or f"<Subject {i + 1}>"
        symbols.add(sym)
        if len(_items(d.get("immutable"))) < 3:
            errors.append(f"{sym} 的 immutable 少于 3 条")
        if not _text(d.get("ref")):
            errors.append(f"{sym} 没有绑定参考图")
    assets = _dict(plan.get("assets"))
    ref_count = (min(2, len(assets.get("person_photos") or []))
                 + min(2, len(assets.get("product_images") or []))
                 + min(1, len(assets.get("background_images") or [])))
    for d in defs:
        for n in re.findall(r"参考图(\d+)", _text(d.get("ref"))):
            if ref_count and int(n) > ref_count:
                errors.append(f"{d.get('symbol')} 绑定了不存在的参考图{n}")

    ret = plan.get("retention") or []
    ret_symbols = {_text(r.get("symbol")) for r in ret if _text(r.get("symbol"))}
    for sym in symbols:
        if sym not in ret_symbols:
            errors.append(f"retention 缺少 {sym}")
    for r in ret:
        if not _items(r.get("preserved")):
            errors.append(f"retention {r.get('symbol')} 缺少 preserved")

    constraints = _dict(plan.get("constraints"))
    if not constraints:
        warnings.append("constraints 为空（人物表演/商品 must_show 未声明）")
    prod_c = _dict(constraints.get("product"))
    perf_c = _dict(constraints.get("performance"))
    must_show = _items(prod_c.get("must_show"))
    if constraints and not must_show:
        warnings.append("constraints.product.must_show 为空")
    require_face = _bool_or(perf_c.get("require_face_arc"), True)

    shots = plan.get("shots") or []
    if not shots:
        errors.append("shots 为空")
    if shots and not (3 <= len(shots) <= 7):
        warnings.append(f"镜头数 {len(shots)} 不在 3-7")
    try:
        total = sum(float(s.get("duration") or 0) for s in shots)
    except (TypeError, ValueError):
        total = 0
    if total > 15.01:
        errors.append(f"总时长 {total:g} 秒超过 H3 单次上限 15 秒")
    elif total and total < 12:
        warnings.append(f"总时长 {total:g} 秒低于 12 秒")

    core_dims = {"framing", "camera", "light", "action", "micro",
                 "product", "environment", "audio", "continuity"}
    all_evidence: list[str] = []
    for shot in shots:
        idx = shot.get("index")
        try:
            dur = float(shot.get("duration"))
        except (TypeError, ValueError):
            dur = 0.0
        if not (2 <= dur <= 5):
            errors.append(f"镜头{idx} 时长 {shot.get('duration')} 不在 2-5 秒")
        func = _text(shot.get("shot_function"))
        if not func:
            warnings.append(f"镜头{idx} shot_function 为空")
        person_present = _bool_or(shot.get("person_present"), True)
        shot_face = _dict(shot.get("face_arc"))
        shot_evidence = _items(shot.get("product_evidence"))
        all_evidence.extend(shot_evidence)
        shot_cut = _text(shot.get("cut_to_next"))
        if require_face and person_present:
            if not all(_text(shot_face.get(k)) for k in ("start", "turn", "end")):
                warnings.append(f"镜头{idx} 缺少可观察的 face_arc（start/turn/end）")
        if not shot_cut:
            warnings.append(f"镜头{idx} 缺少 cut_to_next 切镜描述")
        beats = shot.get("beats") or []
        if not beats:
            warnings.append(f"镜头{idx} 没有 beats，将只渲染镜头总览")
            continue
        if len(beats) > 4:
            warnings.append(f"镜头{idx} 有 {len(beats)} 个 beat，建议 1-4 个")
        for j, b in enumerate(beats, 1):
            t = _beat_time(b)
            if not t or t[1] <= t[0]:
                errors.append(f"镜头{idx} beat{j} time 无效")
            elif dur and (t[0] < -0.01 or t[1] > dur + 0.01):
                errors.append(f"镜头{idx} beat{j} 超出镜头时长")
            bdur = _beat_duration(b, dur)
            required = 7 if bdur <= 1.5 else 9 if bdur <= 3 else 10
            missing: list[str] = []
            desc = _text(b.get("description"))
            if desc:
                # 只做“空/截断”sanity 下限；细度由 critic 判断，不设目标字数
                if len(desc) < 40:
                    missing.append(f"description过短({len(desc)}字)")
                cov = {_norm_dimension(x) for x in _items(b.get("coverage"))}
                cov &= set(COVERAGE_DIMS)
                covered = len(cov)
                if covered < required:
                    missing.append(f"coverage({covered}/{required})")
                lack = sorted(core_dims - cov)
                if lack:
                    missing.append("缺少维度:" + ",".join(lack))
                beat_face = _dict(b.get("face_arc") or shot_face)
                if require_face and person_present:
                    if not all(_text(beat_face.get(k)) for k in ("start", "turn", "end")):
                        missing.append("face_arc不完整")
                beat_evidence = _items(b.get("product_evidence"))
                all_evidence.extend(beat_evidence)
                if not beat_evidence and not shot_evidence:
                    missing.append("product_evidence为空")
                beat_cut = _text(b.get("cut_to_next") or shot_cut)
                if not beat_cut:
                    missing.append("cut_to_next为空")
                cont = _nonempty(b.get("continuity"),
                                 ["inherited", "end_state", "transition"])
                # prose beat 允许把连续性写在 description 里；有结构化字段就检查
                if cont and len(cont) < 3:
                    missing.append(f"continuity({len(cont)}/3)")
                beat_reports.append({
                    "shot": idx, "beat": j, "chars": len(desc),
                    "coverage": covered, "required": required,
                    "missing": missing,
                })
            else:
                # 旧结构化 beat 的兼容检查（阈值已提高）
                if not _text(b.get("framing")):
                    missing.append("framing")
                cam = _nonempty(b.get("camera"),
                                ["type", "direction", "speed_curve", "amplitude", "focus"])
                if len(cam) < 4:
                    missing.append(f"camera({len(cam)}/4)")
                light = _nonempty(b.get("light"),
                                  ["source", "direction", "quality", "color", "contrast",
                                   "highlight", "shadow", "rim"])
                if len(light) < 4:
                    missing.append(f"light({len(light)}/4)")
                action = _nonempty(b.get("action"),
                                   ["anticipation", "burst", "settle", "weight", "secondary"])
                if len(action) < 4:
                    missing.append(f"action({len(action)}/4)")
                micro = _items(b.get("micro_state"))
                if len(micro) < 3:
                    missing.append(f"micro({len(micro)}/3)")
                product = _nonempty(b.get("product"),
                                    ["position", "orientation", "contact", "deformation",
                                     "highlight", "detail"])
                if len(product) < 3:
                    missing.append(f"product({len(product)}/3)")
                env = _nonempty(b.get("environment"),
                                ["foreground", "midground", "background",
                                 "atmosphere", "depth"])
                if len(env) < 3:
                    missing.append(f"environment({len(env)}/3)")
                audio = _dict(b.get("audio"))
                speech = _text(audio.get("speech")).lower()
                if speech not in ("", "none", "no speech", "silent", "无口播", "静音"):
                    errors.append(f"镜头{idx} beat{j} 含口播 speech={speech}")
                audio_ok = len(_nonempty(audio, ["ambience", "foley", "music"])) >= 2
                if not audio_ok:
                    missing.append("audio(2)")
                cont = _nonempty(b.get("continuity"),
                                 ["inherited", "end_state", "transition"])
                if len(cont) < 3:
                    missing.append(f"continuity({len(cont)}/3)")

                covered = 1 if (t and t[1] > t[0]) else 0
                covered += 1 if _text(b.get("framing")) else 0
                covered += 1 if len(cam) >= 4 else 0
                covered += 1 if len(light) >= 4 else 0
                covered += 1 if len(action) >= 4 else 0
                covered += 1 if len(micro) >= 3 else 0
                covered += 1 if len(product) >= 3 else 0
                covered += 1 if len(env) >= 3 else 0
                covered += 1 if audio_ok else 0
                covered += 1 if len(cont) >= 3 else 0
                if covered < required:
                    missing.append(f"coverage({covered}/{required})")
                beat_reports.append({
                    "shot": idx, "beat": j, "chars": 0,
                    "coverage": covered, "required": required,
                    "missing": missing,
                })
                for key in ("framing", "render_texture"):
                    if _text(b.get(key)) in ABSTRACT_ONLY:
                        warnings.append(f"镜头{idx} beat{j} {key} 只有抽象词")
                for key in ("camera", "light", "action", "product", "environment",
                            "continuity"):
                    for sk, sv in _dict(b.get(key)).items():
                        if _text(sv) in ABSTRACT_ONLY:
                            warnings.append(f"镜头{idx} beat{j} {key}.{sk} 只有抽象词")
            if missing:
                warnings.append(f"镜头{idx} beat{j} 粒度不足: {', '.join(missing)}")

    for item in must_show:
        if not any(item in e or e in item for e in all_evidence):
            warnings.append(f"must_show 未被 product_evidence 覆盖: {item}")
    constraint_issues = [
        w for w in warnings
        if ("face_arc" in w or "cut_to_next" in w or "must_show" in w)]
    return {
        "errors": errors,
        "warnings": warnings,
        "beats": beat_reports,
        "ok": not errors,
        "granularity_ok": not any(x.get("missing") for x in beat_reports),
        "constraints_ok": not constraint_issues,
    }


def strict() -> bool:
    return C.env("PV_PROMPT_LINT_STRICT", "").lower() in ("1", "true", "yes", "on")
