#!/usr/bin/env python3
"""只读检查项目布局与数据层约束。

用法：
    .venv/bin/python scripts/check_layout.py
    .venv/bin/python scripts/check_layout.py --json
    .venv/bin/python scripts/check_layout.py --strict   # warning 也算失败

不移动、不删除、不重写任何文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = [
    "assets", "assets/sources", "assets/persons", "assets/products",
    "configs", "configs/products",
    "pipelines/fission", "tests",
    "data", "data/catalog", "data/reference_cases", "data/reference_facets",
    "data/reference_alignments", "data/reference_index",
    "data/reference_runs", "data/fission_slices", "data/plans",
    "outputs", "outputs/review", "outputs/approved", "outputs/published",
    "outputs/failed", "outputs/tmp", "outputs/fission",
    "docs",
]
MEDIA_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _size_mb(path: Path) -> float:
    try:
        out = subprocess.run(["du", "-sk", str(path)], capture_output=True,
                             text=True, timeout=20).stdout.split()
        return round(int(out[0]) / 1024.0, 1) if out else 0.0
    except Exception:
        return 0.0


def _abs_strings(obj, prefix=""):
    """递归找绝对路径字符串，返回 (path, value)。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_abs_strings(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_abs_strings(v, f"{prefix}[{i}]"))
    elif isinstance(obj, str):
        if obj.startswith("/Users/") or obj.startswith("/home/"):
            out.append((prefix, obj))
    return out


class Audit:
    def __init__(self):
        self.rows = []

    def add(self, level: str, code: str, msg: str, **extra):
        self.rows.append({"level": level, "code": code, "msg": msg, **extra})

    def ok(self, code, msg, **extra):
        self.add("PASS", code, msg, **extra)

    def warn(self, code, msg, **extra):
        self.add("WARN", code, msg, **extra)

    def fail(self, code, msg, **extra):
        self.add("FAIL", code, msg, **extra)

    def summary(self):
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for r in self.rows:
            counts[r["level"]] += 1
        return counts


def check_dirs(a: Audit):
    for d in REQUIRED_DIRS:
        if (ROOT / d).is_dir():
            a.ok("dir.exists", d)
        else:
            a.fail("dir.missing", d)


def check_pool_cases(a: Audit):
    pool = _load(ROOT / "data/reference_pool.json")
    if not isinstance(pool, list):
        a.fail("pool.invalid", "data/reference_pool.json 不是数组")
        return
    pool_ids = {str(x.get("id")) for x in pool if isinstance(x, dict)}
    case_dirs = {p.name for p in (ROOT / "data/reference_cases").glob("ref-*")
                 if p.is_dir()}
    facet_ids = {p.stem for p in (ROOT / "data/reference_facets").glob("ref-*.json")}
    missing = sorted(pool_ids - case_dirs)
    orphan = sorted(case_dirs - pool_ids)
    no_facet = sorted(case_dirs - facet_ids)
    orphan_facet = sorted(facet_ids - case_dirs)
    if missing:
        a.fail("pool.missing_cases", f"池中有 {len(missing)} 条无案例目录: {missing[:5]}")
    else:
        a.ok("pool.cases", f"{len(pool_ids)} 条池记录都有案例目录")
    if orphan:
        a.warn("cases.orphan", f"{len(orphan)} 个案例目录不在池中: {orphan[:5]}")
    if no_facet:
        a.warn("facets.missing", f"{len(no_facet)} 个案例没有 facet: {no_facet[:5]}")
    if orphan_facet:
        a.warn("facets.orphan", f"{len(orphan_facet)} 个 facet 没有案例目录: {orphan_facet[:5]}")
    a.add("PASS" if not orphan_facet else "WARN", "facets.count",
          f"cases={len(case_dirs)} facets={len(facet_ids)} pool={len(pool_ids)}")


