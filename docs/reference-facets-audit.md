# reference facets v0 抽取审计

> 日期：2026-10-20
> 脚本：`scripts/reference_facets.py`
> 产物：`data/reference_facets/{ref_id}.json` + `data/reference_facets/index.json`
> 原则：确定性投影，只搬运已有描述，不重新解读；无法验证的对齐显式标 null。

## 1. 总览

| 指标 | 结果 |
|---|---|
| 案例数 | 29 / 29 |
| 结构审计 | 29 OK / 0 BAD |
| 镜头总数 | 222 |
| 镜头字段完整 | 222 / 222（13 个字段 + time/duration） |
| 有 ASR 转写 | 29 / 29 |
| 每镜都有 blueprint_prompt | 222 / 222 |
| 时长自洽（镜头时长和 vs 视频时长） | 29 / 29（误差 < 1s） |
| beat↔镜头对齐覆盖 | 29 / 29（1 time_overlap + 14 LLM + 14 index_by_count） |
| 索引/对齐引用自洽 | 29 / 29 |

## 2. beat_order ↔ 镜头对齐

| 对齐方式 | 案例数 | 含义 |
|---|---:|---|
| `time_overlap` | 1 | beat 文本含显式时间区间，按时间重叠对齐（高可信） |
| `llm_monotonic` | 14 | LLM 语义对齐，单调、允许一 beat 多镜 / 一镜多 beat；附证据与置信度 |
| `index_by_count` | 14 | beat 数 = 镜头数，按顺序暂对齐；**语义未校验** |
| `none` | 0 | 无 |

14 条 LLM 对齐案例：

`2ae1, 4b03, 654c, f755, 094b, 1471, 15b4, 84e9, 9141, b27a, bd6f, d962, dc99, f290`

5 条文胸案例已全部达到可验证对齐：`32b0`（time_overlap）、`1471/15b4/84e9/b27a`（LLM，0.87–0.94）。

对齐质量：

| 指标 | 结果 |
|---|---|
| 平均置信度 | 0.868 |
| high（≥0.8） | 13 条 |
| medium（0.6–0.8） | 1 条（`2ae1`，0.79） |
| unmatched beat | 0 |
| unmatched shot | 0 |

产物：
- `data/reference_alignments/{ref_id}.json` — LLM 原始对齐 + 每 beat 的 evidence/confidence；
- facet 内 `structure.beat_shot_alignment` — `method/confidence/pairs/unmatched_*/model/prompt_version`；
- `structure.beat_shot_alignment_auto` — 保留对齐前的自动结果，便于回溯。

说明：
- `llm_monotonic` 允许“一个长镜头承载多个连续 beat”，因此 beat 的镜头区间可以重叠；下游应把它当作**证据区间**，不要假设 beat 之间是互斥分片。
- ASR 质量会影响口播型 beat 的对齐（痛点、功能、价格、CTA）。本次 prompt 已把逐镜 transcript 作为证据输入。
- `index_by_count` 仍是 `unverified`；若某条案例要进入正式契约，建议优先用 `time_overlap` 或 `llm_monotonic` 的案例。

## 3. 数据质量备注

1. **`reference_role_map` 结构不统一**：27 条是语义角色（product/scene/hand/text/style 等），2 条是图片槽位（`Image 1`/`Image 2`…）。v0 原样保留，未做归一化。
2. **`index_by_count` 只是暂对齐**：例如 `1471` 的 7 个 beat 与 7 镜数量一致，顺序看起来合理，但未做语义校验；使用时应视为 `unverified`。
3. **`shot_size` / `camera` 是原描述的枚举值**（如 `close_up`、`static`），未翻译成自然语言；下游渲染时需要一层词典。
4. **`on_screen_text` 是逐镜 OCR 读数**，含 ASR 误差；`transcript` 也保留原始转写，未清洗。
5. **v0 没有新增字段**：scene props、hand pose、must_show 等需要进一步结构化的槽位，暂未从描述中推导，避免制造不可回溯的信息。
6. **LLM 对齐不是人工金标**：每 beat 都有 evidence 和 confidence，低置信项（如 `2ae1` 的痛点 beat）在使用前应人工抽查。

## 4. 每个 facet 文件的结构

```text
meta            标题/品类/category_key/tags/时长/来源/镜头数/beat 数
structure       hook / beat_order / beats(对齐行) / proof / cta /
                beat_shot_alignment(method/confidence/pairs/unmatched/evidence) /
                beat_shot_alignment_auto(对齐前自动结果)
timeline[]      逐镜：time/duration/景别/角度/机位/光影/色彩/构图/主体/动作/
                商品/可见度/画面文字/转场/置信度/blueprint_prompt
style           visual_style / global_style / pacing / camera_language /
                lighting / color_palette / on_screen_text_style
scene           场景描述 + reference_role_map.scene
product         商品描述 + reference + 逐镜商品/可见度
text            文本策略 + 逐镜画面文字 + ASR + reference
roles           9 个角色视角原样保留
compliance      platform 角色的观察/推断/关键时刻
slots           invariants / variables / hard_constraints / soft_constraints /
                negative / reference_role_map
provenance      源文件路径 + descriptions.json 的 sha256 + 生成时间
```

## 5. 命令

```bash
# 重新抽取全部
.venv/bin/python scripts/reference_facets.py

# 只抽指定案例
.venv/bin/python scripts/reference_facets.py --refs ref-1792419234-1471,ref-1792419234-32b0

# 只审计，不重建
.venv/bin/python scripts/reference_facets.py --check

# 对未对齐案例做 LLM beat→镜头对齐（默认只做 alignment_method=none）
.venv/bin/python scripts/reference_align.py

# 指定案例 / 重做 / 同时重做 index_by_count
.venv/bin/python scripts/reference_align.py --refs ref-xxx,ref-yyy
.venv/bin/python scripts/reference_align.py --refs ref-xxx --force
.venv/bin/python scripts/reference_align.py --include-unverified
```

说明：`reference_facets.py` 重建时，如果 `descriptions.json` 的 sha256 未变，
会保留已有的 `llm_monotonic` 对齐，不会覆盖 `reference_align.py` 的结果。
