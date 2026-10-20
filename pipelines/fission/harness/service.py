"""Fission harness facade：稳定输入/输出，不暴露 FastAPI 或 store。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .local import default_context
from .models import HarnessRequest, HarnessResult
from .. import p0_runner


class FissionHarness:
    """P0.2 链路的可移植入口。

    默认使用本地 project adapters；其他项目可以传入自己的 HarnessContext，
    替换 LLM、素材、facet、视频 backend 和审核实现。
    """

    def __init__(self, context=None, video_backend=None, progress=None):
        self.context = context or default_context(progress=progress)
        if video_backend is not None:
            self.context = replace(self.context, video=video_backend)
        self.progress = progress or self.context.progress

    def run(self, req: HarnessRequest) -> HarnessResult:
        res = p0_runner.run_p0(
            req.profile_id,
            req.text,
            req.n,
            req.out_root,
            req.seed,
            person=req.person,
            product_image=req.product_image,
            prepare_materials=req.prepare_materials,
            refresh_materials=req.refresh_materials,
            generate=req.generate,
            progress=self.progress,
            generate_fn=self.context.video.generate,
            context=self.context,
        )
        return self._result(res)

    def resume(self, run_dir: str | Path) -> HarnessResult:
        res = p0_runner.resume_p0_generation(
            run_dir, progress=self.progress,
            generate_fn=self.context.video.generate,
            context=self.context)
        out = Path(res["run_dir"])
        return self._result(res, contracts=sorted(
            out.glob("v[0-9][0-9]/contract.json")))

    @staticmethod
    def _result(res: dict, contracts: list[Path] | None = None) -> HarnessResult:
        manifest = res.get("manifest") or {}
        run_dir = Path(res["run_dir"])
        if contracts is None:
            contracts = [Path(x) for x in (res.get("contracts") or [])]
        return HarnessResult(
            run_id=str(manifest.get("run_id") or run_dir.name),
            run_dir=run_dir,
            status=str(manifest.get("status") or ""),
            manifest=manifest,
            contracts=contracts,
            videos=[Path(x) for x in (res.get("videos") or [])],
            audit=res.get("audit") or {},
            inputs=res.get("inputs") or manifest.get("inputs") or {},
        )