def check_facets(a: Audit):
    checked = stale = bad_schema = 0
    for p in sorted((ROOT / "data/reference_facets").glob("ref-*.json")):
        f = _load(p)
        if not isinstance(f, dict):
            a.fail("facet.invalid", p.name)
            continue
        checked += 1
        if not f.get("schema_version"):
            bad_schema += 1
        ref_id = f.get("ref_id") or p.stem
        desc = ROOT / "data/reference_cases" / ref_id / "descriptions.json"
        if not desc.exists():
            a.warn("facet.no_source", ref_id)
            continue
        src_sha = (f.get("provenance") or {}).get("source_sha256")
        if src_sha and src_sha != _sha(desc):
            stale += 1
            a.warn("facet.stale", f"{ref_id} source_sha256 与 descriptions.json 不一致")
        align = (f.get("structure") or {}).get("beat_shot_alignment") or {}
        method = align.get("method") or "none"
        if method == "llm_monotonic":
            ap = ROOT / "data/reference_alignments" / f"{ref_id}.json"
            if not ap.exists():
                a.warn("facet.alignment_missing", f"{ref_id} 标记 llm 但无对齐文件")
            else:
                aj = _load(ap) or {}
                if aj.get("source_sha256") and aj.get("source_sha256") != src_sha:
                    a.warn("facet.alignment_stale", f"{ref_id} 对齐文件 source_sha256 不一致")
    if stale:
        a.warn("facets.stale_summary", f"{stale}/{checked} 个 facet 源描述已变化")
    else:
        a.ok("facets.fresh", f"{checked} 个 facet 与源描述一致")
    if bad_schema:
        a.warn("facets.schema", f"{bad_schema}/{checked} 个 facet 缺 schema_version")
    else:
        a.ok("facets.schema", f"{checked} 个 facet 有 schema_version")


def check_indexes(a: Audit):
    cases = len([p for p in (ROOT / "data/reference_cases").glob("ref-*") if p.is_dir()])
    facets = len(list((ROOT / "data/reference_facets").glob("ref-*.json")))
    ri = _load(ROOT / "data/reference_index/index.json") or {}
    if ri.get("cases") != cases:
        a.warn("index.reference", f"reference_index cases={ri.get('cases')} 实际={cases}")
    else:
        a.ok("index.reference", f"reference_index cases={cases}")
    ci = _load(ROOT / "data/reference_cases/index.json") or {}
    if ci.get("total") != cases:
        a.warn("index.cases_stale",
               f"reference_cases/index.json total={ci.get('total')} 实际={cases}（该索引未被 list_cases 使用）")
    else:
        a.ok("index.cases", f"reference_cases index total={cases}")
    fi = _load(ROOT / "data/reference_facets/index.json") or {}
    if fi.get("total") != facets:
        a.warn("index.facets", f"reference_facets index total={fi.get('total')} 实际={facets}")
    else:
        a.ok("index.facets", f"reference_facets index total={facets}")

    slices = len([p for p in (ROOT / "data/fission_slices").glob("slice-*")
                  if p.is_dir()])
    si = _load(ROOT / "data/fission_slices/index.json") or {}
    if si.get("total") != slices:
        a.warn("index.slices",
               f"fission_slices index total={si.get('total')} 实际={slices}")
    else:
        a.ok("index.slices", f"fission_slices index total={slices}")

    plans = len(list((ROOT / "data/plans").glob("pvplan-*.json")))
    pi = _load(ROOT / "data/plans/plan_index.json") or {}
    if pi.get("total") != plans:
        a.warn("index.plans",
               f"plan_index total={pi.get('total')} 实际={plans}")
    else:
        a.ok("index.plans", f"plan_index total={plans}")
    orphan_items = [x for x in (pi.get("items") or [])
                    if (x.get("owner") or
                        ("fission_run" if x.get("run_id")
                         else "review_item" if x.get("review_item")
                         else "job_history" if x.get("jobs")
                         else "unlinked")) == "unlinked"]
    if orphan_items:
        ids = [x.get("plan_id") for x in orphan_items]
        a.warn("index.plans_orphans",
               f"{len(ids)} 个 plan 未关联 run/review: {ids[:5]}")
    else:
        a.ok("index.plans_orphans", "所有 plan 都有 run 或 review 归属")


def check_schemas(a: Audit):
    expected = [
        "fission-facet.v0.schema.json",
        "reference-alignment.v1.schema.json",
        "fission-contract.v0.schema.json",
        "run.v1.schema.json",
        "review-item.v1.schema.json",
        "export-manifest.v1.schema.json",
    ]
    missing = [x for x in expected
               if not (ROOT / "docs/schemas" / x).exists()]
    if missing:
        a.warn("schemas.missing", f"docs/schemas 缺 {missing}")
    else:
        a.ok("schemas", f"{len(expected)} 个 schema 存在")


