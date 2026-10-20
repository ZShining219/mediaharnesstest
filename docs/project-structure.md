# 项目结构约束 v1

> 日期：2026-10-20
> 目标：把“输入 → 描述 → 派生 → 契约 → 运行 → 审核 → 导出”固定成单向、可追溯、可重建、可清理的结构。
> 检查器：`scripts/check_layout.py`（只读，不移动/删除文件）。

## 0. 当前结论

结构基本健康：

- 29 条参考池 ↔ 29 个案例目录 ↔ 29 份 facet，全部一致；
- 29 份 facet 的 `source_sha256` 与 `descriptions.json` 全部一致；
- 导出目录完整（1 个 run，5 条视频），审核队列 29 对媒体/sidecar 全部配对；
- **Phase 0/1/2 + P0 链路重构已执行**：检查器 **PASS=47 / WARN=1 / FAIL=0**（唯一告警：审核队列体积）。
- 新链路已收进 `pipelines/fission/`，商品配置在 `configs/products/`，回归测试在 `tests/`。

首轮 9 条告警全部清掉，另外完成了 Phase 2：

- whisper 缓存从 `data/models/` 迁到 `models/whisper`；
- 一次性选品文件从 `data/` 根迁到 `data/catalog/`；
- `reference_cases` 索引改为全量重建，不再只写当前批次；
- 6 个无归属旧 plan 归档到 `data/plans/archive/`，2 个有失败任务引用的 plan 标记为 `job_history`。

## 1. 分层与单向数据流

```text
L0  assets/                         只读输入：sources / persons / products /
                                    backgrounds / voices / bgm / garments / characters
      ↓
L1  data/reference_pool.json        人工确认的参考池
    data/material_pool.json         自动采集的候选池（当前为空）
    data/directions.json            内容方向（任务意图）
    data/prompt_templates.json      提示词模板
      ↓
L2  data/reference_cases/{ref_id}/  每条参考的结构化描述
      ↓
L3  data/reference_facets/          派生：裂变 facet
    data/reference_alignments/      派生：beat ↔ 镜头对齐
    data/reference_index/           派生：检索索引
      ↓
L4  data/fission_slices/{slice_id}/ 契约：contract / prompt / audit / diff
    data/plans/pvplan-*.json        DirectorPlan
      ↓
L5  data/reference_runs/{run_id}/   一次裂变的运行记录
      ↓
L6  outputs/review/                 待审核队列
    outputs/approved/               已通过
    outputs/published/              已发布
    outputs/failed/                 失败/废片
      ↓
L7  outputs/fission/{run_id}/       对外导出的不可变快照
```

旁路（运维，不属于业务数据流）：

```text
outputs/tmp/     生成中间文件
logs/            服务日志
work/            手工实验/临时工作区
data/jobs.db     任务状态
models/whisper/  模型缓存（已迁出 data/，git/deploy 排除）
```

## 2. 目录职责与所有权

