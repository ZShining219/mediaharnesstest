"""Harness 运行时依赖；p0_runner 只依赖这些端口。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ports import (ComposerDeps, ContractCodec, FacetRepository,
                    LLMProvider, MaterialProvider, ProfileProvider,
                    ProgressSink, VideoBackend)


@dataclass
class HarnessContext:
    root: Path
    profiles: ProfileProvider
    facets: FacetRepository
    materials: MaterialProvider
    llm: LLMProvider
    codec: ContractCodec
    video: VideoBackend
    progress: ProgressSink | None = None
    facet_dir: Path | None = None

    @property
    def composer_deps(self) -> ComposerDeps:
        return ComposerDeps(llm=self.llm, facets=self.facets,
                            codec=self.codec)