def check_profiles(a: Audit):
    profiles = sorted((ROOT / "configs" / "products").glob("*.json"))
    if not profiles:
        a.warn("profiles.none", "configs/products 没有 profile")
        return
    bad = []
    for p in profiles:
        d = _load(p)
        if not isinstance(d, dict):
            bad.append(f"{p.name}: JSON 解析失败")
            continue
        missing = [k for k in (
            "product_id", "image", "category", "identity", "must_show",
            "must_not_change", "claims", "person") if not d.get(k)]
        if missing:
            bad.append(f"{p.name}: 缺 {missing}")
        for key in ("image",):
            if d.get(key) and not (ROOT / d[key]).exists():
                bad.append(f"{p.name}: {key} 不存在")
        person = (d.get("person") or {}).get("image")
        if not person or not (ROOT / person).exists():
            bad.append(f"{p.name}: person.image 不存在")
    if bad:
        a.warn("profiles.invalid", "；".join(bad))
    else:
        a.ok("profiles", f"{len(profiles)} 个 profile 有效")


def check_fission_runs(a: Audit):
    root = ROOT / "data" / "runs"
    if not root.exists():
        a.warn("runs.none", "data/runs 不存在")
        return
    runs = [p for p in root.iterdir() if p.is_dir()]
    missing = [p.name for p in runs if not (p / "run.json").exists()]
    if missing:
        a.warn("runs.no_manifest",
               f"{len(missing)} 个 run 缺 run.json（legacy）: {missing[:5]}")
    else:
        a.ok("runs.manifest", f"{len(runs)} 个 run 有 manifest")


def check_runs(a: Audit):
    runs = [p for p in (ROOT / "data/reference_runs").iterdir() if p.is_dir()]
    complete = incomplete = bad = 0
    allowed = {"draft", "dry_run", "no_generate", "generated",
               "exported", "failed"}
    for d in sorted(runs):
        if not (d / "brief.json").exists():
            a.warn("run.no_brief", d.name)
            continue
        has_summary = (d / "summary.json").exists()
        has_outputs = (d / "outputs").is_dir() and any(
            (d / "outputs").glob("variant_*.mp4"))
        status = (_load(d / "run.json") or {}).get("status")
        if status and status not in allowed:
            bad += 1
            a.warn("run.status_invalid", f"{d.name} status={status!r}")
        if has_summary and has_outputs:
            complete += 1
            if status not in ("generated", "exported"):
                bad += 1
                a.warn("run.no_status",
                       f"{d.name} 已完成但缺有效 run.json 状态")
        else:
            incomplete += 1
            if status not in ("dry_run", "no_generate", "failed", "draft"):
                bad += 1
                a.warn("run.no_status",
                       f"{d.name} 未完成且缺有效 run.json 状态")
    a.add("PASS" if bad == 0 else "WARN", "runs.summary",
          f"runs={len(runs)} complete={complete} "
          f"incomplete={incomplete} status_bad={bad}")


def check_exports(a: Audit):
    exports = [p for p in (ROOT / "outputs/fission").iterdir()
               if p.is_dir() and not p.name.startswith(".")]
    if not exports:
        a.warn("export.none", "outputs/fission 无导出目录")
        return
    for d in sorted(exports):
        man = _load(d / "manifest.json")
        if not isinstance(man, dict):
            a.warn("export.no_manifest", d.name)
            continue
        run_dir = Path(str(man.get("run_dir") or ""))
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
        if not run_dir.exists():
            a.warn("export.run_missing", f"{d.name} manifest.run_dir 不存在: {run_dir}")
        items = man.get("items") or []
        vids = list(d.glob("variant_*.mp4"))
        if len(items) != len(vids):
            a.warn("export.count", f"{d.name} manifest items={len(items)} mp4={len(vids)}")
        else:
            a.ok("export", f"{d.name} items={len(items)}")


