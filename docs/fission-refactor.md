# 裂变链路 P0 重构

> 日期：2026-10-20
> 目标：把“文胸专用的端到端脚本”收成“换商品/换池子不改核心代码的链路”。

## 1. 重构前的问题

- `contract_gen.py` 写死文胸：`PRODUCT_REF`、`PERSON`、`MUST_SHOW`、`MUST_NOT_CHANGE`、默认 claims。
- `variant_gen.py` 写死 5 个 primary_ref 锚点。
- `ugc_batch.py` 顺序跑，失败即停；没有 run manifest / resume。
- 旧脚本各自实现一套逻辑，和包内实现重复。

## 2. 重构后的结构

```text
pipelines/fission/
  __init__.py
  io.py           # JSON / envelope / 轻量校验
  profiles.py     # 商品 profile 加载与校验
  pool.py         # 全池 digest + 动态锚点目录
  brief.py        # 商品图 + profile -> brief
  guidance.py     # brief + 全池 -> guidance
  variants.py     # brief + guidance + 动态锚点 -> variants
  adapters.py     # adapter registry + ugc_individual_seller
  contracts.py    # variant -> contract/prompt/voice/srt
  runner.py       # 编排 + run manifest + resume

configs/products/
  bra-milk-lace.json
  README.md

tests/
  test_fission_refactor.py
```

## 3. 商品配置外置

`configs/products/bra-milk-lace.json` 提供：

- 商品图、品类、身份、must_show/must_not_change；
- claims/proofs；
- person（图/身份/策略/授权状态）；
- color_policy、offer、platform/compliance；
- default_archetype、reference_id。

`contract_gen` 不再出现文胸常量；换商品只换 profile（+ 商品图/人物图）。

## 4. 动态锚点

`pool.build_digest()` 为每条 ref 生成：

```json
"anchor": {"beats":[1,2,...], "shots":[1,2,...],
           "beat_count":6, "shot_count":8}
```

`variants.py` 把**全部池子**的锚点目录交给 LLM，不再限制 5 个 ref。
`contracts.py` 校验 `primary_ref` 与 `source_beats/source_shots`，不合法时回退到 facet 的第一组有效索引。

## 5. Adapter registry

```python
ADAPTERS = {
  "ugc_individual_seller": UGCIndividualSellerAdapter(),
}
```

- 通用 contract 只要求 beats/attributes/constraints；
- UGC adapter 解释 claim/proof/text/voice/persona/context/CTA；
- 未来加 `model_seeding/v0`、`product_demo/v0` 不改核心 runner。

## 6. Run manifest + resume

每次 run 写 `data/runs/{run_id}/run.json`：

```json
{
  "schema_version": "fission-run/v1",
  "status": "running|contracts_done|done|partial|failed",
  "stages": {
    "pool": {"status": "done"},
    "brief": {"status": "done"},
    "guidance": {"status": "done"},
    "variants": {"status": "done"},
    "contracts": {"status": "done"},
    "generation": {"status": "running", "variants": {...}},
    "evaluation": {"status": "pending"}
  },
  "inputs": {},
  "errors": []
}
```

`--resume` 只重跑未完成/失败的阶段和变体；已经生成的视频不会重复扣 H3。

## 7. 入口

```bash
# 只到契约，不生成视频
.venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --n 3 --skip-generate

# 完整生成 3 条
.venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --n 3

# 从已有 run 继续
.venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --resume \
  --out-root data/runs/fission-bra-milk-lace-...
```

兼容旧参数：`--product-image`、`--person-image`、`--text`、`--out-root` 仍可用。

网页入口：`#/fission`（工作台 → 裂变素材）。

- 左侧选商品 Profile、商品图/人物图、数量，可勾选“只生成契约”；
- 右侧显示运行记录、7 个阶段状态、变体视频与商品校验；
- 提交走 `POST /api/jobs/fission`，列表/详情走 `/api/fission/runs`，续跑走 `/api/fission/runs/{run_id}/resume`；
- 页面不提供参考视频选择：视频池只作为后台整体指导。

## 7.1 呈现车道（v1.1）

P0 版本虽然让 LLM “自由生成变体”，但 adapter 仍把每条都强制成：

- 真人女主播；
- 手机竖屏手持；
- 居家客厅/卧室；
- 每个 beat 都有口播；
- negative 里写“不要无人物”。

结果就是：变体只换了开头和卖点顺序，观感仍是同一种口播讲解。v1.1 改为显式车道：

```text
guidance.presentation_lanes[]
  name / summary
  person_visibility: full | partial | hands_only | none
  presenter_mode:   direct_speech | voiceover | ambient | text_only
  camera_language / scene / lighting / proof_style
  narrative_device / audio_design / text_style / pacing
        ↓ select_lanes() 贪心覆盖不同人物/声音/机位/场景
variants[].format_profile   # 每个变体锁定一条车道
        ↓ adapter
contract.target.format.presentation
        ↓
H3 prompt / 人物参考图 / 口播文件 / 字幕 / 原生音频策略
```