| 目录/文件 | 层 | 写入者 | 读取者 | 可重建 | 生命周期 |
|---|---|---|---|---|---|
| `assets/sources/` | L0 | 采集脚本 | 描述/裂变 | 否（原始素材） | 永久，不删源 |
| `assets/persons|products|backgrounds|...` | L0 | 人工/采集 | 生成管线 | 否 | 永久 |
| `data/reference_pool.json` | L1 | `reference_pool.py` / UI | 描述、裂变 | 否（人工确认） | 永久 |
| `data/material_pool.json` | L1 | 自动采集 | 备料/选品 | 可重采 | 可清理 |
| `data/directions.json` | L1 | 人工/UI | 编排 | 否 | 永久 |
| `data/prompt_templates.json` | L1 | UI/手工 | 生成 | 否 | 永久 |
| `configs/products/` | L1 | 人工/产品配置 | 裂变链路 | 否 | 永久 |
| `configs/concepts/` | L1 | 人工/研发 | CreativeWorld proposer | 否 | 永久 |
| `data/worlds/registry.jsonl` | L5 | 历史遗留（P0.2 不再读写） | — | 可清空 | 可归档 |
| `data/catalog/` | L1 | 采集/选品脚本 | 选品/复盘 | 可重采 | 可归档 |
| `data/reference_cases/{ref_id}/` | L2 | `reference_analysis` | facet/检索/UI | 是（重跑描述） | 随池 |
| `data/reference_facets/` | L3 | `scripts/reference_facets.py` | 契约/检索 | 是 | 随案例 |
| `data/reference_alignments/` | L3 | `scripts/reference_align.py` | 契约/审计 | 是（需 LLM） | 随案例 |
| `data/reference_index/` | L3 | `reference_retrieval.build_index()` | 检索 | 是 | 随案例 |
| `data/fission_slices/{slice_id}/` | L4 | 切片/契约脚本 | 生成/审核 | 是 | 随实验 |
| `data/fission_slices/index.json` | L3 | `scripts/build_indexes.py` | UI/检查器 | 是 | 随切片 |
| `data/plans/` | L4 | `product_video.plan` | 生成管线/UI | 是 | 可归档 |
| `data/plans/plan_index.json` | L3 | `scripts/build_indexes.py` | UI/检查器 | 是 | 随 plan |
| `data/reference_runs/{run_id}/` | L5 | `reference_fission.run_full()` | 导出/UI | 部分 | 永久（运行记录） |
| `data/runs/{run_id}/` | L5 | `pipelines/fission/p0_runner.py` | 新链路/审计 | 部分 | 永久（含 run.json） |
| `outputs/review/` | L6 | `store.add_review_item()` | UI/审核 | 否（成品） | 30 天或转 approved/failed |
| `outputs/fission/{run_id}/` | L7 | 导出步骤 | 交付/复盘 | 可从 run 重建 | 永久（交付快照） |
| `outputs/tmp/` | 运维 | 生成管线 | 临时 | 是 | 7 天 |
| `models/whisper/` | 运维 | faster-whisper | 描述 | 是（可重下） | 缓存；git/deploy 排除 |
| `pipelines/fission/` | 代码 | 研发 | 链路编排 | — | 随版本 |
| `tests/` | 代码 | 研发/CI | 回归 | — | 随版本 |

## 3. 关键产物契约

| 产物 | 必需字段 | 版本/溯源 |
|---|---|---|
| `reference_pool.json[]` | `id/path/title/note/tags/duration/source_url/created_at` | `id` 唯一 |
| `descriptions.json` | `ref_id/meta/global/shots/roles/blueprint/transcript` | 每条案例独立 |
| `fission_facets/v0` | `schema_version/ref_id/meta/structure/timeline/style/scene/product/text/roles/compliance/slots/provenance` | `provenance.source_sha256` |
| `reference_alignments/*.json` | `ref_id/model/prompt_version/generated_at/source_sha256/alignments/unmatched_*` | 与 facet 同 sha |
| `fission-contract/v0` | `schema_version/slice_id/target/structure.beats[].source/facet_coverage/provenance` | 每 beat 必须有 source |
| `DirectorPlan` | `id/title/intent/meta/shots/constraints/assets` | `id` 唯一，建议带 `run_id` |
| run | `brief/retrieved/template/plans/summary/manifest` + **`run.json` 状态** | `run_id` 唯一，append-only |
| review item | 媒体 + 同名 `.json`（`id/pipeline/status/created_at/prompt/inputs/shots`） | 媒体与 sidecar 必须成对 |
| export | `manifest.json/items/variant_*.mp4/validation_*.json/README.md` | `manifest.run_dir` 指回 run |

## 4. 硬约束

### 数据流