def check_review(a: Audit):
    review = ROOT / "outputs/review"
    media = {p.stem for p in review.iterdir()
             if p.is_file() and p.suffix.lower() in MEDIA_EXT}
    sidecars = {p.stem for p in review.iterdir()
                if p.is_file() and p.suffix.lower() == ".json"}
    orphan_media = sorted(media - sidecars)
    orphan_sidecar = sorted(sidecars - media)
    if orphan_media:
        a.warn("review.orphan_media", f"{len(orphan_media)} 个媒体无 sidecar: {orphan_media[:5]}")
    if orphan_sidecar:
        a.warn("review.orphan_sidecar", f"{len(orphan_sidecar)} 个 sidecar 无媒体: {orphan_sidecar[:5]}")
    if not orphan_media and not orphan_sidecar:
        a.ok("review.pairs", f"{len(media)} 对媒体/sidecar")
    old = []
    now = time.time()
    for p in review.glob("*.json"):
        d = _load(p) or {}
        ts = d.get("created_at")
        if isinstance(ts, (int, float)) and now - ts > 30 * 86400:
            old.append(p.stem)
    if old:
        a.warn("review.age", f"{len(old)} 条 pending 超过 30 天: {old[:5]}")
    a.add("PASS" if len(media) <= 50 else "WARN", "review.size",
          f"pending 媒体 {len(media)} 个，目录 {_size_mb(review)} MB")


def check_hygiene(a: Audit):
    ds = []
    for base in (ROOT / "data", ROOT / "outputs"):
        ds.extend(str(p.relative_to(ROOT)) for p in base.rglob(".DS_Store"))
    if ds:
        a.warn("hygiene.ds_store", f"{len(ds)} 个 .DS_Store: {ds[:5]}")
    else:
        a.ok("hygiene.ds_store", "无 .DS_Store")

    abs_hits = []
    for p in (list((ROOT / "data/fission_slices").glob("*/run.json"))
              + list((ROOT / "data/fission_slices").glob("*/contract.json"))
              + list((ROOT / "data/reference_runs").glob("*/run.json"))):
        d = _load(p)
        if d:
            abs_hits.extend((str(p.relative_to(ROOT)), k, v)
                            for k, v in _abs_strings(d))
    if abs_hits:
        a.warn("hygiene.absolute_paths",
               f"{len(abs_hits)} 处绝对路径（新产物应存相对路径）: {abs_hits[:3]}")
    else:
        a.ok("hygiene.absolute_paths", "切片产物无绝对路径")

    models = ROOT / "data/models"
    if models.exists():
        a.warn("hygiene.models",
               f"data/models 是模型缓存（{_size_mb(models)} MB），不属于 data/ 业务数据")
    else:
        a.ok("hygiene.models", "data/models 不存在（缓存已迁出）")
    cache = ROOT / "models" / "whisper"
    if cache.exists():
        a.ok("hygiene.cache", f"whisper cache 位于 models/whisper（{_size_mb(cache)} MB）")
    else:
        a.warn("hygiene.cache", "models/whisper 不存在，ASR 会重新下载")
    tmp = ROOT / "outputs/tmp"
    tmp_mb = _size_mb(tmp) if tmp.exists() else 0
    a.add("PASS" if tmp_mb < 1024 else "WARN", "hygiene.tmp",
          f"outputs/tmp {tmp_mb} MB")
    failed = ROOT / "outputs/failed"
    failed_mb = _size_mb(failed) if failed.exists() else 0
    a.add("PASS" if failed_mb < 500 else "WARN", "hygiene.failed",
          f"outputs/failed {failed_mb} MB")


def main():
    ap = argparse.ArgumentParser(description="项目布局与数据层约束检查")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    audit = Audit()
    check_dirs(audit)
    check_pool_cases(audit)
    check_facets(audit)
    check_indexes(audit)
    check_profiles(audit)
    check_fission_runs(audit)
    check_schemas(audit)
    check_runs(audit)
    check_exports(audit)
    check_review(audit)
    check_hygiene(audit)
    counts = audit.summary()
    if a.json:
        print(json.dumps({"root": str(ROOT), "summary": counts,
                          "rows": audit.rows}, ensure_ascii=False, indent=2))
    else:
        for r in audit.rows:
            print(f"{r['level']:4} {r['code']:28} {r['msg']}")
        print(f"\nPASS={counts['PASS']} WARN={counts['WARN']} "
              f"FAIL={counts['FAIL']}")
    return 1 if counts["FAIL"] or (a.strict and counts["WARN"]) else 0


if __name__ == "__main__":
    sys.exit(main())
