"""参考案例库的检索与泛化（retrieval + generalizer）。

- 把 data/reference_cases/*/descriptions.json 摊平成 facet 文档；
- BM25 检索（中文用 jieba 分词，无需向量库）；
- 把 top-k 文档交给 LLM 归纳成 constraint template，供下游 decoder 使用。
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from . import config as C, llm
from .jsonutil import extract_json

log = logging.getLogger("reference_retrieval")

CASES_DIR = C.ROOT / "data" / "reference_cases"
INDEX_DIR = C.ROOT / "data" / "reference_index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)
DOCS_PATH = INDEX_DIR / "documents.jsonl"

_PUNCT = re.compile(r"[\s，。！？；：、,.!?;:\"'“”‘’（）()\[\]{}<>《》/\\|~`@#$%^&*+=_-]+")


def _load_jieba():
    try:
        import jieba
        return jieba
    except Exception:
        return None


_JIEBA = _load_jieba()


def tokenize(text: str) -> list[str]:
    text = str(text or "").lower()
    text = _PUNCT.sub(" ", text)
    if _JIEBA:
        toks = [t.strip() for t in _JIEBA.lcut(text)]
    else:
        toks = re.findall(r"[一-鿿]{1,3}|[a-z0-9]+", text)
    stop = {"的", "了", "是", "在", "和", "与", "一个", "这个", "那个",
            "我们", "你们", "他们", "画面", "视频", "可以", "没有", "很"}
    return [t for t in toks if len(t) > 0 and t not in stop]


def load_cases() -> list[dict]:
    out = []
    for p in sorted(CASES_DIR.glob("*/descriptions.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("读取案例失败 %s: %s", p, e)
    return out


def _meta(case: dict) -> dict:
    m = case.get("meta") or {}
    g = case.get("global") or {}
    return {
        "ref_id": case.get("ref_id"),
        "category": g.get("category") or "",
        "tags": m.get("tags") or [],
        "duration": m.get("duration"),
        "source_url": m.get("source_url") or "",
        "title": m.get("title") or "",
    }


def flatten_case(case: dict) -> list[dict]:
    meta = _meta(case)
    ref = case.get("ref_id")
    docs: list[dict] = []

    def add(kind: str, dimension: str, text: str, **extra):
        text = (text or "").strip()
        if not text:
            return
        docs.append({
            "doc_id": f"{ref}:{kind}:{extra.get('index', 0)}",
            "ref_id": ref, "kind": kind, "dimension": dimension,
            "text": text, "metadata": {**meta, **extra},
        })

    g = case.get("global") or {}
    add("global", "global", " ".join(str(g.get(k) or "") for k in (
        "category", "scene", "visual_style", "lighting", "pacing",
        "camera_language", "on_screen_text_style", "product")))
    for s in case.get("shots") or []:
        add("shot", "visual", " ".join(str(s.get(k) or "") for k in (
            "shot_size", "angle", "camera", "lighting", "color",
            "composition", "subject", "action", "product",
            "product_visibility", "on_screen_text", "transition")),
            index=s.get("index"), start=s.get("start"), end=s.get("end"))
    for role, d in (case.get("roles") or {}).items():
        if not isinstance(d, dict):
            continue
        text = " ".join(
            [str(x) for x in (d.get("observations") or [])]
            + [str(x) for x in (d.get("inferences") or [])]
            + [str(x) for x in (d.get("key_moments") or [])])
        add("role", role, text)
    bp = case.get("blueprint") or {}
    add("blueprint", "style", bp.get("global_style") or "")
    add("blueprint", "structure", " ".join(
        [str(bp.get("structure") or "")]
        + [f"不变:{x}" for x in (bp.get("invariants") or [])]
        + [f"软约束:{x}" for x in (bp.get("soft_constraints") or [])]
        + [f"硬约束:{x}" for x in (bp.get("hard_constraints") or [])]))
    add("blueprint", "shot_prompts", " ".join(
        str(s.get("prompt") or "") for s in (bp.get("shot_prompts") or [])))
    if case.get("transcript"):
        add("transcript", "speech", " ".join(
            str(s.get("text") or "") for s in case["transcript"]))
    return docs


def build_index() -> dict:
    cases = load_cases()
    docs: list[dict] = []
    for c in cases:
        docs.extend(flatten_case(c))
    with open(DOCS_PATH, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    index = {
        "generated_at": int(time.time()),
        "cases": len(cases),
        "documents": len(docs),
        "refs": [c.get("ref_id") for c in cases],
    }
    (INDEX_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def load_docs() -> list[dict]:
    if not DOCS_PATH.exists():
        build_index()
    docs = []
    with open(DOCS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


class _Index:
    def __init__(self, docs: list[dict]):
        from rank_bm25 import BM25Okapi
        self.docs = docs
        self.tokens = [tokenize(d.get("text") or "") for d in docs]
        self.bm25 = BM25Okapi(self.tokens) if self.tokens else None

    def search(self, query: str, k: int = 12,
               role: str | None = None,
               dimension: str | None = None,
               tags_any: list[str] | None = None) -> list[dict]:
        if not self.docs:
            return []
        q = tokenize(query)
        scores = self.bm25.get_scores(q) if (self.bm25 and q) else [0.0] * len(self.docs)
        # 无 BM25 命中时退回字面匹配
        if q and max(scores) <= 0:
            qs = set(q)
            scores = [float(len(qs & set(t))) for t in self.tokens]
        idx = sorted(range(len(self.docs)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in idx:
            d = self.docs[i]
            md = d.get("metadata") or {}
            if role and not (d.get("kind") == "role"
                             and d.get("dimension") == role):
                continue
            if dimension and d.get("dimension") != dimension:
                continue
            if tags_any and not any(t in (md.get("tags") or []) for t in tags_any):
                continue
            if scores[i] <= 0 and q:
                continue
            item = dict(d)
            item["score"] = round(float(scores[i]), 4)
            item["snippet"] = (d.get("text") or "")[:280]
            out.append(item)
            if len(out) >= k:
                break
        return out


_INDEX: _Index | None = None


def get_index() -> _Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = _Index(load_docs())
    return _INDEX


def retrieve(query: str, k: int = 12, **filters) -> list[dict]:
    return get_index().search(query, k=k, **filters)


FALLBACK_TEMPLATE = {
    "summary": "参考案例以产品特写、手部演示、逐点字幕为主；本条按快节奏、无口播、产品证据优先执行。",
    "invariants": [
        "前 1-3 秒必须出现商品或商品动作",
        "镜头以产品特写/近景为主，人物只做身份与穿着展示",
        "每个镜头至少一个商品画面证据",
        "快节奏、正常速度，禁止慢动作",
    ],
    "variables": ["人物", "场景", "字幕措辞", "具体运镜", "优惠信息"],
    "hard_constraints": [
        "商品颜色/材质/版型/细节不可变",
        "不新增商品图之外的服装部件",
        "无口播、无品牌 logo、无额外人物",
        "9:16，4-15 秒",
    ],
    "soft_constraints": [
        "hook 用痛点反问或产品特写",
        "结构：钩子 → 商品揭晓 → 材质/结构证明 → 使用/上身 → 结尾",
        "镜头 3-6 个，每镜 2-4 秒",
    ],
    "structure_options": [
        {"name": "痛点反问", "hook": "不要再穿钢圈内衣了",
         "beat_order": ["痛点", "产品特写", "柔软证明", "结构", "结尾"],
         "pacing": "快", "camera": "固定近景 + 手部演示",
         "proof": "挤压回弹/内里无钢圈", "cta": "结尾定格",
         "on_screen_text": "无"},
        {"name": "材质证明", "hook": "极近特写蕾丝纹理",
         "beat_order": ["材质特写", "拉伸手感", "内里结构", "上身", "结尾"],
         "pacing": "快", "camera": "微距横移 + 近景",
         "proof": "蕾丝/金边/回弹", "cta": "结尾定格",
         "on_screen_text": "无"},
        {"name": "结构拆解", "hook": "正面罩杯",
         "beat_order": ["正面", "背面四排扣", "肩带/侧翼", "内里", "结尾"],
         "pacing": "快", "camera": "固定近景 + 翻转",
         "proof": "四排扣/软支撑/无钢圈", "cta": "结尾定格",
         "on_screen_text": "无"},
    ],
    "evidence_refs": [],
}


def generalize(query: str, docs: list[dict],
               product_desc: str = "") -> dict:
    if not docs:
        return dict(FALLBACK_TEMPLATE)
    context = []
    for d in docs[:16]:
        context.append(
            f"### {d.get('ref_id')} · {d.get('kind')}/{d.get('dimension')}\n"
            f"{d.get('text')[:900]}")
    prompt = f"""新素材 brief：
{query}

