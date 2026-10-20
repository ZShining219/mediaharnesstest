"""Harness 的稳定输入/输出模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HarnessRequest:
    """一次裂变 harness 调用的完整输入。"""

    profile_id: str = "panty-cotton-lace"
    n: int = 5
    seed: int | None = None
    text: str | None = None
    person: str | None = None
    product_image: str | None = None
    prepare_materials: bool = True
    refresh_materials: bool = False
    generate: bool = False
    out_root: str | None = None


@dataclass
class HarnessResult:
    """一次 harness 调用的归一化输出；不把 FastAPI/store 类型暴露给调用方。"""

    run_id: str
    run_dir: Path
    status: str
    manifest: dict[str, Any] = field(default_factory=dict)
    contracts: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def videos_ready(self) -> bool:
        return bool(self.videos)