adapter 的关键变化：

- `full/partial` 才提交人物参考图；`hands_only/none` 只提交商品图；
- `voiceover=false` 时不写 `voiceover.txt`，但仍保留 H3 原生环境音/BGM；
- `subtitles` 从 `text_overlay` 生成 SRT，支持“无口播、只字幕”；
- 场景/机位/光线/节奏从车道读取，不再固定“居家客厅 + 手机手持”；
- negative 不再统一写“不要无人物”；
- 侧身/背影车道额外提交商品背面参考图，并强制首镜正面近景定帧，避免商品被拍成光面基础款。

实测 `data/runs/fission-diversity-test/`（4 条，全部商品校验 pass）：

| 变体 | 车道 | 人物 | 声音 | 商品校验 |
|---|---|---|---|---|
| v01 | 正面口播 | full | direct_speech | 8/9/8 pass |
| v02 | 侧身/背影 | partial | voiceover | 8/8/7 pass |
| v03 | 纯手部字幕卡 | hands_only | text_only | 9/9/9 pass |
| v04 | 桌面静物 | none | ambient | 9/9/9 pass |

## 7.2 P0 商品锚定 + 风格采样（新引擎）

旧 lane 引擎仍是“固定分类 + adapter 默认值”，P0 已另起一条正交链路：

```text
anchor.py       ProductAnchor：商品事实/多视角参考/claim atoms
style_atlas.py  reference_facets -> visual/copy 风格属性 + 距离
planner.py      seeded max-min 采样视觉风格与文案风格
composer.py     anchor × style -> contract/prompt；批量文案去重
audit.py        anchor / style / copy / concept 审计
concept/        CreativeWorld：proposer/critic/selector/semantic/operators
materials.py    增量素材解读：descriptions/facets/alignments
p0_runner.py    anchor -> style -> world -> contract -> audit -> H3（可选）
```

入口：

```bash
# 只出契约
.venv/bin/python scripts/fission_p0.py --profile bra-milk-lace --n 5 --seed 42

# 产品化 job（素材解读 + 契约 + H3）
curl -s -X POST http://127.0.0.1:8800/api/jobs/fission-p0 \
  -H 'Content-Type: application/json' \
  -d '{"profile_id":"panty-cotton-lace","n":5,"seed":42}'
```

完整设计与测试结果见 `docs/fission-p0-architecture.md`。当前前端 `/#/fission` 默认 P0.2；
旧 lane 入口保留用于已验收视频。

## 8. 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

覆盖：
- profile 加载与路径存在；
- envelope 校验；
- 29 条 pool digest + anchor；
- UGC adapter 契约构建 + `reference_contract` 校验；
- primary_ref fallback。

## 9. 当前边界

- 只注册了 `ugc_individual_seller` adapter；
- variant/world 多样性使用单批 semantic 签名距离 + 确定性 audit；不做跨 run 记忆；
- brief/guidance/variant 还没有完整 JSON Schema 强制校验；
- H3 生成仍是顺序执行，没有并发/成本上限；
- 旧的 `scripts/pool_query.py` 等现在是兼容入口，主逻辑在 `pipelines/fission/`。

## 10. 本次跑通结果

命令：

```bash
# 1) 只到契约
.venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --n 3 \
  --skip-generate --out-root data/runs/fission-bra-refactor-test

# 2) 从同一 run 继续生成
.venv/bin/python scripts/ugc_batch.py --profile bra-milk-lace --resume \
  --out-root data/runs/fission-bra-refactor-test
```

结果：

| 项 | 结果 |
|---|---|
| run.json | `status=done`，7 个阶段全部 done |
| 契约 | 3/3 valid，0 warning |
| 主参考 | v01 1471 / v02 32b0 / v03 1471（动态锚点自动选择） |
| 视频 | 3 条 12s / 768×1344 / H3 原生音频 |
| 商品校验 | v01 8/9/8；v02 8/8/7；v03 9/9/9，全部 pass |
| 审核 | `outputs/review/variant_01_1f3440.mp4` 等（同名自动加后缀） |
| 测试 | `8/8 OK`（含无人物车道、车道选择） |
| 布局检查 | `PASS=48 WARN=0 FAIL=0` |

`--resume` 验证：
- 第一次 `--skip-generate` 只生成到契约；
- 第二次 `--resume` 跳过 pool/brief/guidance/variants/contracts，只执行 generation/evaluation；
- 未重复生成已完成的变体。

当前 minor issues：
- v01：蕾丝细节略简化、手持时杯型轻微变形；
- v02：运动模糊导致蕾丝/金边细节略丢失；
- v03：模特穿开衫展示，但商品完整可见，不影响判定。

