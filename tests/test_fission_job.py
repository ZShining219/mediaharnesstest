"""P0.2 job 编排测试：不调用 LLM/H3。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from starlette.background import BackgroundTasks

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission import materials  # noqa: E402
from pipelines.fission import p0_runner  # noqa: E402
from pipelines.fission.io import load_json, save_json  # noqa: E402
from orchestrator.app import main as api_main  # noqa: E402


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _fake_contract(i: int) -> dict:
    return {
        "target": {"format": {
            "duration": 12, "aspect_ratio": "9:16", "resolution": "768P",
            "presentation": {
                "name": f"style{i}", "person_visibility": "hands_only",
                "presenter_mode": "text_only", "camera_family": "tabletop",
                "scene_family": "tabletop",
            },
        }},
        "structure": {
            "name": f"variant{i}", "concept": "test",
            "copy_profile": {"tone": "test"},
            "creative_world": {"title": f"world{i}"},
            "style_id": f"s{i}",
            "beats": [{
                "index": 1, "time": [0, 12], "function_label": "demo",
                "shot_size": "特写", "angle": "俯拍", "camera": "固定",
                "lighting": "柔光", "composition": "", "action": "",
                "information": {}, "product_evidence": ["x"],
                "on_screen_text": "", "transition": "硬切",
            }],
        },
        "_validation": {"ok": True},
    }


class TestMaterialsInventory(unittest.TestCase):
    def test_inventory_missing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pool = tmp / "pool.json"
            pool.write_text(json.dumps([
                {"id": "ref-a", "path": "a.mp4"},
                {"id": "ref-b", "path": "b.mp4"},
            ]), encoding="utf-8")
            _write(tmp / "cases" / "ref-a" / "descriptions.json", {})
            _write(tmp / "facets" / "ref-a.json", {
                "ref_id": "ref-a",
                "structure": {"beat_shot_alignment": {
                    "method": "llm_monotonic"}},
            })
            inv = materials.inventory(
                pool_path=pool, cases_dir=tmp / "cases",
                facets_dir=tmp / "facets", align_dir=tmp / "align")
            self.assertEqual(inv["refs"], 2)
            self.assertEqual(inv["descriptions"], 1)
            self.assertEqual(inv["facets"], 1)
            self.assertEqual(inv["aligned"], 1)
            self.assertEqual(inv["missing_descriptions"], ["ref-b"])
            self.assertEqual(inv["missing_facets"], ["ref-b"])


class TestGeneration(unittest.TestCase):
    def _fixture(self, tmp: Path, n: int = 1) -> tuple[Path, dict]:
        out = tmp / "run"
        manifest = {
            "engine": "p0.2", "run_id": out.name,
            "status": "contracts_done",
            "stages": {"generation": {"status": "pending", "variants": {}}},
            "errors": [],
        }
        for i in range(1, n + 1):
            d = out / f"v{i:02d}"
            d.mkdir(parents=True, exist_ok=True)
            _write(d / "contract.json", _fake_contract(i))
            (d / "prompt_h3.txt").write_text("prompt", encoding="utf-8")
        save_json(out / "run.json", manifest)
        return out, manifest

    def test_generate_partial(self):
        with tempfile.TemporaryDirectory() as td:
            out, manifest = self._fixture(Path(td), 2)

            def fake(contract, prompt, out_dir, name, force=False):
                if name.endswith("02.mp4"):
                    raise RuntimeError("provider failed")
                (out_dir / name).write_bytes(b"fake-mp4")
                _write(out_dir / "run.json", {
                    "status": "generated", "provider_task": "task-1",
                    "review_path": "outputs/review/fake.mp4", "job": "job-1",
                })
                return load_json(out_dir / "run.json")

            res = p0_runner._generate_variants(out, manifest,
                                               generate_fn=fake)
            self.assertEqual(manifest["status"], "partial")
            self.assertEqual(res["generation"]["status"], "partial")
            self.assertEqual(manifest["stages"]["generation"]
                             ["variants"]["v01"]["status"], "done")
            self.assertEqual(manifest["stages"]["generation"]
                             ["variants"]["v02"]["status"], "failed")
            self.assertEqual(len(res["videos"]), 1)
            self.assertTrue(any("provider failed" in x
                                for x in manifest["errors"]))

    def test_resume_generation(self):
        with tempfile.TemporaryDirectory() as td:
            out, _manifest = self._fixture(Path(td), 1)

            def fake(contract, prompt, out_dir, name, force=False):
                (out_dir / name).write_bytes(b"fake-mp4")
                _write(out_dir / "run.json", {
                    "status": "generated", "provider_task": "resume-task",
                    "review_path": "outputs/review/resume.mp4",
                })
                return load_json(out_dir / "run.json")

            res = p0_runner.resume_p0_generation(out, generate_fn=fake)
            self.assertEqual(res["manifest"]["status"], "done")
            self.assertEqual(len(res["videos"]), 1)
            self.assertTrue((out / "run.json").exists())

    def test_skip_existing_generated_video(self):
        with tempfile.TemporaryDirectory() as td:
            out, manifest = self._fixture(Path(td), 1)
            vdir = out / "v01"
            (vdir / "variant_01.mp4").write_bytes(b"fake-mp4")
            _write(vdir / "run.json", {
                "status": "generated", "provider_task": "old",
                "review_path": "old.mp4",
            })
            called = []

            def fake(*args, **kwargs):
                called.append(args)
                raise AssertionError("should skip")

            res = p0_runner._generate_variants(out, manifest,
                                               generate_fn=fake)
            self.assertFalse(called)
            self.assertEqual(manifest["status"], "done")
            self.assertEqual(len(res["videos"]), 1)
            self.assertTrue(res["videos"][0].endswith("variant_01.mp4"))
            self.assertEqual(manifest["stages"]["generation"]
                             ["variants"]["v01"]["skipped"], True)


class TestRunP0Manifest(unittest.TestCase):
    def test_contract_only_manifest_with_materials(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "p0-test"
            styles = [{"id": "s1", "name": "s1"},
                      {"id": "s2", "name": "s2"}]
            worlds = [{"id": "w1", "title": "w1"},
                      {"id": "w2", "title": "w2"}]

            def fake_compose(anchor, brief, plan, catalog, out_root,
                             deps=None):
                contracts = []
                for i, _style in enumerate(plan["styles"], 1):
                    c = _fake_contract(i)
                    d = out_root / f"v{i:02d}"
                    d.mkdir(parents=True, exist_ok=True)
                    save_json(d / "contract.json", c)
                    (d / "prompt_h3.txt").write_text(
                        "【主体定义】\n【全局合同】\n【商品硬约束】\n"
                        "【逻辑分镜时间轴】\n【负面约束】\n",
                        encoding="utf-8")
                    contracts.append(c)
                return contracts

            audit = {
                "ok": True,
                "anchor": {"errors": []},
                "copy": {"cross_variant": {"duplicates": 0}},
                "style": {"min_visual_distance": 1.0,
                          "min_copy_distance": 1.0,
                          "coverage": {}, "perceptual_ok": True},
                "concept": {"ok": True, "count": 2},
            }
            plan = {"seed": 42, "styles": styles, "distances": []}
            with ExitStack() as stack:
                stack.enter_context(patch(
                    "pipelines.fission.harness.local.LocalMaterials.prepare",
                    return_value={"refs": 29, "descriptions": 29,
                                  "facets": 29, "aligned": 29}))
                stack.enter_context(patch.object(
                    p0_runner.style_atlas, "build_style_atlas",
                    return_value={"count": 29, "items": []}))
                stack.enter_context(patch.object(
                    p0_runner, "plan_styles", return_value=plan))
                stack.enter_context(patch.object(
                    p0_runner.proposer, "propose_worlds", return_value=[]))
                stack.enter_context(patch.object(
                    p0_runner.critic, "critique", return_value=(worlds, [])))
                stack.enter_context(patch.object(
                    p0_runner.selector, "select_worlds",
                    return_value=worlds))
                stack.enter_context(patch.object(
                    p0_runner.selector, "pair_styles",
                    return_value=list(zip(worlds, styles))))
                stack.enter_context(patch.object(
                    p0_runner.composer, "compose_batch",
                    side_effect=fake_compose))
                stack.enter_context(patch.object(
                    p0_runner.composer, "diversify_copy",
                    side_effect=lambda c, *a, **k: c))
                stack.enter_context(patch.object(
                    p0_runner, "audit_contracts", return_value=audit))
                res = p0_runner.run_p0(
                    "bra-milk-lace", n=2, seed=42, out_root=str(out),
                    prepare_materials=True, generate=False)

            manifest = res["manifest"]
            self.assertEqual(manifest["engine"], "p0.2")
            self.assertEqual(manifest["status"], "contracts_done")
            self.assertTrue((out / "run.json").exists())
            self.assertTrue((out / "v01" / "contract.json").exists())
            self.assertIn("inputs", manifest)
            self.assertEqual(manifest["stages"]["materials"]["status"], "done")
            self.assertEqual(manifest["stages"]["generation"]["status"],
                             "skipped")
            self.assertEqual(manifest["stages"]["contracts"]["count"], 2)


class TestP0JobApi(unittest.TestCase):
    def test_job_returns_contracts_only_result(self):
        fake_manifest = {
            "engine": "p0.2", "status": "contracts_done",
            "stages": {"generation": {"status": "skipped"}},
        }
        fake_result = {
            "manifest": fake_manifest,
            "videos": [],
            "contracts": ["v01/contract.json"],
        }
        calls = {}

        def finish(jid, status, result):
            calls.update(jid=jid, status=status, result=result)

        with patch.object(api_main.store, "job_create",
                          return_value="fission_p0-test"), \
             patch.object(api_main.store, "job_update"), \
             patch.object(api_main.store, "job_finish",
                          side_effect=finish), \
             patch.object(p0_runner, "run_p0", return_value=fake_result):
            bg = BackgroundTasks()
            out = api_main.job_fission_p0(
                api_main.FissionP0Req(
                    profile_id="panty-cotton-lace", n=2,
                    skip_generate=True), bg)
            for task in bg.tasks:
                task.func()

        self.assertEqual(out["job"], "fission_p0-test")
        self.assertTrue(out["run_id"].startswith("p0-panty-cotton-lace-"))
        self.assertEqual(calls["status"], "done")
        self.assertEqual(calls["result"]["phase"], "contracts_only")
        self.assertEqual(calls["result"]["engine"], "p0.2")

    def test_p0_engine_helper(self):
        self.assertTrue(api_main._is_p0_engine("p0"))
        self.assertTrue(api_main._is_p0_engine("p0.2"))
        self.assertFalse(api_main._is_p0_engine("legacy"))


if __name__ == "__main__":
    unittest.main()