商品描述：
{product_desc or '（未单独提供，见案例）'}

参考案例片段（来自视频池的多视角描述）：
{chr(10).join(context)[:16000]}

请把上述案例泛化成一份可执行的约束模板。要求：
1. 不要复述单条案例，要归纳多条案例的共性、变体和边界；
2. invariants 是必须保留的结构/风格；
3. variables 是可替换的内容槽位；
4. hard_constraints 是商品/平台/合规的硬约束；
5. soft_constraints 是 hook、beat、节奏、镜头语言等软约束；
6. structure_options 只给 3 个可执行的裂变结构，每个含 hook/beat_order/pacing/camera/proof/cta/on_screen_text；
7. evidence_refs 写支持这些结论的 ref_id；
8. 每个字段尽量简短，总输出控制在 3000 字以内。
只输出 JSON，结构：
{{
 "summary": "",
 "invariants": [],
 "variables": [],
 "hard_constraints": [],
 "soft_constraints": [],
 "structure_options": [
   {{"name":"","hook":"","beat_order":[],"pacing":"","camera":"","proof":"","cta":"","on_screen_text":""}}
 ],
 "evidence_refs": []
}}"""
    last = None
    for attempt in range(2):
        try:
            user = prompt if attempt == 0 else (
                prompt + "\n\n上一次输出过长或不是合法 JSON。"
                "这次只输出 JSON；structure_options 只给 3 个，"
                "每个字段不超过 40 字，总输出不超过 2500 字。")
            txt = llm.LLM(model=C.env("REFERENCE_LLM_MODEL", "deepseek-chat"), timeout=180).chat(
                user, max_tokens=8000,
                temperature=0.3 if attempt == 0 else 0.15,
                json_mode=True)
            data = extract_json(txt)
            if data:
                return data
            last = "JSON 解析失败"
            log.warning("泛化尝试 %d 输出无 JSON: %s", attempt + 1,
                        txt[:300])
        except Exception as e:
            last = e
            log.warning("泛化尝试 %d 失败: %s", attempt + 1, e)
    log.warning("泛化最终失败，使用兜底模板: %s", last)
    return dict(FALLBACK_TEMPLATE)


def build_reference_brief(query: str, product_desc: str = "",
                          k: int = 12,
                          run_dir: Path | None = None) -> dict:
    docs = retrieve(query, k=k)
    template = generalize(query, docs, product_desc)
    out = {"query": query, "product_desc": product_desc,
           "docs": docs, "template": template}
    if run_dir:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "retrieved.json").write_text(
            json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "template.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return out
