"""Fission Runner：端到端编排 + run manifest + resume。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from orchestrator.app import reference_fission

from . import brief as brief_mod
from . import contracts as contracts_mod
from . import guidance as guidance_mod
from . import pool as pool_mod
from . import profiles
from . import variants as variants_mod
from .io import load_json, save_json

ROOT = Path(__file__).resolve().parents[2]


def _now() -> int:
    return int(time.time())


def _manifest(run_id: str, profile: dict, inputs: dict) -> dict:
    return {
        "schema_version": "fission-run/v1",
        "run_id": run_id,
        "status": "running",
        "profile_id": profile.get("product_id"),
        "inputs": inputs,
        "stages": {
            "pool": {"status": "pending", "output": "pool_digest.json"},
            "brief": {"status": "pending", "output": "brief.json"},
            "guidance": {"status": "pending", "output": "guidance.json"},
            "variants": {"status": "pending", "output": "variants.json"},
            "contracts": {"status": "pending", "output": "v*/contract.json"},
            "generation": {"status": "pending", "variants": {}},
            "evaluation": {"status": "pending", "output": "evaluation.json"},
        },
        "created_at": _now(),
        "updated_at": _now(),
        "errors": [],
    }


def _save_manifest(run_dir: Path, manifest: dict):
    manifest["updated_at"] = _now()
    save_json(run_dir / "run.json", manifest)


def _stage(manifest: dict, name: str, status: str, **extra):
    st = manifest["stages"].setdefault(name, {})
    st.update({"status": status, **extra})


def _done(manifest: dict, name: str, path: Path) -> bool:
    st = (manifest.get("stages") or {}).get(name) or {}
    return st.get("status") == "done" and path.exists()


def _run_script(script: str, *args: str):
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    print("$", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT), text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{script} failed")


def run_pipeline(profile_ref: str, text: str | None, n: int = 3,
                 out_root: str | None = None, skip_generate: bool = False,
                 resume: bool = False, person_override: str | None = None,
                 product_image: str | None = None) -> dict:
    profile, profile_path = profiles.load_profile(profile_ref)
    if product_image:
        p = Path(product_image)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            raise SystemExit(f"商品图不存在: {p}")
        profile["image"] = str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    if not text:
        text = (f"商品是{profile.get('category')}，人物用固定人物图，"
                f"产出{n}条裂变素材")
    run_id = f"fission-{profile['product_id']}-{time.strftime('%Y%m%d-%H%M%S')}"
    if out_root:
        run_dir = Path(out_root)
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
        if (run_dir / "run.json").exists() and not resume:
            raise SystemExit(f"{run_dir} 已有 run.json；用 --resume 继续")
    else:
        run_dir = ROOT / "data" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    inputs = {"profile": str(profile_path), "product_image": profile["image"],
              "person": person_override
              or (profile.get("person") or {}).get("image"),
              "text": text, "n": n}
    if resume and (run_dir / "run.json").exists():
        manifest = load_json(run_dir / "run.json")
        manifest["status"] = "running"
        manifest.setdefault("errors", [])
    else:
        manifest = _manifest(run_dir.name, profile, inputs)
    _save_manifest(run_dir, manifest)

    # 1. pool
    digest_path = run_dir / "pool_digest.json"
    if not (resume and _done(manifest, "pool", digest_path)):
        digest = pool_mod.build_digest()
        save_json(digest_path, digest)
        _stage(manifest, "pool", "done", output="pool_digest.json",
               refs=len(digest["payload"]["refs"]))
        _save_manifest(run_dir, manifest)
    else:
        digest = load_json(digest_path)

    # 2. brief
    brief_path = run_dir / "brief.json"
    if not (resume and _done(manifest, "brief", brief_path)):
        brief = brief_mod.synthesize_brief(
            profile, text, deliverables=n, person_override=person_override)
        save_json(brief_path, brief)
        _stage(manifest, "brief", "done", output="brief.json")
        _save_manifest(run_dir, manifest)
    else:
        brief = load_json(brief_path)

    # 3. guidance
    guidance_path = run_dir / "guidance.json"
    if not (resume and _done(manifest, "guidance", guidance_path)):
        guidance = guidance_mod.synthesize_guidance(brief, digest)
        save_json(guidance_path, guidance)
        _stage(manifest, "guidance", "done", output="guidance.json",
               patterns=len(guidance["payload"]["patterns"]))
        _save_manifest(run_dir, manifest)
    else:
        guidance = load_json(guidance_path)

    # 4. variants
    variants_path = run_dir / "variants.json"
    if not (resume and _done(manifest, "variants", variants_path)):
        vset = variants_mod.generate_variants(brief, guidance, digest, n)
        save_json(variants_path, vset)
        _stage(manifest, "variants", "done", output="variants.json",
               count=len(vset["payload"]["variants"]))
        _save_manifest(run_dir, manifest)
    else:
        vset = load_json(variants_path)

    # 5. contracts
    catalog = pool_mod.anchor_catalog(digest)
    made = []
    for i, v in enumerate(vset["payload"]["variants"], 1):
        d = run_dir / f"v{i:02d}"
        cp = d / "contract.json"
        if resume and cp.exists() and _done(manifest, "contracts", cp):
            made.append({"dir": str(d), "primary_ref": None,
                         "valid": True, "errors": [], "warnings": [],
                         "resumed": True})
            continue
        info = contracts_mod.build_contract_for_variant(
            v, brief, profile, catalog, d, i)
        made.append(info)
        print(json.dumps(info, ensure_ascii=False), flush=True)
    contract_files = sorted(run_dir.glob("v[0-9][0-9]/contract.json"))
    _stage(manifest, "contracts", "done", output="v*/contract.json",
           count=len(contract_files))
    _save_manifest(run_dir, manifest)
    if skip_generate:
        manifest["status"] = "contracts_done"
        _save_manifest(run_dir, manifest)
        return {"run_dir": str(run_dir), "manifest": manifest,
                "contracts": [str(x) for x in contract_files]}

    # 6. generation
    gen = manifest["stages"].setdefault("generation", {"variants": {}})
    gen["status"] = "running"
    _save_manifest(run_dir, manifest)
    videos = []
    for i, cp in enumerate(contract_files, 1):
        d = cp.parent
        name = f"variant_{i:02d}.mp4"
        vp = d / name
        key = f"v{i:02d}"
        if resume and vp.exists() and (gen.get("variants", {}).get(key, {})
                                        .get("status") == "done"):
            videos.append(str(vp))
            continue
        try:
            _run_script("run_contract.py", "--contract", str(cp),
                        "--prompt", str(d / "prompt_h3.txt"),
                        "--out", str(d), "--name", name)
            ok = vp.exists()
            gen.setdefault("variants", {})[key] = {
                "status": "done" if ok else "failed",
                "video": str(vp.relative_to(ROOT)) if vp.exists() else None,
            }
            if ok:
                videos.append(str(vp))
        except Exception as e:
            gen.setdefault("variants", {})[key] = {
                "status": "failed", "error": f"{type(e).__name__}: {e}"}
            gen["status"] = "failed"
            manifest["errors"].append(f"generation {key}: {e}")
            _save_manifest(run_dir, manifest)
            raise
        _save_manifest(run_dir, manifest)
    gen["status"] = "done" if len(videos) == len(contract_files) else "partial"
    _save_manifest(run_dir, manifest)

    # 7. evaluation
    evals = []
    extra_images = [
        ROOT / profile[k] for k in ("back_image",)
        if profile.get(k) and (ROOT / profile[k]).exists()]
    for i, vp in enumerate(videos, 1):
        try:
            res = reference_fission.validate_output(
                Path(vp), ROOT / profile["image"], Path(vp).parent, i,
                extra_images=extra_images)
        except Exception as e:
            res = {"index": i, "error": f"{type(e).__name__}: {e}"}
        evals.append({"video": vp, "validation": res})
        print(json.dumps(evals[-1], ensure_ascii=False), flush=True)
    save_json(run_dir / "evaluation.json",
              {"videos": videos, "evaluations": evals})
    _stage(manifest, "evaluation", "done", output="evaluation.json")
    manifest["status"] = "done" if len(videos) == len(contract_files) else "partial"
    _save_manifest(run_dir, manifest)
    return {"run_dir": str(run_dir), "manifest": manifest,
            "videos": videos, "evaluation": str(run_dir / "evaluation.json")}


def main():
    ap = argparse.ArgumentParser(description="Fission 端到端链路")
    ap.add_argument("--profile", default="bra-milk-lace",
                    help="configs/products 下的 profile id 或 JSON 路径")
    ap.add_argument("--product-image", default=None,
                    help="覆盖 profile 商品图")
    ap.add_argument("--person", default=None, help="覆盖 profile 人物图")
    ap.add_argument("--person-image", default=None, help="--person 的别名")
    ap.add_argument("--text", default=None,
                    help="用户文字；默认按 profile 品类生成")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--out-root", default=None)
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    res = run_pipeline(a.profile, a.text, a.n, a.out_root,
                       a.skip_generate, a.resume,
                       a.person or a.person_image, a.product_image)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
