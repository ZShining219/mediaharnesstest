"""重构后的最小回归测试（不调用 LLM / H3）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.app import reference_contract as rc  # noqa: E402
from pipelines.fission.adapters import choose_primary_ref, get_adapter  # noqa: E402
from pipelines.fission.io import envelope, validate_envelope  # noqa: E402
from pipelines.fission.pool import anchor_catalog, build_digest  # noqa: E402
from pipelines.fission.profiles import load_profile  # noqa: E402
from pipelines.fission.variants import select_lanes  # noqa: E402


class TestProfile(unittest.TestCase):
    def test_load_bra_profile(self):
        profile, path = load_profile("bra-milk-lace")
        self.assertTrue(path.exists())
        self.assertEqual(profile["product_id"], "bra-milk-lace")
        self.assertIn("must_show", profile)
        self.assertIn("person", profile)
        self.assertTrue((ROOT / profile["image"]).exists())
        self.assertTrue((ROOT / profile["person"]["image"]).exists())


class TestEnvelope(unittest.TestCase):
    def test_valid(self):
        env = envelope("brief", "v0", "brief-1", "test", {"x": 1})
        self.assertEqual(validate_envelope(env, "brief"), [])

    def test_invalid(self):
        self.assertTrue(validate_envelope({"type": "brief"}))
        self.assertTrue(validate_envelope(
            envelope("brief", "v0", "b", "t", {}), "guidance"))


class TestPool(unittest.TestCase):
    def test_digest_and_anchors(self):
        d = build_digest()
        refs = d["payload"]["refs"]
        self.assertEqual(len(refs), 29)
        cat = anchor_catalog(d)
        self.assertIn("ref-1792419234-bd6f", cat)
        self.assertTrue(cat["ref-1792419234-bd6f"]["beats"])
        self.assertTrue(cat["ref-1792419234-bd6f"]["shots"])


class TestAdapter(unittest.TestCase):
    def _variant(self):
        return {
            "id": "t1",
            "hypothesis": "测试变体",
            "rationale": "测试",
            "primary_ref": "ref-1792419234-bd6f",
            "evidence_refs": [],
            "beats": [
                {"index": 1, "time": [0, 4], "shot_size": "medium",
                 "angle": "平视", "camera": "手持中景",
                 "lighting": "自然窗光", "composition": "真人半身",
                 "action": "真人手持商品",
                 "product_evidence": ["正面罩杯"],
                 "information": {"claim": "卖点一", "proof": "证明一",
                                 "text_overlay": "字幕一", "voiceover": "口播一",
                                 "persona": "真人女主播", "context": "居家客厅",
                                 "offer_cta": ""}},
                {"index": 2, "time": [4, 8], "shot_size": "close_up",
                 "angle": "俯视", "camera": "手持近景",
                 "lighting": "自然窗光", "composition": "桌面近景",
                 "action": "手指按压商品",
                 "product_evidence": ["背面四排扣"],
                 "information": {"claim": "卖点二", "proof": "证明二",
                                 "text_overlay": "字幕二", "voiceover": "口播二",
                                 "persona": "真人女主播", "context": "桌面近景",
                                 "offer_cta": ""}},
                {"index": 3, "time": [8, 12], "shot_size": "medium",
                 "angle": "平视", "camera": "手持中景",
                 "lighting": "自然窗光", "composition": "真人半身",
                 "action": "真人 CTA",
                 "product_evidence": ["正面罩杯"],
                 "information": {"claim": "卖点三", "proof": "证明三",
                                 "text_overlay": "字幕三", "voiceover": "口播三",
                                 "persona": "真人女主播", "context": "衣帽间",
                                 "offer_cta": "点下方看活动价"}},
            ],
        }

    def test_build_contract(self):
        profile, _ = load_profile("bra-milk-lace")
        facet = rc.load_facet("ref-1792419234-bd6f")
        brief = {"payload": {
            "goal": {"duration_seconds": 12,
                     "archetype": "ugc_individual_seller"},
            "constraints": {"color_policy": "single"},
        }}
        adapter = get_adapter("ugc_individual_seller")
        c = adapter.build_contract(self._variant(), brief, profile, facet, 1)
        val = rc.validate_contract(c, facet)
        self.assertTrue(val["ok"], val["errors"])
        self.assertEqual(c["target"]["references"][0]["path"],
                         profile["person"]["image"])
        self.assertEqual(c["target"]["product"]["must_show"],
                         profile["must_show"])
        self.assertEqual(c["target"]["format"]["archetype"],
                         "ugc_individual_seller")
        self.assertEqual(len(c["structure"]["beats"]), 3)

    def test_hands_only_lane_removes_person(self):
        profile, _ = load_profile("bra-milk-lace")
        facet = rc.load_facet("ref-1792419234-bd6f")
        brief = {"payload": {
            "goal": {"duration_seconds": 12,
                     "archetype": "ugc_individual_seller"},
            "constraints": {"color_policy": "single"},
        }}
        v = self._variant()
        v["format_profile"] = {
            "name": "桌面手部 ASMR",
            "summary": "只拍手部操作和商品细节，无口播",
            "person_visibility": "hands_only",
            "presenter_mode": "ambient",
            "camera_language": "固定俯拍微距",
            "scene": "木质桌面，浅色背景",
            "lighting": "自然侧光",
            "proof_style": "按压/翻面/拉扣",
            "narrative_device": "细节检验",
            "audio_design": "布料摩擦与按压声",
            "text_style": "大字关键词",
            "pacing": "ASMR 慢节奏",
        }
        for b in v["beats"]:
            b["information"]["persona"] = ""
            b["information"]["voiceover"] = ""
        adapter = get_adapter("ugc_individual_seller")
        c = adapter.build_contract(v, brief, profile, facet, 2)
        val = rc.validate_contract(c, facet)
        self.assertTrue(val["ok"], val["errors"])
        self.assertNotIn("person", c["target"])
        self.assertEqual(len(c["target"]["references"]), 1)
        self.assertEqual(c["target"]["references"][0]["kind"], "product")
        self.assertFalse(c["target"]["format"]["voiceover"])
        self.assertTrue(c["target"]["format"]["native_audio"])
        self.assertEqual(c["target"]["format"]["presentation"]["person_visibility"],
                         "hands_only")
        self.assertEqual(c["information_budget"]["personas"], 0)
        for b in c["structure"]["beats"]:
            self.assertEqual(b["information"]["voiceover"], "")
            self.assertIn("画面只有", b["information"]["persona"])

    def test_select_lanes_covers_distinct_modes(self):
        guidance = {"payload": {"presentation_lanes": [
            {"name": "真人口播", "person_visibility": "full",
             "presenter_mode": "direct_speech", "camera_language": "手持中景",
             "scene": "客厅"},
            {"name": "真人口播2", "person_visibility": "full",
             "presenter_mode": "direct_speech", "camera_language": "固定中景",
             "scene": "卧室"},
            {"name": "手部 ASMR", "person_visibility": "hands_only",
             "presenter_mode": "ambient", "camera_language": "俯拍微距",
             "scene": "桌面"},
            {"name": "字幕卡", "person_visibility": "none",
             "presenter_mode": "text_only", "camera_language": "固定平视",
             "scene": "桌面"},
        ]}}
        lanes = select_lanes(guidance, 3)
        self.assertEqual(len(lanes), 3)
        self.assertEqual(len({x["name"] for x in lanes}), 3)
        self.assertGreaterEqual(
            len({x["person_visibility"] for x in lanes}), 3)

    def test_choose_primary_ref_fallback(self):
        cat = {"ref-a": {}, "ref-b": {}}
        self.assertEqual(
            choose_primary_ref({"primary_ref": "ref-b", "evidence_refs": []},
                               cat), "ref-b")
        self.assertEqual(
            choose_primary_ref({"primary_ref": "missing", "evidence_refs": []},
                               cat, fallback="ref-a"), "ref-a")


if __name__ == "__main__":
    unittest.main()
