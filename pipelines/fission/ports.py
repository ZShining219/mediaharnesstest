"""可移植裂变 harness 的端口（只放协议/依赖容器，不 import 项目实现）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class LLMProvider(Protocol):
    def chat(self, user: str, system: str | None = None,
             max_tokens: int = 2000, temperature: float = 0.7,
             json_mode: bool = False) -> str:
        ...


class FacetRepository(Protocol):
    def catalog(self) -> dict[str, Any]:
        ...

    def get(self, ref_id: str) -> dict:
        ...


class ContractCodec(Protocol):
    def validate(self, contract: dict, facet: dict) -> dict:
        ...

    def render_prompt(self, contract: dict) -> str:
        ...

    def render_audit(self, contract: dict, facet: dict) -> str:
        ...

    def text_to_srt(self, text: str, duration: float, path: Path) -> Path:
        ...


class MaterialProvider(Protocol):
    def prepare(self, refresh: bool = False, progress=None) -> dict:
        ...


class ProfileProvider(Protocol):
    def load(self, profile_ref: str | Path) -> tuple[dict, Path]:
        ...


class VideoBackend(Protocol):
    def generate(self, contract: Path, prompt: Path, out_dir: Path,
                 name: str, force: bool = False) -> dict[str, Any]:
        ...


class ProgressSink(Protocol):
    def __call__(self, phase: str, extra: dict[str, Any] | None = None) -> None:
        ...


@dataclass
class ComposerDeps:
    llm: LLMProvider
    facets: FacetRepository
    codec: ContractCodec