- **C1 单向写入**：下游只读上游。`reference_cases` 只能由描述脚本写；`facets` 只能由 `reference_facets.py` 写；`alignments` 只能由 `reference_align.py` 写；`outputs/review` 只能由 `store.add_review_item()` 写；`outputs/fission` 只能由导出步骤写。
- **C2 派生三件套**：所有派生 JSON 必须带 `schema_version`、`generated_at`、`source_sha256`（或等价 source refs）。源变了但 sha 没变 = 数据错误。
- **C3 索引只读派生**：`index.json` 永远可重建，禁止手改；索引与实际目录不一致时，以目录为准并重建索引。
- **C4 一 ref 一目录**：`data/reference_cases/{ref_id}/` 不允许跨案例写文件；`ref_id` 全局唯一。
- **C5 run append-only**：一次裂变一个 `run_id`；已有 `summary.json/manifest.json` 的 run 不允许覆盖，重跑生成新 `run_id`。
- **C6 导出快照**：`outputs/fission/{run_id}/` 只能从完整 run 导出，导出后不再修改；删除源 run 不得删除导出。
- **C7 审核队列**：`review` 是待审核，不是归档；通过后转 `approved`，失败转 `failed`；媒体与 sidecar 必须同名成对。
- **C8 生命周期**：`outputs/tmp` 7 天、`outputs/failed` 30 天、`review` 30 天或 50 条上限；清理必须先 dry-run。
- **C9 资产只读**：生成管线不得写 `assets/sources|persons|products|backgrounds`；只有采集/人工导入脚本可以写。
- **C10 缓存放 data 之外**：模型、HF cache、whisper cache 不属于业务数据；当前位置 `models/whisper`，禁止再在 `data/` 下创建缓存。
- **C11 相对路径**：交付/契约/run 元数据存相对项目根的路径；绝对路径只允许出现在运行时日志或 `*_abs` 字段。
- **C12 密钥只在 `.env`**：`data/`、`docs/`、`outputs/` 中不得出现 API key、token、cookie。
- **C13 候选池 vs 确认池**：`material_pool.json`（自动采集）与 `reference_pool.json`（人工确认）不得混用；UI 必须标明。
- **C14 命名**：
  - `ref-{epoch}-{4hex}`；
  - `fission-{YYYYMMDD}-{HHMMSS}`；
  - `pvplan-{YYYYMMDD}-{HHMMSS}-{4hex}`；
  - `slice-{ref_short}-direction{n}`；
  - `variant_{nn}.mp4` / `variant_contract.mp4`；
  - sidecar 与媒体同 basename。
- **C15 版本对齐**：schema 变更必须同时更新 `docs/` 与检查器；不允许静默改字段含义。
- **C16 目录卫生**：`data/`、`outputs/` 不出现 `.DS_Store`、临时文件、手工副本。
- **C17 运行状态**：每个 run 必须有 `run.json`，状态至少 `draft/no_generate/generated/exported/failed`。
- **C18 导出可回溯**：`manifest.json` 必须能指回 `run_dir`，并能列出每条 variant 的 plan/validation。

## 5. 当前状态审计（Phase 0/1/2 后）

### 5.1 通过项

| 检查 | 结果 |
|---|---|
| 目录 | 25/25 必需目录存在（含 `configs/products`、`pipelines/fission`、`tests`） |
| 池 ↔ 案例 | 29/29 一致，无缺失/孤儿 |
| 案例 ↔ facet | 29/29 一致 |
| facet 溯源 | 29/29 `source_sha256` 与源描述一致 |
| 索引 | cases=29 / reference=29 / facets=29 / slices=1 / plans=16 |
| plan 归属 | 5 run / 9 review / 2 job_history / 0 unlinked |
| run 状态 | 4/4 `run.json`；complete=1，incomplete=3，status_bad=0 |
| schema | `docs/schemas/` 8 份落盘，检查器校验 6 份核心 |
| 导出 | `fission-20261019-235919` items=5 |
| 审核配对 | 29 对媒体/sidecar 全部配对 |
| 缓存 | `models/whisper` 399.5 MB，git/deploy 均排除 |
| 卫生 | 无 `.DS_Store`；切片产物无绝对路径 |
| 体积 | tmp 287.8 MB；failed 9.1 MB（低于阈值） |

### 5.2 已修复

