"""World Selector：候选世界去重、max-min 选择、与 StyleSpec 配对。"""
from __future__ import annotations

from itertools import permutations

from .semantic import semantic_distance, semantic_signature


def _spread(world: dict, worlds: list[dict]) -> float:
    return sum(semantic_distance(world, other) for other in worlds
               if other is not world)


def select_worlds(worlds: list[dict], n: int) -> list[dict]:
    """单批语义 max-min；不读取任何历史 run。"""
    if len(worlds) < n:
        raise ValueError(f"可用 world 不足: {len(worlds)} < {n}")
    # 先选一个“离其他候选最远”的世界作为种子，避免总是取候选列表第一条
    selected = [max(worlds, key=lambda w: _spread(w, worlds))]
    remaining = [w for w in worlds if w is not selected[0]]
    while remaining and len(selected) < n:
        def score(w):
            dist = min(semantic_distance(w, s) for s in selected)
            # 覆盖 bonus：不同 person_need / operator
            need_new = int(w.get("person_need") not in
                           {s.get("person_need") for s in selected})
            op_new = int(w.get("operator") not in
                         {s.get("operator") for s in selected})
            return dist + 0.08 * need_new + 0.05 * op_new
        best = max(remaining, key=score)
        selected.append(best)
        remaining.remove(best)
    return selected


def _compat(world: dict, style: dict) -> float:
    pv = (style.get("visual") or {}).get("person_visibility")
    need = world.get("person_need") or "any"
    score = 1.0
    if need == "on_body" and pv not in ("full", "partial"):
        score -= 0.8
    elif need == "hands" and pv != "hands_only":
        score -= 0.8
    scene = str(world.get("scene") or "")
    sf = (style.get("visual") or {}).get("scene_family")
    if "户外" in scene and sf == "outdoor":
        score += 0.15
    if ("桌面" in scene or "桌" in scene) and sf == "tabletop":
        score += 0.1
    return score


def _fit_style(world: dict, style: dict) -> dict:
    """世界要求优先：不让 hands 世界配到无手风格，也不让 on_body 世界配到手部风格。"""
    need = world.get("person_need") or "any"
    out = dict(style)
    v = dict(out.get("visual") or {})
    pv = v.get("person_visibility")
    if need == "hands" and pv != "hands_only":
        v["person_visibility"] = "hands_only"
        if v.get("presenter_mode") == "direct_speech":
            v["presenter_mode"] = "voiceover"
    elif need == "on_body" and pv not in ("full", "partial"):
        v["person_visibility"] = "full"
    out["visual"] = v
    sig = dict(out.get("visual_signature") or {})
    sig["person_visibility"] = v.get("person_visibility")
    sig["presenter_mode"] = v.get("presenter_mode")
    out["visual_signature"] = sig
    out["creative_world"] = world
    return out


def pair_styles(worlds: list[dict], styles: list[dict]) -> list[tuple[dict, dict]]:
    """把 N 个 world 与 N 个 style 做最优配对，避免 on_body 世界配到 hands_only。"""
    n = min(len(worlds), len(styles))
    if n == 0:
        return []
    if n <= 7:
        best_order, best_score = None, -1e9
        for perm in permutations(range(len(styles)), n):
            score = sum(_compat(worlds[i], styles[j])
                        for i, j in enumerate(perm))
            if score > best_score:
                best_order, best_score = perm, score
        return [(worlds[i], _fit_style(worlds[i], styles[best_order[i]]))
                for i in range(n)]
    # 兜底 greedy
    used, pairs = set(), []
    for w in worlds[:n]:
        cand = max((j for j in range(len(styles)) if j not in used),
                   key=lambda j: _compat(w, styles[j]))
        pairs.append((w, _fit_style(w, styles[cand])))
        used.add(cand)
    return pairs


def coverage(worlds: list[dict]) -> dict:
    def uniq(key):
        return len({str(w.get(key) or "") for w in worlds})
    return {
        "count": len(worlds),
        "unique_titles": uniq("title"),
        "unique_premises": uniq("premise"),
        "unique_devices": uniq("device"),
        "operators": sorted({str(w.get("operator") or "") for w in worlds}),
        "person_need": sorted({str(w.get("person_need") or "") for w in worlds}),
        "core_devices": len({semantic_signature(w).get("core_device") or ""
                             for w in worlds}),
        "core_actions": len({semantic_signature(w).get("core_action") or ""
                             for w in worlds}),
    }
