"""商品 Profile 加载与校验。"""
from __future__ import annotations

from pathlib import Path

from .io import load_json

ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / "configs" / "products"

REQUIRED = (
    "product_id", "image", "category", "identity",
    "must_show", "must_not_change", "claims", "person",
)


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p


def load_profile(profile: str | Path) -> tuple[dict, Path]:
    """profile 可以是 id（bra-milk-lace）或 JSON 路径。"""
    p = Path(profile)
    if not p.suffix:
        p = PROFILE_DIR / f"{p.name}.json"
    elif not p.is_absolute():
        p = ROOT / p
    data = load_json(p)
    errors = [f"缺少 {k}" for k in REQUIRED if not data.get(k)]
    person = data.get("person") or {}
    if not person.get("image"):
        errors.append("person.image 缺失")
    for key in ("image", "back_image", "inner_image"):
        if data.get(key) and not _resolve(data[key]).exists():
            errors.append(f"{key} 不存在: {data[key]}")
    for key in ("image", "side_image"):
        if person.get(key) and not _resolve(person[key]).exists():
            errors.append(f"person.{key} 不存在: {person[key]}")
    if errors:
        raise ValueError("；".join(errors))
    data.setdefault("default_archetype", "ugc_individual_seller")
    data.setdefault("color_policy", "single")
    return data, p