| # | 原告警 | 处理 |
|---|---|---|
| 1 | `reference_cases/index.json` 陈旧 | `analyze_pool` 改为全量重建；`build_indexes.py --cases` 也可重建 |
| 2 | 3 个 run 无 summary/outputs | 补 `run.json`，状态 `dry_run` |
| 3 | 1 个已完成 run 无状态 | 补 `run.json`，状态 `exported`，含 variant_count/export_manifest |
| 4 | 5 个 `.DS_Store` | 已删除；`.gitignore` 已忽略 |
| 5 | 切片 `run.json` 绝对路径 | `run_contract.py` 改存相对路径；现有 `run.json` 已重写 |
| 6 | `fission_slices` 无索引 | 已生成 `data/fission_slices/index.json` |
| 7 | `plans` 无索引 | 已生成 `data/plans/plan_index.json`，含 run/review/job 归属 |
| 8 | 无机器可读 schema | 已补 `docs/schemas/`（8 份） |
| 9 | 无生命周期清理 | 已补 `scripts/cleanup_outputs.py`（默认 dry-run） |
| 10 | `data/models` 缓存混层 | 已迁到 `models/whisper`；`WHISPER_DIR`、`.gitignore`、部署排除同步更新；`_whisper()` 已验证可从新路径加载 |
| 11 | 一次性选品文件散落 | 已迁到 `data/catalog/` |
| 12 | 6 个旧 plan 无归属 | 归档到 `data/plans/archive/`；2 个有失败任务引用的标记 `job_history` |

### 5.3 剩余告警

- `review.size`：审核队列 53 个媒体 / 363 MB，超过检查阈值；这是已生成裂变视频，不是结构错误。
- `scripts/check_layout.py --strict` 当前仍可运行，结构检查无 FAIL。

### 5.4 生命周期 dry-run

```text
tmp    8 个 / 32.4 MB（>7 天）
failed 0 个 / 0.0 MB（>30 天）
review 0 条 / 0.0 MB（>30 天，且保留最新 50 条）
```

未删除任何文件；需要时执行 `scripts/cleanup_outputs.py --apply`。

## 6. 落地顺序

### Phase 0（已完成）

1. ✅ `docs/project-structure.md` + `scripts/check_layout.py`；
2. ✅ 删除 5 个 `.DS_Store`；
3. ✅ 重建 `data/reference_cases/index.json`（29 条）；
4. ✅ 给 4 个 run 补 `run.json` 状态；
5. ✅ 新产物（切片/契约/run）统一相对路径。

### Phase 1（已完成）

1. ✅ `data/fission_slices/index.json`；
2. ✅ `data/plans/plan_index.json`（含 run/review 归属）；
3. ✅ `docs/schemas/`（facet/alignment/contract/run/review/export/index）；
4. ✅ `scripts/cleanup_outputs.py`（dry-run 优先）。

### Phase 2（已完成）

1. ✅ `data/models/whisper` → `models/whisper`，更新 `reference_analysis.WHISPER_DIR`；
2. ✅ `data/douyin_dushi_*.json` → `data/catalog/`；
3. ✅ `reference_cases` 索引写入改为全量重建（`rebuild_case_index()`）；
4. ✅ 6 个无归属旧 plan 归档到 `data/plans/archive/`；2 个有失败任务引用的保留并标记 `job_history`。

### Phase 3（高风险，非必要不做）

把 `data/reference_*` 物理重命名为 `data/ref/{cases,facets,alignments,...}` 需要同步改所有路径常量；
当前没有收益，不建议做。逻辑分层已经足够，物理路径保持稳定。

## 7. 检查器与索引

```bash
# 布局/数据层检查
.venv/bin/python scripts/check_layout.py
.venv/bin/python scripts/check_layout.py --json
.venv/bin/python scripts/check_layout.py --strict   # warning 也失败

# 重建派生索引
.venv/bin/python scripts/build_indexes.py --all
.venv/bin/python scripts/build_indexes.py --cases
.venv/bin/python scripts/build_indexes.py --slices
.venv/bin/python scripts/build_indexes.py --plans

# 生命周期清理（默认 dry-run）
.venv/bin/python scripts/cleanup_outputs.py
.venv/bin/python scripts/cleanup_outputs.py --apply
```

退出码：`0` = 无 FAIL；`1` = 有 FAIL（`--strict` 时 WARN 也算）。

## 8. 一句话

结构不靠“记得放对地方”，靠 **单向分层 + 版本/溯源字段 + 可重建索引 + 生命周期 + 检查器**。
当前没有断裂，先把 9 条告警按 Phase 0/1 清掉，再考虑缓存与一次性文件的迁移。
