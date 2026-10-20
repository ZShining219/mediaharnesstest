"""素材解读：增量准备 reference descriptions / facets / alignments。

P0.2 job 的 materials 阶段只补齐缺失的素材，不会在每次跑图时重新调用视觉模型。
`refresh=True` 才会强制重读全部参考视频。

这个模块刻意不 import 任何 LLM 客户端；实际脚本通过子进程执行，
这样 job 编排层和素材解读实现保持解耦。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL_PATH = ROOT / "data" / "reference_pool.json"
CASES_DIR = ROOT / "data" / "reference_cases"
FACETS_DIR = ROOT / "data" / "reference_facets"
ALIGN_DIR = ROOT / "data" / "reference_alignments"


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _ref_ids(pool_path: Path) -> list[str]:
    try:
        rows = json.loads(pool_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"读取参考池失败: {pool_path}: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError(f"参考池格式错误（应为数组）: {pool_path}")
    return [str(x.get("id")) for x in rows
            if isinstance(x, dict) and x.get("id")]


def _alignment_method(facet: dict) -> str:
    return str((((facet.get("structure") or {})
                 .get("beat_shot_alignment") or {}).get("method") or "none"))


def inventory(pool_path: Path | None = None,
              cases_dir: Path | None = None,
              facets_dir: Path | None = None,
              align_dir: Path | None = None) -> dict:
    """只读盘点；不触发任何模型调用。"""
    pool_path = pool_path or POOL_PATH
    cases_dir = cases_dir or CASES_DIR
    facets_dir = facets_dir or FACETS_DIR
    align_dir = align_dir or ALIGN_DIR
    ids = _ref_ids(pool_path)
    descriptions = [x for x in ids
                    if (cases_dir / x / "descriptions.json").is_file()]
    facets = [x for x in ids if (facets_dir / f"{x}.json").is_file()]
    aligned = 0
    unaligned = []
    unverified = []
    for rid in facets:
        facet = _load_json(facets_dir / f"{rid}.json")
        method = _alignment_method(facet)
        if method != "none":
            aligned += 1
        else:
            unaligned.append(rid)
        if method == "index_by_count":
            unverified.append(rid)
    align_files = [x for x in ids if (align_dir / f"{x}.json").is_file()]
    missing_descriptions = [x for x in ids if x not in descriptions]
    missing_facets = [x for x in ids if x not in facets]
    return {
        "refs": len(ids),
        "descriptions": len(descriptions),
        "facets": len(facets),
        "aligned": aligned,
        "align_files": len(align_files),
        "missing_descriptions": missing_descriptions,
        "missing_facets": missing_facets,
        "unaligned": unaligned,
        "unverified": unverified,
    }


def _run_script(script: str, *args: str, timeout: int = 3600) -> str:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), text=True, capture_output=True,
            timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{script} 超时（>{timeout}s）") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1200:]
        raise RuntimeError(
            f"{script} 失败（exit={proc.returncode}）: {tail.strip()}")
    return proc.stdout or ""


def prepare_materials(refresh: bool = False,
                      progress=None,
                      pool_path: Path | None = None,
                      cases_dir: Path | None = None,
                      facets_dir: Path | None = None,
                      align_dir: Path | None = None) -> dict:
    """增量补齐描述、facet 和 beat↔镜头对齐。

    常规 run：只有描述/facet 缺失时才调用对应脚本；已有 29 条素材时基本是
    一次确定性的 facets 重建。`refresh=True` 会强制重新描述并对齐。
    """
    def emit(phase: str, **extra):
        if progress:
            try:
                progress(phase, extra)
            except Exception:
                pass

    before = inventory(pool_path, cases_dir, facets_dir, align_dir)
    if not before["refs"]:
        raise RuntimeError("参考池为空，无法准备素材")

    described = 0
    if refresh or before["missing_descriptions"]:
        emit("materials.describe", refs=before["refs"],
             missing=len(before["missing_descriptions"]))
        args = ["--force"] if refresh else []
        _run_script("reference_describe.py", *args)
        described = (before["refs"] if refresh
                     else len(before["missing_descriptions"]))

    emit("materials.facets", refs=before["refs"])
    _run_script("reference_facets.py")

    after_facets = inventory(pool_path, cases_dir, facets_dir, align_dir)
    # `index_by_count` 是可用的暂对齐，不应在每次 job 都重新调用 LLM。
    # 新描述/新 facet 或真正的 method=none 才单独做语义对齐。
    new_ids = sorted(set(before["missing_descriptions"])
                     | set(before["missing_facets"]))
    align_ids = sorted(set(after_facets["unaligned"]) | set(new_ids))
    need_align = bool(refresh or align_ids)
    if need_align:
        emit("materials.align", ids=len(align_ids),
             unaligned=len(after_facets["unaligned"]), refresh=refresh)
        if refresh:
            _run_script("reference_align.py", "--force")
        elif align_ids:
            _run_script("reference_align.py", "--refs", ",".join(align_ids))

    after = inventory(pool_path, cases_dir, facets_dir, align_dir)
    if after["missing_descriptions"] or after["missing_facets"]:
        raise RuntimeError(
            "素材仍不完整: descriptions 缺 "
            f"{len(after['missing_descriptions'])}, facets 缺 "
            f"{len(after['missing_facets'])}")
    return {
        "refs": after["refs"],
        "descriptions": after["descriptions"],
        "facets": after["facets"],
        "aligned": after["aligned"],
        "align_files": after["align_files"],
        "unverified": len(after["unverified"]),
        "missing_before": len(before["missing_descriptions"]),
        "missing_facets_before": len(before["missing_facets"]),
        "described": described,
        "refreshed": bool(refresh),
    }
