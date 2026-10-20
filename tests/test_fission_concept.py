"""Concept 层测试：world schema、距离、world→style 配对。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.anchor import build_anchor  # noqa: E402
from pipelines.fission.concept.critic import critique  # noqa: E402
from pipelines.fission.concept.schema import normalize, validate, world_distance  # noqa: E402
from pipelines.fission.concept.selector import pair_styles, select_worlds  # noqa: E402
from pipelines.fission.concept.semantic import (contract_semantic_audit,
                                                semantic_audit,
                                                semantic_distance)  # noqa: E402
from pipelines.fission.profiles import load_profile  # noqa: E402


def _world(title: str, need: str = "hands") -> dict:
    return {
        "title": title,
        "premise": f"{title}：早上整理抽屉，三条内裤按顺序摆开。",
        "tension": "旧内裤卷边、夹臀，早上总是翻找。",
        "device": "抽屉 + 三条轮换 + 手指逐一检查",
        "turn": "发现包边平整、底裆加长",
        "payoff": "抽屉只留三条，按颜色取用",
        "scene": "卧室抽屉前",
        "props": ["抽屉", "三条内裤"],
        "visual_motifs": ["抽屉开合", "三色排列"],
        "person_need": need,
        "proof_rituals": [
            {"action": "手指拉开包边再松手", "evidence": "无痕包边与三角版型",
             "claim_ids": ["feature_05"]},
            {"action": "翻开底裆对比长度", "evidence": "加长纯棉底裆",
             "claim_ids": ["feature_04"]},
        ],
        "claim_ids": ["feature_05", "feature_04"],
        "operator": "test",
    }


class TestConcept(unittest.TestCase):
    def setUp(self):
        self.anchor = build_anchor(load_profile("panty-cotton-lace")[0])

    def test_normalize_validate_and_distance(self):
        a = normalize(_world("抽屉排班"), self.anchor, 1)
        b_raw = _world("办公室久坐测试", "on_body")
        b_raw.update({
            "premise": "连续开会八小时，椅子摩擦让旧内裤卷边，起身时总要先拽一下。",
            "tension": "久坐闷热，起身尴尬。",
            "device": "办公室椅子 + 计时器 + 起身动作",
            "turn": "换成纯棉底裆后，八小时结束仍然平整。",
            "payoff": "会议结束直接起身，不用整理衣服。",
            "scene": "办公室工位",
            "props": ["办公椅", "计时器"],
            "visual_motifs": ["计时器数字", "起身"],
        })
        b = normalize(b_raw, self.anchor, 2)
        self.assertEqual(validate(a, self.anchor), [])
        self.assertGreater(world_distance(a, b), 0.2)
        accepted, rejected = critique([_world("抽屉排班"), _world("抽屉排班")],
                                      self.anchor)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)

    def test_semantic_distance_and_audit(self):
        a = normalize(_world("抽屉排班"), self.anchor, 1)
        b = normalize(_world("抽屉排班二"), self.anchor, 2)
        a["semantic"]["core_device"] = "抽屉盲选"
        b["semantic"]["core_device"] = "抽屉盲选"
        self.assertLess(semantic_distance(a, b), 0.5)
        audit = semantic_audit([a, b])
        self.assertFalse(audit["ok"])
        self.assertEqual(audit["duplicate_core_devices"], ["抽屉盲选"])

        c = normalize(_world("办公室久坐测试", "on_body"), self.anchor, 3)
        c["semantic"]["core_device"] = "久坐起身测试"
        self.assertGreater(semantic_distance(a, c), semantic_distance(a, b))
        self.assertGreaterEqual(semantic_audit([a, c])["min_distance"], 0)

        def contract(world, action):
            return {
                "target": {"format": {"presentation": {
                    "person_visibility": "hands_only",
                    "presenter_mode": "text_only"}}},
                "structure": {
                    "creative_world": world,
                    "beats": [{"action": action, "information": {
                        "claim_id": "feature_01"}}],
                },
            }
        ca = contract(a, "手指翻开包边再松手")
        cb = contract(b, "手指翻开包边再松手")
        cc = contract(c, "坐在椅子上起身摸腰线")
        self.assertFalse(contract_semantic_audit([ca, cb])["ok"])
        self.assertTrue(contract_semantic_audit([ca, cc])["ok"])

    def test_select_and_pair_style(self):
        worlds = [normalize(_world(f"世界{i}"), self.anchor, i) for i in range(1, 5)]
        picked = select_worlds(worlds, 2)
        self.assertEqual(len(picked), 2)
        styles = [
            {"id": "s1", "visual": {"person_visibility": "hands_only",
                                    "presenter_mode": "voiceover"},
             "visual_signature": {"person_visibility": "hands_only",
                                  "presenter_mode": "voiceover"}},
            {"id": "s2", "visual": {"person_visibility": "none",
                                    "presenter_mode": "ambient"},
             "visual_signature": {"person_visibility": "none",
                                  "presenter_mode": "ambient"}},
        ]
        pairs = pair_styles([_world("手部世界", "hands"),
                             _world("上身世界", "on_body")], styles)
        by_world = {w["title"]: s for w, s in pairs}
        self.assertEqual(by_world["手部世界"]["visual"]["person_visibility"],
                         "hands_only")
        self.assertIn(by_world["上身世界"]["visual"]["person_visibility"],
                      ("full", "partial"))


if __name__ == "__main__":
    unittest.main()
