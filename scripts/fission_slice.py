#!/usr/bin/env python3
"""垂直切片：ref-1471 + 方向一 -> 显式 beat 契约 -> H3 prompt + 对比报告。

只生成 prompt/contract/audit，不调用 H3。

用法：
    .venv/bin/python scripts/fission_slice.py
    .venv/bin/python scripts/fission_slice.py --out data/fission_slices/slice-1471-direction1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import reference_contract as rc  # noqa: E402

REF_ID = "ref-1792419234-1471"
DEFAULT_OUT = ROOT / "data" / "fission_slices" / "slice-1471-direction1"
PLANS = ROOT / "outputs" / "fission" / "fission-20261019-235919" / "plans.json"
REVIEW = (ROOT / "outputs" / "review" /
          "product_video-20261019-235940-9facee_final.json")

DIRECTION = {
    "name": "方向一：指尖倒计时·结构快闪",
    "concept": (
        "用“手部动作节拍器”替代字幕节奏：每一下手指敲击或捏压对应一个结构证据，"
        "观看方式像跟着手指读产品，无字幕无口播，全靠动作切点推进。"),
    "hook": {
        "time": [0.0, 1.0],
        "description": (
            "0-1秒纯白台面上产品正面特写，一只手食指从画面右侧快速入画，"
            "点向桃色蝴蝶结，动作即开始。"),
    },
    "camera": "固定俯拍为主，手部入画动作带轻微手持感，浅景深，产品始终居中",
    "lighting": (
        "室内柔光棚拍，顶部柔光箱 + 侧补光；奶白色不失真，"
        "金色包边有细高光"),
}

GLOBAL = {
    "scene": "纯白哑光台面，无背景道具；产品始终居中。参考案例的纱帘、花艺、木质台面不迁移。",
    "lighting": ("室内柔光棚拍，顶部柔光箱 + 侧补光；奶白色白平衡准确，"
                 "金色包边有细高光，浅景深，阴影干净。"),
    "camera": "固定机位为主，具体角度以每个 beat 为准；手部入画带轻微手持感，产品始终居中，浅景深。",
    "person_policy": "无真人出镜，仅手部入画；手部肤色自然，不佩戴饰品。",
    "audio_policy": "无口播、无台词；只有环境底噪与 BGM。",
    "text_policy": "无字幕、无贴纸、无品牌 logo、无画面文字。",
    "negative": [
        "无口播", "无字幕", "无文字", "无品牌logo", "无真人出镜（仅手部入画）",
        "无多余主体", "商品不变形", "商品不变色", "商品不增减部件",
        "手部结构稳定，不穿模", "不要慢动作", "不要慢速推拉",
        "不要水印", "不要镜像漂移", "不要出现功效宣称文字",
    ],
}

MUST_SHOW = [
    "正面罩杯与花卉蕾丝纹理",
    "金色/香槟金包边",
    "前中桃色蝴蝶结",
    "宽肩带与侧比连接处",
    "背面四排扣",
    "内里点状纹理软支撑",
]
MUST_NOT_CHANGE = [
    "奶白/米白色",
    "花卉蕾丝花型与密度",
    "金色/香槟金包边",
    "前中桃色蝴蝶结位置",
    "四排扣数量与位置",
    "宽肩带结构",
    "无钢圈软支撑结构",
]


def _source(beat_indices, shot_indices, fields_used, overrides, note):
    return {
        "ref_id": REF_ID,
        "beat_indices": beat_indices,
        "shot_indices": shot_indices,
        "fields_used": fields_used,
        "overrides": overrides,
        "note": note,
    }


def build_contract(facet: dict) -> dict:
    # 参考 1471 的 7 个 beat / 7 个镜头：
    # 1 痛点否定 | 2 无钢圈调整型 | 3 舒适聚拢 | 4 肩带加宽
    # 5 四排扣背面 | 6 内里软支撑 | 7 促销CTA
    beats = [
        {
            "index": 1,
            "function": "hook",
            "function_label": "视觉钩子",
            "time": [0.0, 2.5],
            "duration": 2.5,
            "shot_size": "close_up",
            "angle": "俯视",
            "camera": "固定俯拍，手指从画面右侧快速入画，动作带轻微手持感",
            "lighting": GLOBAL["lighting"],
            "composition": "纯白台面，产品正面居中，桃色蝴蝶结与金色包边同框",
            "action": "食指快速点向桃色蝴蝶结，随即沿金色包边滑过；动作在 0-1 秒内开始",
            "product_evidence": ["前中桃色蝴蝶结", "金色/香槟金包边", "正面罩杯与花卉蕾丝纹理"],
            "on_screen_text": "",
            "transition": "硬切",
            "source": _source(
                [2, 3], [1, 2, 3],
                ["shot_size", "composition", "product", "action"],
                ["scene", "angle", "lighting", "camera", "action_detail"],
                "参考 beats 2-3 的正面展示与调整角度动作；场景、俯拍、点触动作按目标方向改写。"),
        },
        {
            "index": 2,
            "function": "structure_strap",
            "function_label": "结构证明·肩带",
            "time": [2.5, 4.5],
            "duration": 2.0,
            "shot_size": "close_up",
            "angle": "侧俯",
            "camera": "固定机位，产品侧向镜头，手指捏住肩带连接处",
            "lighting": GLOBAL["lighting"],
            "composition": "纯白台面，产品侧向，肩带与侧比连接处居中，浅景深",
            "action": "手指捏住肩带连接处轻拉，展示宽肩带与软支撑",
            "product_evidence": ["宽肩带", "肩带与侧比连接处", "无钢圈软支撑"],
            "on_screen_text": "",
            "transition": "硬切",
            "source": _source(
                [4], [4],
                ["shot_size", "composition", "product", "action"],
                ["scene", "angle", "lighting", "camera", "action_detail"],
                "参考 beat 4 肩带加宽 → shot 4 双手捏肩带展示；目标改为单手指捏连接处。"),
        },
        {
            "index": 3,
            "function": "structure_hooks",
            "function_label": "结构证明·四排扣",
            "time": [4.5, 7.0],
            "duration": 2.5,
            "shot_size": "close_up",
            "angle": "平视",
            "camera": "固定近景 + 快速翻转",
            "lighting": GLOBAL["lighting"],
            "composition": "纯白台面，产品背面居中，四排扣完整入画",
            "action": "翻转产品，手指依次点过四排扣每一颗扣子",
            "product_evidence": ["背面四排扣"],
            "on_screen_text": "",
            "transition": "硬切",
            "source": _source(
                [5], [5],
                ["shot_size", "composition", "product", "action"],
                ["scene", "lighting", "camera", "action_detail"],
                "参考 beat 5 四排扣背面 → shot 5 翻转展示；保留景别与构图关系。"),
        },
        {
            "index": 4,
            "function": "material_inner",
            "function_label": "材质证明·内里",
            "time": [7.0, 9.5],
            "duration": 2.5,
            "shot_size": "close_up",
            "angle": "平视略俯",
            "camera": "固定近景 + 微距推近",
            "lighting": GLOBAL["lighting"],
            "composition": "纯白台面，内里居中，点状纹理充满画面",
            "action": "手指翻开内衬，指腹按压点状纹理后松开，展示回弹",
            "product_evidence": ["内里点状纹理", "内里无钢圈/软支撑结构"],
            "on_screen_text": "",
            "transition": "硬切",
            "source": _source(
                [6], [6],
                ["shot_size", "angle", "composition", "product", "action"],
                ["scene", "lighting", "camera", "action_detail"],
                "参考 beat 6 内里软支撑 → shot 6 双手翻开内里；目标改为单手指腹按压回弹。"),
        },
        {
            "index": 5,
            "function": "end_card",
            "function_label": "结尾卡",
            "time": [9.5, 12.0],
            "duration": 2.5,
            "shot_size": "close_up",
            "angle": "平视略俯",
            "camera": "固定机位，轻微推近",
            "lighting": GLOBAL["lighting"],
            "composition": "纯白台面，产品正面居中，双手托举，蕾丝与金边在光下清晰",
            "action": "双手托举产品微转，花卉蕾丝与金色包边在光下清晰，最后定格",
            "product_evidence": ["正面罩杯与花卉蕾丝纹理", "金色/香槟金包边", "前中桃色蝴蝶结"],
            "on_screen_text": "",
            "transition": "结尾定格/淡出",
            "source": _source(
                [3, 7], [2, 3, 7],
                ["shot_size", "composition", "product", "action"],
                ["scene", "lighting", "camera", "action_detail", "on_screen_text"],
                "参考 beat 3 正面展示 + beat 7 shot 7 的侧边蕾丝/金边细节；CTA 文案与字幕明确放弃。"),
        },
    ]

    return {
        "schema_version": "fission-contract/v0",
        "slice_id": "slice-1471-direction1",
        "target": {
            "ref_id": REF_ID,
            "product": {
                "symbol": "<Product 1>",
                "identity": "米白色/奶白色蕾丝无钢圈调整型文胸",
                "description": facet["product"]["description"],
                "must_show": MUST_SHOW,
                "must_not_change": MUST_NOT_CHANGE,
                "wear_state": "平铺/手持展示，不反折遮挡关键细节",
                "matching": "不新增商品图之外的服装部件",
                "reference_policy": "参考图1 = 商品图1（只负责商品本身；忽略图中的手、背景、文字和原有字幕）。",
                "image": "data/reference_runs/fission-20261019-235919/product.jpg",
            },
            "format": {
                "duration": 12,
                "aspect_ratio": "9:16",
                "resolution": "768P",
                "pacing": "fast",
                "voiceover": False,
                "subtitles": False,
            },
        },
        "structure": {
            "name": DIRECTION["name"],
            "concept": DIRECTION["concept"],
            "hook": DIRECTION["hook"],
            "beats": beats,
        },
        "global": GLOBAL,
        "negative": [],
        "facet_coverage": {
            "used": [
                {"facet": "structure.beats[2-3]", "value": "正面展示/调整角度 + 舒适聚拢",
                 "why": "目标 beat 1 的正面产品展示与点触动作"},
                {"facet": "structure.beats[4]", "value": "肩带加宽",
                 "why": "目标 beat 2 的肩带/侧比结构证明"},
                {"facet": "structure.beats[5]", "value": "四排扣背面",
                 "why": "目标 beat 3 的背面结构证明"},
                {"facet": "structure.beats[6]", "value": "内里软支撑",
                 "why": "目标 beat 4 的内里材质证明"},
                {"facet": "structure.beats[3,7]", "value": "正面收束 + 侧边蕾丝/金边细节",
                 "why": "目标 beat 5 的结尾英雄镜头"},
                {"facet": "style.camera_language", "value": "固定机位、close_up、浅景深",
                 "why": "全局机位语法"},
                {"facet": "slots.invariants", "value": "蕾丝/金边/蝴蝶结/宽肩带/四排扣/无钢圈",
                 "why": "商品不可变特征"},
            ],
            "adapted": [
                {"facet": "style.lighting", "value": "暖黄柔光 → 中性柔光棚拍 + 金色高光",
                 "why": "目标方向要求纯白台面与奶白色准确"},
                {"facet": "style.pacing", "value": "缓慢、7镜×6秒 → 快节奏、5 beat×2-2.5秒",
                 "why": "目标方向要求快节奏"},
                {"facet": "timeline[1].composition", "value": "双手托举居中、纱帘花艺虚化 → 纯白台面、产品居中",
                 "why": "场景由目标方向覆盖"},
                {"facet": "timeline[4].angle", "value": "平视 → 侧俯",
                 "why": "固定俯拍方向下展示肩带连接处"},
                {"facet": "structure.hook", "value": "0-3秒痛点否定 → 0-1秒手指点蝴蝶结",
                 "why": "无口播、以动作钩子替代痛点文案"},
            ],
            "waived": [
                {"facet": "structure.beats[1]", "value": "痛点否定",
                 "why": "目标方向无口播、无痛点叙事"},
                {"facet": "structure.beats[7]", "value": "促销 CTA 文案",
                 "why": "目标方向无 CTA；仅复用 shot 7 的侧边蕾丝/金边画面"},
                {"facet": "slots.invariants[字幕]", "value": "白色描边黑体字幕",
                 "why": "目标方向无字幕"},
                {"facet": "transcript", "value": "全片口播转写",
                 "why": "目标方向无口播"},
                {"facet": "roles.platform", "value": "字幕安全区/口播合规提示",
                 "why": "无字幕、无口播；商品功效宣称仍按负面约束规避"},
            ],
        },
        "provenance": {
            "facet": f"data/reference_facets/{REF_ID}.json",
            "alignment": f"data/reference_alignments/{REF_ID}.json",
            "direction_source": "outputs/fission/fission-20261019-235919/plans.json#plan[0]",
        },
    }


def _existing_summary() -> dict:
    out = {"available": False}
    try:
        plans = json.loads(PLANS.read_text(encoding="utf-8"))
        plan = plans[0]
        out.update({
            "available": True,
            "plan_id": plan.get("id"),
            "title": plan.get("title"),
            "shots": [{
                "index": s.get("index"),
                "function": s.get("shot_function"),
                "time": s.get("time"),
                "camera": s.get("camera"),
                "lighting": s.get("lighting"),
                "action": s.get("product_action"),
                "evidence": s.get("product_evidence"),
                "transition": s.get("cut_to_next"),
            } for s in plan.get("shots") or []],
        })
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    try:
        review = json.loads(REVIEW.read_text(encoding="utf-8"))
        out["prompt"] = review.get("prompt") or ""
        out["prompt_chars"] = len(out["prompt"])
    except Exception as e:
        out["prompt_chars"] = 0
        out["prompt_error"] = f"{type(e).__name__}: {e}"
    return out


def render_diff(contract: dict, facet: dict, existing: dict) -> str:
    stats = rc.contract_stats(contract, facet)
    beats = contract["structure"]["beats"]
    lines = ["# 垂直切片对比：ref-1471 + 方向一", ""]
    lines.append("## 1. 现有 variant_01（旧链路）")
    lines.append("")
    if existing.get("available"):
        lines.append(f"- plan：`{existing.get('plan_id')}` · {existing.get('title')}")
        lines.append(f"- prompt 长度：{existing.get('prompt_chars', 0)} 字符")
        lines.append("")
        lines.append("| 镜 | 时间 | 功能 | 机位 | 动作 | 商品证据 |")
        lines.append("|---:|---|---|---|---|---|")
        for s in existing.get("shots") or []:
            t = s.get("time") or [0, 0]
            lines.append(f"| {s.get('index')} | {t[0]:.1f}-{t[1]:.1f}s | "
                         f"{s.get('function')} | {s.get('camera')} | "
                         f"{s.get('action')} | {'、'.join(s.get('evidence') or [])} |")
    else:
        lines.append("- 旧产物不可用：" + str(existing.get("error") or existing.get("prompt_error")))
    lines.append("")
    lines.append("## 2. 新契约（本切片）")
    lines.append("")
    lines.append("| beat | 时间 | 功能 | 景别/角度 | 机位 | 动作 | 商品证据 | 来源 |")
    lines.append("|---:|---|---|---|---|---|---|---|")
    for b in beats:
        t = b["time"]
        src = b["source"]
        lines.append(f"| {b['index']} | {t[0]:.1f}-{t[1]:.1f}s | "
                     f"{b['function_label']} | {b['shot_size']} / {b['angle']} | "
                     f"{b['camera']} | {b['action']} | "
                     f"{'、'.join(b['product_evidence'])} | "
                     f"ref beat {src['beat_indices']} → shot {src['shot_indices']} |")
    lines.append("")
    lines.append("## 3. 对比")
    lines.append("")
    old_shots = existing.get("shots") or []
    old_hook = next((s for s in old_shots if s.get("function") == "视觉钩子"), None)
    old_hook_pos = (f"第 {old_hook.get('index')} 镜 "
                    f"{old_hook.get('time')[0]:.1f}-{old_hook.get('time')[1]:.1f}s"
                    if old_hook else "无")
    new_hook = next((b for b in beats if b.get("function") == "hook"), None)
    new_hook_pos = (f"第 {new_hook.get('index')} beat "
                    f"{new_hook.get('time')[0]:.1f}-{new_hook.get('time')[1]:.1f}s"
                    f"（动作 0-1s 开始）" if new_hook else "无")
    rows = [
        ("分镜数", str(len(old_shots)), str(len(beats))),
        ("hook 位置", old_hook_pos, new_hook_pos),
        ("每镜字段", "function/time/camera/action/evidence/transition（6）",
         "function/time/shot_size/angle/camera/lighting/composition/action/evidence/text/transition/source（12）"),
        ("参考来源", "0 条显式来源", f"{stats['beats_with_source']}/{stats['beat_count']} beat 带来源"),
        ("参考 beat 使用", "无记录",
         f"{len(stats['reference_beats_used'])}/{stats['reference_beat_count']}"
         f"（{stats['reference_beats_used']}；beat 1 放弃，beat 7 仅放弃 CTA 文案）"),
        ("参考镜头使用", "无记录",
         f"{len(stats['reference_shots_used'])}/{stats['reference_shot_count']}"
         f"（{stats['reference_shots_used']}；shot 7 为部分复用）"),
        ("方向 camera/lighting", "仅 hook 镜使用，其余硬编码",
         "5/5 beat 均写入方向指定的机位与光线"),
        ("template 结构选项", "0 项进入 prompt", "方向 beats 1:1 进入 prompt"),
        ("字段可追溯", "无", "每 beat 有 source.beat_indices/shot_indices/fields_used/overrides"),
    ]
    lines.append("| 维度 | 旧链路 | 新契约 |")
    lines.append("|---|---|---|")
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    lines.append("")
    lines.append("## 4. 字段是否够用")
    lines.append("")
    lines.append("- 本方向所需字段均在 facet 中找到：景别、角度、机位、光线、构图、动作、"
                 "商品证据、转场、来源 beat/shot、参考改写记录。没有出现“缺字段导致无法落笔”。")
    lines.append("- 明确的边界：")
    lines.append("  1. 手部动作目前只有 `timeline[].action` 的文本粒度；如果要精确到手指姿态/左右手/力度，"
                 "需要在 facet 增加 hand 子槽位或关键帧级描述。")
    lines.append("  2. `shot_size` / `camera` 是参考描述里的枚举/短句（如 `close_up`、`static`），"
                 "批量渲染前需要一层词典或人工确认。")
    lines.append("  3. 场景/光线是目标方向主动覆盖参考的槽位，已在 `facet_coverage.adapted` 中记录；"
                 "这不是“丢失”，但下游必须尊重 override。")
    lines.append("")
    lines.append("## 5. 结论")
    lines.append("")
    lines.append("契约字段足够支撑这条方向；旧链路的核心问题不是字段不够，而是没有把 "
                 "facet 的结构/镜头字段按 beat 回填。下一步可把 `make_variant_briefs` 的"
                 "输出 schema 改成 `structure.beats[]`，并让 `build_controlled_plan` 直接消费 beats，"
                 "不再走 `_order_from_beat_order` 的 4 模块折叠。")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="ref-1471 + 方向一 垂直切片")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    facet = rc.load_facet(REF_ID)
    contract = build_contract(facet)
    validation = rc.validate_contract(contract, facet)
    contract["_validation"] = validation
    if not validation["ok"]:
        print("契约校验失败：")
        for e in validation["errors"]:
            print(" -", e)
        sys.exit(1)

    prompt = rc.render_h3_prompt(contract)
    audit = rc.render_audit(contract, facet)
    existing = _existing_summary()
    diff = render_diff(contract, facet, existing)

    (out / "contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "prompt_h3.txt").write_text(prompt, encoding="utf-8")
    (out / "prompt_audit.md").write_text(audit, encoding="utf-8")
    (out / "diff.md").write_text(diff, encoding="utf-8")

    stats = rc.contract_stats(contract, facet)
    print(json.dumps({
        "out": str(out),
        "validation": validation,
        "stats": stats,
        "prompt_chars": len(prompt),
        "existing_prompt_chars": existing.get("prompt_chars", 0),
        "files": ["contract.json", "prompt_h3.txt", "prompt_audit.md", "diff.md"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
