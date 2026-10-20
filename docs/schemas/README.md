# Schema 索引

> 日期：2026-10-20
> 这些 schema 描述产物**必需字段**，不是完整校验器；完整校验由 `scripts/check_layout.py` 与各构建脚本负责。

| 文件 | 版本 | 对应产物 | 写入者 |
|---|---|---|---|
| `fission-facet.v0.schema.json` | `fission-facets/v0` | `data/reference_facets/{ref_id}.json` | `scripts/reference_facets.py` |
| `reference-alignment.v1.schema.json` | `beat-align/v1` | `data/reference_alignments/{ref_id}.json` | `scripts/reference_align.py` |
| `fission-contract.v0.schema.json` | `fission-contract/v0` | `data/fission_slices/{slice_id}/contract.json` | `scripts/fission_slice.py` / 后续契约定向生成 |
| `run.v1.schema.json` | `run/v1` | `data/reference_runs/{run_id}/run.json` | `reference_fission.run_full()` / 迁移脚本 |
| `review-item.v1.schema.json` | `review-item/v1` | `outputs/review/{id}.json` | `store.add_review_item()` |
| `export-manifest.v1.schema.json` | `export-manifest/v1` | `outputs/fission/{run_id}/manifest.json` | 导出步骤 |
| `fission-slices-index.v1.schema.json` | `fission-slices-index/v1` | `data/fission_slices/index.json` | `scripts/build_indexes.py` |
| `plans-index.v1.schema.json` | `plans-index/v1` | `data/plans/plan_index.json` | `scripts/build_indexes.py` |

## 版本规则

- 字段含义变化 → 升版本（`v0 → v1`），不要静默改；
- 新增可选字段 → 可不升版本；
- 删除/重命名必需字段 → 必须升版本，并更新 `check_layout.py`；
- 索引文件永远可重建，不作为事实源。

## 手工校验

```bash
# 只校验 JSON 语法
python3 -m json.tool docs/schemas/fission-contract.v0.schema.json >/dev/null

# 若环境有 jsonschema，可校验产物
.venv/bin/python - <<'PY'
import json, jsonschema
schema = json.load(open("docs/schemas/fission-contract.v0.schema.json"))
data = json.load(open("data/fission_slices/slice-1471-direction1/contract.json"))
jsonschema.validate(data, schema)
print("OK")
PY
```
