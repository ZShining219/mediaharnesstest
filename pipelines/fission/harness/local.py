"""当前项目内的本地适配器；移植到其他项目时只替换这一层。"""
from __future__ import annotations

from pathlib import Path

from ..context import HarnessContext
from ..ports import ComposerDeps


class LocalLLM:
    def __init__(self, timeout: float = 300):
        self.timeout = timeout

    def chat(self, user: str, system: str | None = None,
             max_tokens: int = 2000, temperature: float = 0.7,
             json_mode: bool = False) -> str:
        from orchestrator.app import reference_analysis as ra
        return ra._ref_llm(timeout=self.timeout).chat(
            user, system=system, max_tokens=max_tokens,
            temperature=temperature, json_mode=json_mode)


class LocalFacets:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(__file__).resolve().parents[3] / \
            "data" / "reference_facets"

    def catalog(self) -> dict[str, Path]:
        return {p.stem: p for p in self.directory.glob("ref-*.json")}

    def get(self, ref_id: str) -> dict:
        from orchestrator.app import reference_contract as rc
        return rc.load_facet(ref_id, self.directory)


class LocalCodec:
    def validate(self, contract: dict, facet: dict) -> dict:
        from orchestrator.app import reference_contract as rc
        return rc.validate_contract(contract, facet)

    def render_prompt(self, contract: dict) -> str:
        from orchestrator.app import reference_contract as rc
        return rc.render_h3_prompt(contract)

    def render_audit(self, contract: dict, facet: dict) -> str:
        from orchestrator.app import reference_contract as rc
        return rc.render_audit(contract, facet)

    def text_to_srt(self, text: str, duration: float, path: Path) -> Path:
        from orchestrator.app import media
        return media.text_to_srt(text, duration, path)


class LocalMaterials:
    def prepare(self, refresh: bool = False, progress=None) -> dict:
        from .. import materials
        return materials.prepare_materials(refresh=refresh, progress=progress)


class LocalProfiles:
    def load(self, profile_ref: str | Path):
        from .. import profiles
        return profiles.load_profile(profile_ref)


class RunContractBackend:
    """通过 scripts/run_contract.py 提交 H3 的本地 backend。"""

    def generate(self, contract: Path, prompt: Path, out_dir: Path,
                 name: str, force: bool = False) -> dict:
        from .. import p0_runner
        return p0_runner.run_contract_backend(
            contract, prompt, out_dir, name, force=force)


def default_context(progress=None, video_backend=None,
                    facet_dir: Path | None = None) -> HarnessContext:
    root = Path(__file__).resolve().parents[3]
    facets = LocalFacets(facet_dir or root / "data" / "reference_facets")
    return HarnessContext(
        root=root,
        profiles=LocalProfiles(),
        facets=facets,
        materials=LocalMaterials(),
        llm=LocalLLM(),
        codec=LocalCodec(),
        video=video_backend or RunContractBackend(),
        progress=progress,
        facet_dir=facets.directory,
    )


def default_composer_deps() -> ComposerDeps:
    ctx = default_context()
    return ctx.composer_deps
