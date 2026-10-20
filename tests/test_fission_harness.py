"""Harness facade 测试：不调用 LLM/H3。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.fission.harness import FissionHarness, HarnessRequest  # noqa: E402
from pipelines.fission.harness import service as harness_service  # noqa: E402
from pipelines.fission.harness.local import RunContractBackend  # noqa: E402


class FakeBackend:
    def __init__(self):
        self.calls = []

    def generate(self, contract, prompt, out_dir, name, force=False):
        self.calls.append((contract, prompt, out_dir, name, force))
        return {"provider_task": "fake"}


class TestHarness(unittest.TestCase):
    def test_request_defaults(self):
        req = HarnessRequest()
        self.assertEqual(req.profile_id, "panty-cotton-lace")
        self.assertEqual(req.n, 5)
        self.assertTrue(req.prepare_materials)
        self.assertFalse(req.generate)

    def test_run_maps_result_and_passes_backend(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            fake = {
                "run_dir": str(run_dir),
                "audit": {"ok": True},
                "inputs": {"seed": 42},
                "contracts": [str(run_dir / "v01/contract.json")],
                "videos": [str(run_dir / "v01/variant_01.mp4")],
                "manifest": {"run_id": "run", "status": "done"},
            }
            backend = FakeBackend()
            with patch.object(harness_service.p0_runner, "run_p0",
                              return_value=fake) as run:
                res = FissionHarness(video_backend=backend).run(
                    HarnessRequest(profile_id="panty-cotton-lace", n=2,
                                   seed=42, generate=True))
            self.assertEqual(res.run_id, "run")
            self.assertEqual(res.status, "done")
            self.assertEqual(res.audit["ok"], True)
            self.assertEqual(res.videos, [run_dir / "v01/variant_01.mp4"])
            kwargs = run.call_args.kwargs
            self.assertEqual(kwargs["generate_fn"], backend.generate)
            self.assertTrue(kwargs["generate"])
            self.assertIs(kwargs["context"].video, backend)

    def test_resume_maps_result(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            (run_dir / "v01").mkdir(parents=True)
            (run_dir / "v01/contract.json").write_text("{}", encoding="utf-8")
            fake = {
                "run_dir": str(run_dir),
                "manifest": {"run_id": "run", "status": "done"},
                "videos": [str(run_dir / "v01/variant_01.mp4")],
            }
            backend = FakeBackend()
            with patch.object(harness_service.p0_runner,
                              "resume_p0_generation",
                              return_value=fake) as resume:
                res = FissionHarness(video_backend=backend).resume(run_dir)
            self.assertEqual(res.status, "done")
            self.assertEqual(len(res.contracts), 1)
            self.assertEqual(resume.call_args.kwargs["generate_fn"],
                             backend.generate)
            self.assertIs(resume.call_args.kwargs["context"].video,
                          backend)

    def test_local_backend_delegates(self):
        with tempfile.TemporaryDirectory() as td:
            args = (Path(td) / "c.json", Path(td) / "p.txt",
                    Path(td), "variant_01.mp4")
            with patch("pipelines.fission.p0_runner.run_contract_backend", return_value={"ok": True}) as fn:
                out = RunContractBackend().generate(*args, force=True)
            self.assertEqual(out, {"ok": True})
            fn.assert_called_once_with(*args, force=True)


if __name__ == "__main__":
    unittest.main()
