#!/usr/bin/env python3
"""个体带货垂直切片：bd6f 真人结构 + 32b0 文案/多色 + 1471 商品。

只生成 contract / prompt / voiceover / srt / diff，不调用 H3。

用法：
    .venv/bin/python scripts/fission_ugc_slice.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import media, reference_contract as rc  # noqa: E402

REF_PRODUCT = "ref-1792419234-1471"
REF_STRUCT = "ref-1792419234-bd6f"
REF_CLAIMS = "ref-1792419234-32b0"
OUT = ROOT / "data" / "fission_slices" / "slice-1471-ugc-direction1"
PERSON = "assets/persons/半身照.png"
PRODUCT_IMG = "data/reference_runs/fission-20261019-235919/product.jpg"

VOICEOVER = (
    "小胸姐妹别划走，这件无钢圈内衣真能聚拢。"
    "宽肩带加高侧比，背面四排扣稳稳托住。"
    "奶白蕾丝百搭，通勤居家都能穿。"
    "今天有活动价，点下方看。"
)

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

GLOBAL = {
    "scene": "居家客厅/卧室：米色窗帘、浅木色柜、沙发一角，自然窗光；不要纯白影棚、不要影楼背景、不要产品目录感。",
    "lighting": "自然窗光 + 室内暖光，柔和但不过度磨皮；手机竖屏 UGC 质感，保留轻微噪点和真实肤色。",
    "camera": "手机竖屏手持感：中景口播、近景产品特写、轻微推拉/晃动；不要固定对称广告机位、不要三脚架感。",
    "person_policy": "真人女主播出镜，短发，脸型/发型/体型/肤色与参考图1一致；穿米色针织开衫或白衬衫，领口正常，不暴露；面对镜头口播，有自然手势和表情，口型与台词同步。",
    "audio_policy": "H3 原生同步音频：真人女主播中文普通话口播，语速偏快、热情自然；居家客厅轻微环境底噪；轻快流行 BGM（低音量，卡点切镜）；手指点产品/翻扣/切镜 whoosh 轻音效。每个 beat 的 voiceover 就是台词；口型与台词同步；不要后期 TTS。",
    "text_policy": "字幕后期叠加（白字黑边、大字号、居中偏下），不要生成在画面里；无品牌 logo、无平台水印。",
    "negative": [
        "不要纯白影棚", "不要影楼背景", "不要产品目录感",
        "不要固定对称广告机位", "不要三脚架感", "不要无人物",
        "不要慢动作", "不要画面内生成字幕/文字/贴纸",
        "不要品牌logo", "不要平台水印", "商品不变形", "商品不变色",
        "商品不增减部件", "不要暴露/低俗", "不要镜像漂移",
        "不要假人滑行",
    ],
}


def _source(beat_indices, shot_indices, fields_used, note):
    return {
        "ref_id": REF_STRUCT,
        "beat_indices": beat_indices,
        "shot_indices": shot_indices,
        "fields_used": fields_used,
        "overrides": ["人物", "口播", "字幕", "居家场景", "价格CTA"],
        "note": note,
    }


def build_contract(product_facet: dict) -> dict:
    beats = [
        {
            "index": 1,
            "function": "hook",
            "function_label": "痛点钩子",
            "time": [0.0, 2.5],
            "duration": 2.5,
            "shot_size": "medium",
            "angle": "平视",
            "camera": "手机竖屏手持中景，轻微晃动",
            "lighting": GLOBAL["lighting"],
            "composition": "真人半身居中，右手持文胸举到胸前，居家客厅背景虚化",
            "action": "真人面对镜头说话，右手把文胸举到胸前展示正面，左手做手势",
            "product_evidence": ["正面罩杯与花卉蕾丝纹理", "前中桃色蝴蝶结"],
            "on_screen_text": "小胸姐妹别划走",
            "transition": "硬切",
            "information": {
                "claim": "小胸也能穿出自然聚拢",
                "proof": "真人手持文胸正面展示 + 口播痛点",
                "text_overlay": "小胸姐妹别划走",
                "voiceover": "小胸姐妹别划走，这件无钢圈内衣真能聚拢。",
                "persona": "真人女主播，短发，米色针织开衫",
                "context": "居家客厅，自然窗光",
                "offer_cta": "",
            },
            "source": _source(
                [1], [1],
                ["shot_size", "composition", "action", "on_screen_text"],
                "bd6f 痛点质问 + 真人手持产品开场；换成文胸与小胸主张。"),
        },
        {
            "index": 2,
            "function": "proof",
            "function_label": "结构证明",
            "time": [2.5, 5.5],
            "duration": 3.0,
            "shot_size": "close_up",
            "angle": "俯视/平视略俯",
            "camera": "手持近景，产品在画面中轻微移动",
            "lighting": GLOBAL["lighting"],
            "composition": "居家桌面近景，双手按压罩杯/捏肩带，背景是浅木桌面",
            "action": "手指按压罩杯回弹，捏肩带展示宽肩带，翻转背面点四排扣",
            "product_evidence": ["正面罩杯与花卉蕾丝纹理", "宽肩带", "背面四排扣", "内里软支撑"],
            "on_screen_text": "无钢圈也能聚拢",
            "transition": "硬切",
            "information": {
                "claim": "无钢圈不勒，宽肩带+四排扣稳住",
                "proof": "按压罩杯回弹、捏肩带、翻背面点四排扣",
                "text_overlay": "无钢圈也能聚拢",
                "voiceover": "宽肩带加高侧比，背面四排扣稳稳托住。",
                "persona": "手部/产品特写",
                "context": "居家桌面近景",
                "offer_cta": "",
            },
            "source": _source(
                [4, 5], [6, 7],
                ["shot_size", "composition", "action", "on_screen_text"],
                "bd6f 面料/弹力与耐洗证明的“手持结构演示”语法；换成文胸结构。"),
        },
        {
            "index": 3,
            "function": "context",
            "function_label": "场景/多色",
            "time": [5.5, 8.5],
            "duration": 3.0,
            "shot_size": "medium_close_up",
            "angle": "平视",
            "camera": "手持中景，轻微推近",
            "lighting": GLOBAL["lighting"],
            "composition": "真人穿米色衬衫/针织开衫，展示领口与肩带；切奶白/浅灰/黑色多色平铺",
            "action": "真人侧身展示肩带/领口，手抚领口；切到多色平铺，手指点色",
            "product_evidence": ["肩带", "领口搭配", "多色可选"],
            "on_screen_text": "奶白蕾丝 百搭不挑人",
            "transition": "硬切",
            "information": {
                "claim": "奶白蕾丝百搭，通勤居家都能穿",
                "proof": "真人外搭衬衫展示肩带/领口 + 多色平铺",
                "text_overlay": "奶白蕾丝 百搭不挑人",
                "voiceover": "奶白蕾丝百搭，通勤居家都能穿。",
                "persona": "真人女主播",
                "context": "卧室/衣帽间，换一套通勤穿搭",
                "offer_cta": "",
            },
            "source": _source(
                [6], [8],
                ["shot_size", "composition", "action", "on_screen_text"],
                "bd6f 多色收纳收束 → 换成本品多色/穿搭；32b0 五色平铺补充。"),
        },
        {
            "index": 4,
            "function": "cta",
            "function_label": "价格/CTA",
            "time": [8.5, 12.0],
            "duration": 3.5,
            "shot_size": "medium",
            "angle": "平视",
            "camera": "手持中景，轻微推近，手指向画面下方",
            "lighting": GLOBAL["lighting"],
            "composition": "真人半身居中，手持文胸，另一只手指向下方购物车位置",
            "action": "真人面对镜头说 CTA，手指向下方，产品保持在胸前",
            "product_evidence": ["正面罩杯与花卉蕾丝纹理", "前中桃色蝴蝶结"],
            "on_screen_text": "点下方看活动价",
            "transition": "结尾定格",
            "information": {
                "claim": "今天活动价，点下方看",
                "proof": "真人手持产品 + 价格标签后期叠加",
                "text_overlay": "点下方看活动价",
                "voiceover": "今天有活动价，点下方看。",
                "persona": "真人女主播",
                "context": "居家客厅",
                "offer_cta": "点下方看活动价",
            },
            "source": _source(
                [6], [8],
                ["shot_size", "composition", "action"],
                "bd6f 结尾多色收束 → 目标改为价格/CTA；价格文案为目标新增。"),
        },
    ]

    return {
        "schema_version": "fission-contract/v1-ugc",
        "slice_id": "slice-1471-ugc-direction1",
        "target": {
            "ref_id": REF_PRODUCT,
            "references": [
                {
                    "index": 1,
                    "kind": "person",
                    "label": "固定人物照片1",
                    "path": PERSON,
                    "policy": "只保留人物身份；忽略她的运动内衣、短裤、鞋和白背景；换成米色针织开衫/白衬衫，居家场景。",
                },
                {
                    "index": 2,
                    "kind": "product",
                    "label": "商品图1",
                    "path": PRODUCT_IMG,
                    "policy": "只负责商品本身；忽略图中的手、背景、文字；不要把商品图里的手/背景带进画面。",
                },
            ],
            "person": {
                "symbol": "<Person 1>",
                "reference_index": 1,
                "identity": "短发亚洲女性，脸型、发型、体型、肤色与参考图1一致",
                "immutable": ["脸型", "短发发型", "体型", "肤色"],
                "policy": "不要换脸、不要改变发型/体型；换成米色针织开衫或白衬衫，居家客厅/卧室。",
            },
            "product": {
                "symbol": "<Product 1>",
                "reference_index": 2,
                "identity": "米白色/奶白色蕾丝无钢圈调整型文胸",
                "description": product_facet["product"]["description"],
                "image": PRODUCT_IMG,
                "reference_policy": "参考图2只负责商品本身；忽略图中的手、背景、文字；不要把商品图里的手/背景带进画面。",
                "must_show": MUST_SHOW,
                "must_not_change": MUST_NOT_CHANGE,
                "wear_state": "真人手持/平铺展示；真人上身时外搭衬衫/针织开衫，只露肩带与领口，不暴露。",
                "matching": "不新增商品图之外的服装部件",
            },
            "format": {
                "duration": 12,
                "aspect_ratio": "9:16",
                "resolution": "768P",
                "pacing": "fast",
                "archetype": "ugc_individual_seller",
                "voiceover": True,
                "subtitles": True,
            },
        },
        "structure": {
            "name": "个体带货·痛点口播·12秒",
            "concept": "真人主播居家口播，先戳小胸/勒副乳痛点，再用结构证明和无钢圈体感建立信任，最后用多色/百搭和活动价收口。",
            "hook": {
                "time": [0.0, 1.5],
                "description": "0-1.5秒真人中景，第一句痛点出口，产品在1秒内入画。",
            },
            "beats": beats,
        },
        "global": GLOBAL,
        "information_budget": {
            "claims": 4,
            "proofs": 2,
            "text_overlays": 4,
            "voiceovers": 4,
            "personas": 4,
            "contexts": 2,
            "offer_cta": 1,
        },
        "facet_coverage": {
            "used": [
                {"facet": "bd6f.structure.beats[1]", "value": "痛点质问",
                 "why": "真人开场 + 第一句痛点"},
                {"facet": "bd6f.structure.beats[4-5]", "value": "面料/弹力 + 耐洗证明",
                 "why": "手持结构演示语法"},
                {"facet": "bd6f.structure.beats[6]", "value": "多色收纳收束",
                 "why": "多色/场景收尾"},
                {"facet": "32b0.structure.beats[1-3]", "value": "真人上身/按压/五色平铺",
                 "why": "文胸具体卖点与多色展示"},
                {"facet": "1471.product", "value": "商品身份与不可变特征",
                 "why": "商品图与硬约束"},
                {"facet": "bd6f.roles.marketing", "value": "卖点顺序/证明方式/CTA",
                 "why": "信息密度设计"},
            ],
            "adapted": [
                {"facet": "bd6f.global.scene", "value": "家居/桌面 → 居家客厅/卧室",
                 "why": "文胸带货的家居场景"},
                {"facet": "bd6f.text", "value": "内裤卫生文案 → 文胸聚拢/结构/百搭文案",
                 "why": "商品品类不同"},
                {"facet": "32b0.structure.beats[3]", "value": "五色平铺 → 多色 + 真人穿搭",
                 "why": "目标 12 秒内同时给配色与场景"},
            ],
            "waived": [
                {"facet": "bd6f.structure.beats[2-3]", "value": "独立包装/EO灭菌",
                 "why": "文胸商品不适用"},
                {"facet": "bd6f.structure.beats[5]", "value": "水洗300次",
                 "why": "无检测报告，避免不可验证宣称"},
                {"facet": "1471.style", "value": "纯白影棚/固定机位/浅景深广告感",
                 "why": "目标改为居家 UGC"},
                {"facet": "1471.structure.beats[7]", "value": "具体价格/促销口播",
                 "why": "价格未知，改为“活动价，点下方看”"},
            ],
        },
        "negative": [],
        "provenance": {
            "facet": f"data/reference_facets/{REF_PRODUCT}.json",
            "alignment": f"data/reference_alignments/{REF_PRODUCT}.json",
            "reference_refs": [REF_STRUCT, REF_CLAIMS, REF_PRODUCT],
            "structure_ref": f"data/reference_facets/{REF_STRUCT}.json",
            "claims_ref": f"data/reference_facets/{REF_CLAIMS}.json",
        },
    }


def render_diff(contract: dict, product_contract_path: Path) -> str:
    old = json.loads(product_contract_path.read_text(encoding="utf-8")) \
        if product_contract_path.exists() else {}
    old_fmt = ((old.get("target") or {}).get("format") or {})
    new_fmt = ((contract.get("target") or {}).get("format") or {})
    old_beats = len(((old.get("structure") or {}).get("beats") or []))
    new_beats = len(((contract.get("structure") or {}).get("beats") or []))
    info = rc.contract_stats(contract, rc.load_facet(REF_STRUCT))["information"]
    lines = ["# 个体带货切片 vs 产品说明片", ""]
    lines.append("| 维度 | 产品说明片（variant_contract） | 个体带货切片 |")
    lines.append("|---|---|---|")
    lines.append(f"| archetype | product_demo | {new_fmt.get('archetype')} |")
    lines.append(f"| 分镜数 | {old_beats} | {new_beats} |")
    lines.append(f"| 真人 | 仅手部 | 真人女主播出镜 |")
    lines.append(f"| 口播 | 无 | {info['voiceovers']} 条 |")
    lines.append(f"| 字幕 | 无 | {info['text_overlays']} 条 |")
    lines.append(f"| 明确卖点 | 0 条主张 | {info['claims']} 条 |")
    lines.append(f"| 证明 | 4 个结构展示 | {info['proofs']} 个证明 |")
    lines.append(f"| 场景 | 纯白台面 | {info['contexts']} 个居家场景 |")
    lines.append(f"| 价格/CTA | 无 | {info['offer_cta']} 个 |")
    lines.append("")
    lines.append("目标：12 秒内至少 4 个卖点、2 个证明、4 条口播/字幕、真人、2 个场景、1 个 CTA。")
    return "\n".join(lines) + "\n"


def main():
    product_facet = rc.load_facet(REF_PRODUCT)
    contract = build_contract(product_facet)
    facet = rc.load_facet(REF_STRUCT)
    validation = rc.validate_contract(contract, facet)
    contract["_validation"] = validation
    if not validation["ok"]:
        print("契约校验失败：")
        for e in validation["errors"]:
            print(" -", e)
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    prompt = rc.render_h3_prompt(contract)
    audit = rc.render_audit(contract, facet)
    diff = render_diff(contract, ROOT / "data/fission_slices/slice-1471-direction1/contract.json")
    (OUT / "contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "prompt_h3.txt").write_text(prompt, encoding="utf-8")
    (OUT / "prompt_audit.md").write_text(audit, encoding="utf-8")
    (OUT / "voiceover.txt").write_text(VOICEOVER + "\n", encoding="utf-8")
    media.text_to_srt(VOICEOVER, 12.0, OUT / "subtitles.srt")
    (OUT / "diff_vs_product_demo.md").write_text(diff, encoding="utf-8")
    stats = rc.contract_stats(contract, facet)
    print(json.dumps({
        "out": str(OUT),
        "validation": validation,
        "info": stats["information"],
        "prompt_chars": len(prompt),
        "files": ["contract.json", "prompt_h3.txt", "prompt_audit.md",
                  "voiceover.txt", "subtitles.srt", "diff_vs_product_demo.md"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
