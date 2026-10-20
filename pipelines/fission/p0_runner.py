"""P0.2 编排：素材解读 -> anchor -> style -> world -> contract -> audit -> H3。

`run_p0` 默认只生成契约；API job 传 `generate=True` 后逐条调用
`scripts/run_contract.py`，把视频送入审核队列。manifest 从任务开始就落盘，
并按阶段增量更新，供任务中心和 resume 使用。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from . import anchor as anchor_mod
from . import composer
from . import style_atlas
from .context import HarnessContext
from .audit import audit_contracts
from .concept import critic, operators, proposer, selector
from .io import load_json, save_json
from .planner import plan_styles

ROOT = Path(__file__).resolve().parents[2]
STAGES = ("materials", "anchor", "style_atlas", "planner", "worlds",
          "contracts", "audit", "generation")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _save_manifest(out: Path, manifest: dict) -> None:
    manifest["updated_at"] = int(time.time())
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / ".run.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(out / "run.json")


def _stage(manifest: dict, name: str, status: str, **extra) -> dict:
    st = manifest.setdefault("stages", {}).setdefault(name, {})
    st.update({"status": status, **extra})
    return st


def _emit(progress, phase: str, **extra) -> None:
    if not progress:
        return
    try:
        progress(phase, extra)
    except Exception:
        pass


def _fail(out: Path, manifest: dict, stage: str, exc: Exception) -> None:
    msg = f"{stage}: {type(exc).__name__}: {exc}"
    _stage(manifest, stage, "failed", error=msg)
    manifest["status"] = "error"
    manifest.setdefault("errors", []).append(msg)
    try:
        _save_manifest(out, manifest)
    except Exception:
        pass


def _resolve(path: str | Path, root: Path | None = None) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (root or ROOT) / p


def _apply_overrides(profile: dict, product_image: str | None,
                     person: str | None, root: Path | None = None) -> dict:
    root = root or ROOT
    p = dict(profile)
    p["person"] = dict(profile.get("person") or {})
    if product_image:
        path = _resolve(product_image, root)
        if not path.is_file():
            raise ValueError(f"商品图不存在: {product_image}")
        p["image"] = str(path.relative_to(root)) if path.is_relative_to(root) \
            else str(path)
    if person:
        path = _resolve(person, root)
        if not path.is_file():
            raise ValueError(f"人物图不存在: {person}")
        p["person"]["image"] = (str(path.relative_to(root))
                                if path.is_relative_to(root) else str(path))
    return p


def _initial_manifest(out: Path, profile: dict, profile_path: Path,
                      inputs: dict, n: int, seed: int | None,
                      prepare_materials: bool, generate: bool) -> dict:
    stages = {
        "materials": {"status": "pending" if prepare_materials else "skipped"},
        "anchor": {"status": "pending"},
        "style_atlas": {"status": "pending"},
        "planner": {"status": "pending"},
        "worlds": {"status": "pending"},
        "contracts": {"status": "pending"},
        "audit": {"status": "pending"},
        "generation": {
            "status": "pending" if generate else "skipped",
            "output": "v*/variant_*.mp4",
            "variants": {},
        },
    }
    now = int(time.time())
    return {
        "schema_version": "fission-run/v1",
        "engine": "p0.2",
        "run_id": out.name,
        "status": "running",
        "profile_id": profile["product_id"],
        "profile_path": _rel(profile_path),
        "seed": seed,
        "n": n,
        "inputs": inputs,
        "stages": stages,
        "audit": {},
        "videos": 0,
        "errors": [],
        "created_at": now,
        "updated_at": now,
    }


def _variant_generated(vdir: Path, video: Path) -> dict | None:
    if not video.exists() or video.stat().st_size <= 0:
        return None
    run_path = vdir / "run.json"
    if not run_path.exists():
        return None
    try:
        info = load_json(run_path)
    except Exception:
        return None
    if str(info.get("status") or "") != "generated":
        return None
    return info


def run_contract_backend(contract: Path, prompt: Path, out_dir: Path,
                         name: str, force: bool = False) -> dict:
    """公开的本地视频 backend 入口，供 harness/local.py 适配。"""
    return _run_contract_script(contract, prompt, out_dir, name, force=force)


def _run_contract_script(contract: Path, prompt: Path, out_dir: Path,
                         name: str, force: bool = False) -> dict:
    cmd = [
        sys.executable, str(ROOT / "scripts" / "run_contract.py"),
        "--contract", str(contract),
        "--prompt", str(prompt),
        "--out", str(out_dir),
        "--name", name,
    ]
    if force:
        cmd.append("--force")
    proc = subprocess.run(
        cmd, cwd=str(ROOT), text=True, capture_output=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1200:].strip()
        raise RuntimeError(
            f"run_contract.py 失败（exit={proc.returncode}）: {tail}")
    run_path = out_dir / "run.json"
    if not run_path.exists():
        raise RuntimeError(
            f"run_contract.py 未写 run.json: {_rel(run_path)}")
    return load_json(run_path)


def _generate_variants(out: Path, manifest: dict, progress=None,
                       generate_fn=None) -> dict:
    """逐条生成，单条失败不中断整批。"""
    stage = manifest.setdefault("stages", {}).setdefault(
        "generation", {"output": "v*/variant_*.mp4", "variants": {}})
    paths = sorted(out.glob("v[0-9][0-9]/contract.json"))
    if not paths:
        raise RuntimeError("没有可生成的 contract")
    stage["status"] = "running"
    old_variants = stage.get("variants") or {}
    variants = {
        f"v{idx:02d}": dict(old_variants.get(f"v{idx:02d}")
                            or {"status": "pending"})
        for idx, _cp in enumerate(paths, 1)
    }
    stage["variants"] = variants
    _save_manifest(out, manifest)
    _emit(progress, "generation", current=0, total=len(paths),
          status="running")

    fn = generate_fn or _run_contract_script
    videos: list[str] = []
    for idx, cp in enumerate(paths, 1):
        key = f"v{idx:02d}"
        vdir = cp.parent
        video = vdir / f"variant_{idx:02d}.mp4"
        prompt = vdir / "prompt_h3.txt"
        variant = variants.setdefault(key, {})
        try:
            existing = _variant_generated(vdir, video)
            if existing:
                variant.update({
                    "status": "done",
                    "video": _rel(video),
                    "provider_task": existing.get("provider_task"),
                    "provider_via": existing.get("provider_via"),
                    "review_path": existing.get("review_path"),
                    "job": existing.get("job"),
                    "skipped": True,
                    "error": None,
                })
                videos.append(_rel(video))
            else:
                if not prompt.exists():
                    raise FileNotFoundError(f"prompt 不存在: {_rel(prompt)}")
                variant.update({"status": "running", "video": _rel(video)})
                _save_manifest(out, manifest)
                _emit(progress, "generation", current=idx - 1,
                      total=len(paths), variant=key, status="running")
                # Always force a new provider submission for a job run.
                # `run_contract.py` otherwise uses a slice_id-based idempotency
                # key, which would reuse a previous run's video for the same
                # product/style/variant.
                info = fn(cp, prompt, vdir, video.name, force=True)
                if not video.exists() or video.stat().st_size <= 0:
                    raise RuntimeError(f"{key} 未产出有效视频")
                variant.update({
                    "status": "done",
                    "video": _rel(video),
                    "provider_task": info.get("provider_task"),
                    "provider_via": info.get("provider_via"),
                    "review_path": info.get("review_path"),
                    "job": info.get("job"),
                    "error": None,
                })
                videos.append(_rel(video))
        except Exception as exc:
            msg = f"{key}: {type(exc).__name__}: {exc}"
            variant.update({"status": "failed", "error": msg})
            manifest.setdefault("errors", []).append(msg)
            _emit(progress, "generation", current=idx, total=len(paths),
                  variant=key, status="failed")
        _save_manifest(out, manifest)
        _emit(progress, "generation", current=idx, total=len(paths),
              variant=key, status=variant.get("status"))

    done = sum(1 for x in variants.values() if x.get("status") == "done")
    failed = sum(1 for x in variants.values() if x.get("status") == "failed")
    if done == len(paths):
        stage["status"] = "done"
        manifest["status"] = "done"
    elif done:
        stage["status"] = "partial"
        manifest["status"] = "partial"
    else:
        stage["status"] = "failed"
        manifest["status"] = "failed"
    manifest["videos"] = done
    _save_manifest(out, manifest)
    return {"videos": videos, "generation": stage}


def _summary_variants(out: Path, contracts: list[dict]) -> list[dict]:
    rows = []
    for i, c in enumerate(contracts, 1):
        fmt = (c.get("target") or {}).get("format") or {}
        pres = fmt.get("presentation") or {}
        prompt_path = out / f"v{i:02d}" / "prompt_h3.txt"
        prompt = prompt_path.read_text(encoding="utf-8") \
            if prompt_path.exists() else ""
        rows.append({
            "id": f"v{i:02d}",
            "name": (c.get("structure") or {}).get("name"),
            "style": pres.get("name"),
            "person_visibility": pres.get("person_visibility"),
            "presenter_mode": pres.get("presenter_mode"),
            "camera_family": pres.get("camera_family"),
            "scene_family": pres.get("scene_family"),
            "copy": (c.get("structure") or {}).get("copy_profile"),
            "creative_world": (c.get("structure") or {}).get("creative_world"),
            "prompt_chars": len(prompt),
            "prompt_sections": {
                k: (k in prompt) for k in (
                    "【主体定义】", "【全局合同】", "【商品硬约束】",
                    "【逻辑分镜时间轴】", "【负面约束】")
            },
            "validation": c.get("_validation") or {},
            "prompt": f"v{i:02d}/prompt_h3.txt",
            "contract": f"v{i:02d}/contract.json",
            "video": None,
            "review": None,
        })
    return rows


def _sync_summary(out: Path, manifest: dict, contracts: list[dict] | None = None,
                  styles=None) -> None:
    path = out / "summary.json"
    if contracts is not None:
        summary = {
            "schema_version": "p0-summary/v0",
            "run_id": out.name,
            "seed": manifest.get("seed"),
            "styles": styles or [],
            "audit": manifest.get("audit") or {},
            "variants": _summary_variants(out, contracts),
        }
    else:
        try:
            summary = load_json(path)
        except Exception:
            summary = {"schema_version": "p0-summary/v0",
                       "run_id": out.name, "variants": []}
    gen = (manifest.get("stages") or {}).get("generation") or {}
    variants = gen.get("variants") or {}
    for row in summary.get("variants") or []:
        item = variants.get(str(row.get("id"))) or {}
        if item.get("video"):
            row["video"] = item["video"]
        if item.get("review_path"):
            row["review"] = item["review_path"]
        if item.get("provider_task"):
            row["provider_task"] = item["provider_task"]
    save_json(path, summary)


def run_p0(profile_ref: str, text: str | None = None, n: int = 5,
           out_root: str | None = None, seed: int | None = None,
           atlas_dir: str | None = None,
           person: str | None = None,
           product_image: str | None = None,
           prepare_materials: bool = False,
           refresh_materials: bool = False,
           generate: bool = False,
           progress=None,
           generate_fn=None,
           context: HarnessContext | None = None) -> dict:
    if context is None:
        from .harness.local import default_context
        context = default_context(progress=progress)
    if progress is None:
        progress = context.progress
    profile, profile_path = context.profiles.load(profile_ref)
    profile = _apply_overrides(profile, product_image, person, context.root)
    prepare_materials = bool(prepare_materials or refresh_materials)
    run_id = f"p0-{profile['product_id']}-{time.strftime('%Y%m%d-%H%M%S')}"
    out = Path(out_root) if out_root else ROOT / "data" / "runs" / run_id
    if not out.is_absolute():
        out = ROOT / out
    if (out / "run.json").exists():
        raise RuntimeError(
            f"run 已存在，拒绝覆盖: {_rel(out)}；请用新的 out_root 或 resume")
    out.mkdir(parents=True, exist_ok=True)
    inputs = {
        "profile": _rel(profile_path),
        "product_image": product_image,
        "person": person,
        "text": text,
        "n": n,
        "seed": seed,
        "prepare_materials": bool(prepare_materials),
        "refresh_materials": bool(refresh_materials),
        "generate": bool(generate),
    }
    manifest = _initial_manifest(out, profile, profile_path, inputs, n, seed,
                                 prepare_materials, generate)
    _save_manifest(out, manifest)

    try:
        _stage(manifest, "materials", "running")
        _save_manifest(out, manifest)
        if prepare_materials:
            mat = context.materials.prepare(
                refresh=refresh_materials,
                progress=lambda phase, extra: _emit(progress, phase, **extra))
            _stage(manifest, "materials", "done", **mat)
        else:
            _stage(manifest, "materials", "skipped")
        _save_manifest(out, manifest)
        _emit(progress, "materials", status="done")
    except Exception as exc:
        _fail(out, manifest, "materials", exc)
        raise

    try:
        _stage(manifest, "anchor", "running")
        _save_manifest(out, manifest)
        anchor = anchor_mod.build_anchor(profile)
        errs = anchor_mod.validate_anchor(anchor)
        if errs:
            raise ValueError("anchor 校验失败: " + "; ".join(errs))
        brief = anchor_mod.anchor_to_brief(anchor, n, text)
        save_json(out / "anchor.json", anchor)
        _stage(manifest, "anchor", "done", output="anchor.json")
        _save_manifest(out, manifest)
        _emit(progress, "anchor", status="done")
    except Exception as exc:
        _fail(out, manifest, "anchor", exc)
        raise

    try:
        _stage(manifest, "style_atlas", "running")
        _save_manifest(out, manifest)
        atlas = style_atlas.build_style_atlas(
            Path(atlas_dir) if atlas_dir else context.facet_dir)
        save_json(out / "style_atlas.json", atlas)
        _stage(manifest, "style_atlas", "done", output="style_atlas.json",
               refs=atlas.get("count"))
        _save_manifest(out, manifest)
        _emit(progress, "style_atlas", status="done")
    except Exception as exc:
        _fail(out, manifest, "style_atlas", exc)
        raise

    try:
        _stage(manifest, "planner", "running")
        _save_manifest(out, manifest)
        plan = plan_styles(atlas, n, anchor, seed)
        save_json(out / "style_plan.json", plan)
        _stage(manifest, "planner", "done", output="style_plan.json",
               styles=len(plan.get("styles") or []))
        _save_manifest(out, manifest)
        _emit(progress, "planner", status="done")
    except Exception as exc:
        _fail(out, manifest, "planner", exc)
        raise

    try:
        _stage(manifest, "worlds", "running")
        _save_manifest(out, manifest)
        ops = operators.load_operators()
        candidates = proposer.propose_worlds(
            anchor, max(15, n * 4), ops, llm=context.llm)
        accepted, rejected = critic.critique(candidates, anchor)
        if len(accepted) < n:
            raise RuntimeError(
                f"创意世界候选不足: accepted={len(accepted)} < {n}; "
                f"rejected={len(rejected)}")
        worlds = selector.select_worlds(accepted, n)
        pairs = selector.pair_styles(worlds, plan["styles"])
        plan["styles"] = [style for world, style in pairs]
        save_json(out / "world_candidates.json", {
            "proposed": candidates, "accepted": accepted,
            "rejected": rejected})
        save_json(out / "worlds.json", {
            "worlds": worlds,
            "pairs": [{"style_id": s2.get("id"), "world_id": w.get("id")}
                      for w, s2 in pairs],
            "coverage": selector.coverage(worlds),
            "policy": {"operators": [x.get("name") for x in ops]},
        })
        _stage(manifest, "worlds", "done", output="worlds.json",
               selected=len(worlds), candidates=len(candidates),
               rejected=len(rejected))
        _save_manifest(out, manifest)
        _emit(progress, "worlds", status="done", worlds=len(worlds))
    except Exception as exc:
        _fail(out, manifest, "worlds", exc)
        raise

    try:
        _stage(manifest, "contracts", "running")
        _save_manifest(out, manifest)
        contracts = composer.compose_batch(
            anchor, brief, plan, context.facets.catalog(), out,
            deps=context.composer_deps)
        contracts = composer.diversify_copy(
            contracts, anchor, plan, out, deps=context.composer_deps)
        _stage(manifest, "contracts", "done", output="v*/contract.json",
               count=len(contracts))
        _save_manifest(out, manifest)
        _emit(progress, "contracts", status="done", contracts=len(contracts))
    except Exception as exc:
        _fail(out, manifest, "contracts", exc)
        raise

    try:
        _stage(manifest, "audit", "running")
        _save_manifest(out, manifest)
        audit = audit_contracts(contracts, anchor, plan["styles"],
                                plan.get("distances"))
        save_json(out / "audit.json", audit)
        manifest["audit"] = {
            "ok": audit.get("ok"),
            "anchor_errors": len((audit.get("anchor") or {}).get("errors") or []),
            "copy_duplicates": (audit.get("copy") or {}).get(
                "cross_variant", {}).get("duplicates"),
            "min_visual_distance": (audit.get("style") or {}).get("min_visual_distance"),
            "min_copy_distance": (audit.get("style") or {}).get("min_copy_distance"),
            "coverage": (audit.get("style") or {}).get("coverage"),
            "perceptual_ok": (audit.get("style") or {}).get("perceptual_ok"),
            "concept_ok": (audit.get("concept") or {}).get("ok"),
            "semantic_world_ok": ((audit.get("semantic") or {}).get("worlds")
                                  or {}).get("ok"),
            "semantic_contract_ok": ((audit.get("semantic") or {}).get("contracts")
                                     or {}).get("ok"),
            "semantic_min_distance": ((audit.get("semantic") or {}).get("worlds")
                                      or {}).get("min_distance"),
            "contract_semantic_min_distance": (
                (audit.get("semantic") or {}).get("contracts") or {}
            ).get("min_distance"),
            "worlds": (audit.get("concept") or {}).get("count"),
        }
        _stage(manifest, "audit", "done", output="audit.json",
               ok=audit.get("ok"))
        _save_manifest(out, manifest)
        _emit(progress, "audit", status="done", ok=audit.get("ok"))
    except Exception as exc:
        _fail(out, manifest, "audit", exc)
        raise

    _sync_summary(out, manifest, contracts, plan.get("styles"))
    semantic_ok = bool((audit.get("semantic") or {}).get("ok", True))
    if not generate:
        _stage(manifest, "generation", "skipped")
        manifest["status"] = ("contracts_done" if semantic_ok
                               else "audit_failed")
        if not semantic_ok:
            manifest.setdefault("errors", []).append(
                "semantic audit failed: 单批 world/contract 语义距离不足")
        _save_manifest(out, manifest)
        return {
            "run_dir": str(out), "manifest": manifest, "audit": audit,
            "styles": plan.get("styles"), "worlds": worlds,
            "contracts": [str(out / f"v{i:02d}" / "contract.json")
                          for i in range(1, len(contracts) + 1)],
            "videos": [], "inputs": inputs,
            "generation": manifest["stages"]["generation"],
        }

    if not semantic_ok:
        _stage(manifest, "generation", "skipped",
               error="semantic audit failed")
        manifest["status"] = "audit_failed"
        manifest.setdefault("errors", []).append(
            "semantic audit failed: 单批 world/contract 语义距离不足，已跳过 H3")
        _save_manifest(out, manifest)
        return {
            "run_dir": str(out), "manifest": manifest, "audit": audit,
            "styles": plan.get("styles"), "worlds": worlds,
            "contracts": [str(out / f"v{i:02d}" / "contract.json")
                          for i in range(1, len(contracts) + 1)],
            "videos": [], "inputs": inputs,
            "generation": manifest["stages"]["generation"],
        }

    try:
        result = _generate_variants(
            out, manifest, progress=progress,
            generate_fn=generate_fn or context.video.generate)
        _sync_summary(out, manifest)
        _emit(progress, "generation", status=manifest["status"],
              videos=len(result["videos"]))
    except Exception as exc:
        _fail(out, manifest, "generation", exc)
        raise
    return {
        "run_dir": str(out), "manifest": manifest, "audit": audit,
        "styles": plan.get("styles"), "worlds": worlds,
        "contracts": [str(out / f"v{i:02d}" / "contract.json")
                      for i in range(1, len(contracts) + 1)],
        "videos": result.get("videos") or [],
        "inputs": inputs,
        "generation": result.get("generation") or {},
    }


def resume_p0_generation(run_dir: str | Path, progress=None,
                         generate_fn=None,
                         context: HarnessContext | None = None) -> dict:
    """只续跑 H3 生成；不重跑素材/风格/世界/契约。"""
    out = Path(run_dir)
    if not out.is_absolute():
        out = ROOT / out
    if context is None:
        from .harness.local import default_context
        context = default_context(progress=progress)
    if progress is None:
        progress = context.progress
    manifest = load_json(out / "run.json")
    engine = str(manifest.get("engine") or "")
    if not engine.startswith("p0"):
        raise ValueError(f"不是 P0 run: engine={engine}")
    paths = sorted(out.glob("v[0-9][0-9]/contract.json"))
    if not paths:
        raise RuntimeError("run 中没有 contract，无法续跑生成")
    audit_path = out / "audit.json"
    if audit_path.exists():
        audit = load_json(audit_path)
        if not bool((audit.get("semantic") or {}).get("ok", True)):
            raise RuntimeError(
                "semantic audit 未通过；请换 seed/重新生成，不要直接续跑")
    result = _generate_variants(
        out, manifest, progress=progress,
        generate_fn=generate_fn or context.video.generate)
    _sync_summary(out, manifest)
    _save_manifest(out, manifest)
    return {"run_dir": str(out), "manifest": manifest,
            "videos": result.get("videos") or [],
            "generation": result.get("generation") or {}}
