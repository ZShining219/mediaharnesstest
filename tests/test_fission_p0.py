"""P0 结构测试：anchor / style atlas / planner / audit（不调 LLM/H3）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.anchor import build_anchor, validate_anchor  # noqa: E402
from pipelines.fission.audit import audit_contracts  # noqa: E402
from pipelines.fission.planner import plan_styles  # noqa: E402
from pipelines.fission.profiles import load_profile  # noqa: E402
from pipelines.fission.style_atlas import build_style_atlas  # noqa: E402


class TestAnchor(unittest.TestCase):
    def test_anchor_has_view_refs_and_atoms(self):
        profile, _ = load_profile("bra-milk-lace")
        anchor = build_anchor(profile)
        self.assertEqual(validate_anchor(anchor), [])
        self.assertEqual({r["view"] for r in anchor["references"]},
                         {"front", "back", "inner"})
        self.assertGreaterEqual(len(anchor["claim_atoms"]), 6)
        self.assertTrue(any(a["safe_for_no_person"]
                            for a in anchor["claim_atoms"]))

    def test_panty_profile_allows_on_body(self):
        profile, _ = load_profile("panty-cotton-lace")
        anchor = build_anchor(profile)
        self.assertEqual(validate_anchor(anchor), [])
        self.assertIn("full", anchor["allowed_person_visibility"])
        self.assertIn("partial", anchor["allowed_person_visibility"])
        self.assertFalse(anchor.get("wear_state"))


class TestStyleSpace(unittest.TestCase):
    def test_atlas_and_planner(self):
        profile, _ = load_profile("bra-milk-lace")
        anchor = build_anchor(profile)
        atlas = build_style_atlas()
        self.assertEqual(atlas["count"], 29)
        plan = plan_styles(atlas, 5, anchor, seed=42)
        self.assertEqual(len(plan["styles"]), 5)
        # 5 条风格不能是同一套
        self.assertGreaterEqual(len({
            s["visual"]["person_visibility"] for s in plan["styles"]}), 2)
        self.assertGreaterEqual(len({
            s["visual"]["presenter_mode"] for s in plan["styles"]}), 2)
        self.assertGreaterEqual(len({
            s["copy"]["tone"] for s in plan["styles"]}), 2)
        self.assertTrue(plan["distances"])
        self.assertGreater(max(x["visual"] for x in plan["distances"]), 0.5)


class TestAudit(unittest.TestCase):
    def _contract(self, cid: str, claim: str, cta: str) -> dict:
        return {
            "provenance": {"style_id": "s1"},
            "target": {
                "references": [{"kind": "product", "index": 1, "path": "x"}],
                "product": {"must_show": ["正面"]},
            },
            "structure": {"beats": [{
                "index": 1, "product_evidence": ["正面"],
                "information": {
                    "claim_id": cid, "claim": claim, "proof": "p",
                    "text_overlay": claim, "voiceover": claim,
                    "offer_cta": cta,
                },
            }]},
        }

    def test_anchor_error_and_copy_duplicate(self):
        anchor = build_anchor(load_profile("bra-milk-lace")[0])
        c1 = self._contract(anchor["claim_atoms"][0]["id"],
                            "这是同一句重复文案", "点下方看活动价")
        c2 = self._contract(anchor["claim_atoms"][1]["id"],
                            "这是同一句重复文案", "点下方看活动价")
        audit = audit_contracts([c1, c2], anchor, [], [])
        self.assertFalse(audit["ok"])
        self.assertGreater(audit["copy"]["cross_variant"]["duplicates"], 0)

    def test_single_world_audit_ok(self):
        anchor = build_anchor(load_profile("bra-milk-lace")[0])
        c = self._contract(anchor["claim_atoms"][0]["id"],
                           "一条独立文案", "点下方看活动价")
        c["structure"]["creative_world"] = {
            "id": "w1", "title": "w1", "premise": "p",
            "device": "d", "turn": "t", "payoff": "pay",
        }
        audit = audit_contracts([c], anchor, [], [])
        self.assertTrue(audit["concept"]["ok"])
        self.assertEqual(audit["concept"]["min_distance"], 1.0)


if __name__ == "__main__":
    unittest.main()
