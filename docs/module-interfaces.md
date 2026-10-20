# 模块接口契约 v0

> 日期：2026-10-20
> 目标：把“视频池 → brief → guidance → variants → contract → generation → evaluation”解耦。
> 原则：**稳定信封 + 可变 payload**。模块之间只约定信封，不互相规定语义字段。

## 0. 一句话

**Pool 只负责尽可能全面地描述视频；Brief/Guidance/Variant 是下游按商品动态合成的；Contract 只是某一种可执行适配器；Generation 和 Evaluation 不知道 pool 的存在。**

不做的三件事：
- 不把 pool 做成“给人读的打法/playbook”；
- 不固定 brief 字段；
- 不固定 variant 轴（没有“必须有 hook/proof/persona/CTA”这种全局枚举）。

## 1. 模块边界

```text
┌────────────────────┐
│ Pool Module        │  视频 → 多视角全量描述
│ 不知道商品/契约/UGC │  输出只读语料
└─────────┬──────────┘
          │ 只读查询
┌─────────▼──────────┐
│ Brief Module       │  商品图 + 用户文字 → 动态 brief（事实/未知/问题）
│ 不读 pool          │
└─────────┬──────────┘
          │
┌─────────▼──────────┐
│ Guidance Module    │  brief + pool 查询 → 本次指导（临时，不落成通用 playbook）
│ 只读 pool          │
└─────────┬──────────┘
          │
┌─────────▼──────────┐
│ Variant Module     │  brief + guidance → N 个动态变体假设（N/轴都不固定）
│ 语义去重/多样性     │
└─────────┬──────────┘
          │
┌─────────▼──────────┐
│ Contract Module    │  variant + 证据 → 可执行契约（通用 beats/attributes）
│ 适配器解释字段      │
└─────────┬──────────┘
          │
┌─────────▼──────────┐
│ Generation Module  │  prompt + 人物/商品图 → 视频 + 原生音频
│ 不知道 pool/brief   │
└─────────┬──────────┘
          │
┌─────────▼──────────┐
│ Evaluation Module  │  成片 + brief/guidance → 评分/问题
│ 不知道生成实现      │
└────────────────────┘
```

## 2. 通用信封

所有跨模块产物使用同一个外层信封：

```json
{
  "type": "brief",
  "version": "v0",
  "id": "brief-20261020-...",
  "created_at": 1792460000,
  "producer": "brief_synthesizer/v0",
  "payload": {},
  "refs": [],
  "provenance": {}
}
```

规则：
- `type` + `version` 必须存在；
- `payload` 是模块自己的语义，其他模块只读自己认识的字段；
- 新增可选字段不升版本；删除/改义/重命名必须升版本；
- 消费方必须忽略未知字段，不能因为多一个字段报错；
- `refs` 指向证据（pool 的 ref_id/shot、brief_id、variant_id 等），用于审计。

## 3. Pool Module

### 3.1 职责

输入视频，输出**尽可能全面的多视角描述**。不判断下游用途，不选参考，不产出“打法”。

### 3.2 输出信封

```json
{
  "type": "pool.description",
  "version": "v0",
  "id": "pool-ref-1792419234-bd6f",
  "producer": "reference_analysis/v0",
  "payload": {
    "ref_id": "ref-1792419234-bd6f",
    "meta": {},
    "perspectives": {
      "evidence": {},
      "visual": {},
      "roles": {},
      "audio": {},
      "text": {},
      "blueprint": {},
      "extensions": {}
    }
  },
  "refs": ["assets/sources/..."],
  "provenance": {"model": "...", "generated_at": 0}
}
```

### 3.3 最小视角集合（可扩展，不是上限）

| 视角 | 最小内容 |
|---|---|
| `evidence` | 镜头切点、关键帧、ASR、音频统计 |
| `visual` | global + 逐镜：景别/角度/机位/光线/色彩/构图/主体/动作/商品/可见度/画面文字/转场/置信度 |
| `roles` | audience/director/cinematographer/editor/art/sound/marketing/platform/generator，各自 observations/inferences/key_moments/confidence |
| `audio` | 是否有音轨、响度、BGM/环境/口播线索 |
| `text` | 画面文字、ASR 转写、文本样式 |
| `blueprint` | 风格、逐镜 prompt、镜头语言、光线、节奏、字幕风格、negative、invariants/variables、hard/soft constraints、结构、reference_role_map |
| `extensions` | 任意新增视角（运镜幅度、节拍、转场语法、人物姿态、商品证据链……） |

关键：`extensions` 是开放字典。新增视角不需要改 downstream；downstream 自行决定要不要读。

### 3.4 禁止

- 禁止 import brief/guidance/variant/contract/generation/evaluation；
- 禁止在描述阶段按“同品类/同风格/裂变可用”过滤；
- 禁止把 facet 投影当成 pool 的规范；facet 只是某个下游 adapter 的视图；
- 禁止手写“打法/playbook”作为 pool 产物。

## 4. Brief Module

### 4.1 职责

用户只给商品图（+ 少量文字），brief 模块把它变成**动态 brief**：已知事实、未知项、假设、需要问用户的问题、约束。不读 pool。

### 4.2 输出信封

```json
{
  "type": "brief",
  "version": "v0",
  "id": "brief-20261020-...",
  "producer": "brief_synthesizer/v0",
  "payload": {
    "product": {
      "image": "assets/products/...",
      "category_hint": "",
      "observed": {},
      "user_provided": {}
    },
    "facts": [
      {"key": "", "value": "", "source": "user|image_observed|inferred",
       "confidence": 0.0, "note": ""}
    ],
    "unknowns": [
      {"key": "", "why": "", "question": "", "blocking": true}
    ],
    "assumptions": [],
    "constraints": {
      "platform": "",
      "language": "zh",
      "claims_avoid": [],
      "color_policy": "",
      "compliance_notes": []
    },
    "goal": {
      "deliverables": 0,
      "duration_seconds": 0,
      "media": "video",
      "notes": ""
    },
    "open_questions": []
  },
  "refs": [],
  "provenance": {}
}
```

规则：
- 不固定商品字段；`facts` 是列表，key 由 brief 自己决定；
- `source` 必须区分“用户提供/图像观测/推断”；
- `blocking=true` 的 unknown 才向用户提问；不阻塞的可以先假设；
- `goal.deliverables` 由用户/系统动态决定，不固定 5 条。

### 4.3 禁止

- 禁止读 pool 内部结构；
- 禁止把“文胸/内裤”等品类字段写死；
- 禁止把“4 beat/5 变体/固定轴”带进 brief。

## 5. Guidance Module

### 5.1 职责

针对**这一次 brief**，只读查询 pool 语料，合成临时 guidance。不是通用 playbook，不落成“人类打法文档”。

### 5.2 输出信封

```json
{
  "type": "guidance",
  "version": "v0",
  "id": "guid-20261020-...",
  "producer": "guidance_synthesizer/v0",
  "payload": {
    "brief_id": "brief-...",
    "patterns": [
      {
        "name": "自由命名，不来自固定枚举",
        "description": "",
        "why": "",
        "evidence_refs": ["ref-...:shot:3", "ref-...:role:marketing"],
        "confidence": 0.0
      }
    ],
    "candidate_directions": [
      {"hypothesis": "", "rationale": "", "evidence_refs": []}
    ],
    "constraints": [],
    "open_questions": []
  },
  "refs": ["pool-ref-..."],
  "provenance": {}
}
```

规则：
- `patterns` 和 `candidate_directions` 的名称/结构自由，不固定轴；
- 每个 pattern 必须带 `evidence_refs` 或明确标“推断”；
- guidance 是临时的：存到本次 run，不作为全局“打法库”；
- pool 更新后，guidance 应可重建。

### 5.3 禁止

- 禁止写回 pool；
- 禁止把 guidance 固化成全局 playbook；
- 禁止只按“同品类/同风格”检索；可以跨品类看模式，但 claims 必须由 brief/product facts grounding。

## 6. Variant Module

### 6.1 职责

从 brief + guidance 生成 N 个**变体假设**。N 不固定，差异不靠固定轴枚举，而靠语义去重/评估。

### 6.2 输出信封

```json
{
  "type": "variant_set",
  "version": "v0",
  "id": "varset-20261020-...",
  "producer": "variant_generator/v0",
  "payload": {
    "brief_id": "brief-...",
    "guidance_id": "guid-...",
    "variants": [
      {
        "id": "var-...",
        "hypothesis": "",
        "rationale": "",
        "differentiators": ["自由文本，不是固定轴"],
        "plan": {
          "deliverable_type": "video",
          "duration_seconds": 12,
          "assets": [],
          "required_refs": [],
          "dynamic_attributes": {}
        },
        "evidence_refs": [],
        "confidence": 0.0
      }
    ],
    "diversity": {
      "method": "semantic_dedup|llm_judge|embedding",
      "min_pairwise_distance": 0.0,
      "notes": ""
    }
  },
  "refs": ["brief-...", "guid-..."],
  "provenance": {}
}
```

规则：
- `dynamic_attributes` 自由；不同商品可以长出不同维度；
- `differentiators` 是语义描述，不是固定枚举；
- 必须做语义去重：不能 5 条都是“真人痛点+按压+居家+价格”；
- N 由 brief.goal/guidance 决定；没有“固定 5 条”。

### 6.3 禁止

- 禁止把 hook/proof/persona/CTA 写成全局必填枚举；
- 禁止直接读 pool 原始视频；只能通过 guidance/evidence refs；
- 禁止把 variant 写成最终 prompt（那是 contract 的职责）。

## 7. Contract Module

### 7.1 职责

把一个 variant 变成**可执行契约**。通用 contract 只定义 beats/attributes/constraints；具体语义由 adapter 解释（例如 UGC adapter、product_demo adapter）。

### 7.2 输出信封

```json
{
  "type": "contract",
  "version": "v0",
  "id": "contract-...",
  "producer": "contract_writer/v0",
  "payload": {
    "variant_id": "var-...",
    "adapter": "ugc_individual_seller/v0",
    "beats": [
      {
        "index": 1,
        "time": [0, 2.5],
        "attributes": {
          "任意字段": "由 adapter 解释",
          "claim": "",
          "proof": "",
          "text": "",
          "voice": ""
        },
        "constraints": {},
        "evidence_refs": ["ref-...:shot:3"]
      }
    ],
    "global": {},
    "assets": [],
    "validation": {}
  },
  "refs": ["var-...", "guid-..."],
  "provenance": {}
}
```

规则：
- `attributes` 自由；`ugc_individual_seller/v0` adapter 才要求 claim/proof/text/voice/persona/context/CTA；
- 通用 contract 不强制任何 UGC 字段；
- 每个 beat 必须有 evidence 或显式标“目标新增”；
- 校验器按 adapter 执行，不通过不能进 generation。

### 7.3 Adapter

| adapter | 作用 |
|---|---|
| `ugc_individual_seller/v0` | 解释 claim/proof/text/voice/persona/context/CTA，做信息密度预算 |
| `model_seeding/v0` | 解释真人/多色/场景/穿搭 |
| `product_demo/v0` | 解释产品证据/材质/结构，无人物/口播 |
| 自定义 | 未来新增，不改核心 contract |

## 8. Generation Module

### 8.1 请求/结果

```json
{"type":"generation_request","version":"v0","id":"gen-...",
 "payload":{"prompt":"","assets":[{"role":"person","path":""},
 {"role":"product","path":""}],"params":{}}}

{"type":"generation_result","version":"v0","id":"gen-...",
 "payload":{"media":{"video":"","audio":true},
 "provider":{"name":"MiniMax-H3","task_id":""},
 "native_audio":true}}
```

规则：
- 只知道 prompt + assets + params；
- 不知道 pool/brief/guidance；
- 原生音频/后期 TTS 属于 generation 的内部策略，不反向污染 contract。

## 9. Evaluation Module

### 9.1 输出

```json
{"type":"evaluation","version":"v0","id":"eval-...",
 "payload":{"target_id":"gen-...","scores":{},
 "issues":[],"evidence":[],"verdict":""}}
```

核心评分（可扩展）：
- `product_fidelity`：identity/color/detail；
- `brief_coverage`：brief 的事实/约束覆盖；
- `information_density`：信息单元/10s（不是固定轴，按 adapter 解释）；
- `diversity`：与同批其他变体的语义距离；
- `compliance`：功效词/价格/暴露/平台规则。

规则：
- 不读 generation 实现细节；
- 评分必须带 evidence（帧/文本/时间）；
- 只做评估，不改产物。

## 10. 依赖矩阵

| 模块 | 可读 | 可写 | 禁止 |
|---|---|---|---|
| Pool | 视频/证据 | `data/reference_cases` | brief/guidance/variant/contract/generation |
| Brief | 商品图/用户文字 | `data/runs/{run}/brief.json` | pool 内部结构 |
| Guidance | brief + pool 只读查询 | `data/runs/{run}/guidance.json` | 写 pool；全局 playbook |
| Variant | brief + guidance | `data/runs/{run}/variants.json` | pool 原始视频；最终 prompt |
| Contract | variant + evidence | `data/runs/{run}/contract_*.json` | pool 全量；brief 推断过程 |
| Generation | prompt + assets | `outputs/...` | pool/brief/guidance |
| Evaluation | 成片 + brief/guidance | `data/runs/{run}/evaluation.json` | 修改产物 |

## 11. 存储与命名

```text
data/reference_cases/{ref_id}/        # Pool 产物（长期）
data/runs/{run_id}/
  brief.json
  guidance.json
  variants.json
  contract_01.json ...
  evaluation.json
outputs/review/                       # 成片审核
```

ID：
- `ref-...`（pool）
- `brief-...`
- `guid-...`
- `var-...`
- `contract-...`
- `gen-...`
- `run-...`

## 12. 版本与兼容

- 信封 `version` 管结构；payload 内部 schema 由 producer 管理；
- 新增可选字段不升版本；
- 删除/改义/重命名必须升版本；
- consumer 必须忽略未知字段；
- guidance/variant/contract 都是本次 run 的产物，可随 run 归档，不作为全局事实源。

## 13. 最小原型计划

不先写 playbook，不先固定 brief/轴，按这个顺序：

1. **Pool Query**：只读适配器，输入 brief 的自由查询，输出 pool 视角片段 + evidence；
2. **Brief Synthesizer**：商品图 + 用户文字 → 动态 brief（facts/unknowns/questions）；
3. **Guidance Synthesizer**：brief + pool query → 临时 guidance（自由 patterns/evidence）；
4. **Variant Generator**：brief + guidance → N 个动态变体 + 语义去重；
5. **Contract Adapter**：先实现 `ugc_individual_seller/v0`，把 variant 变成 beats/attributes；
6. **Generation**：复用 `run_contract.py`；
7. **Evaluation**：商品 VLM + 信息密度 + 多样性。

先跑文胸商品：商品图 → 动态 brief → guidance → 3 个变体 → 1 个 contract → 不生成视频，先看 brief/guidance/variant 是否合理。

## 14. 开放问题

1. `goal.deliverables` 默认几条？由 brief 推断还是用户设置？
2. 缺失关键事实（价格/授权/功效）时，哪些必须阻塞提问，哪些可以假设？
3. 多样性用什么度量：embedding 距离、LLM judge，还是人工？
4. Pool 的“最小视角”是否要包含运动/节拍/转场语法？当前 extensions 可加，但 guidance 是否默认读？
5. Guidance 是否需要缓存？当前设计是每次 run 临时生成，pool 变了就重建。

## 15. 当前实现映射（P0 重构后）

| 契约模块 | 实现 |
|---|---|
| Pool | `pipelines/fission/pool.py`（digest + 动态锚点目录） |
| Brief | `pipelines/fission/brief.py` |
| Guidance | `pipelines/fission/guidance.py` |
| Variant | `pipelines/fission/variants.py` |
| Adapter | `pipelines/fission/adapters.py`（registry：`ugc_individual_seller`） |
| Contract | `pipelines/fission/contracts.py` |
| Runner | `pipelines/fission/runner.py`（run manifest + resume） |
| 商品配置 | `configs/products/*.json` |
| 兼容入口 | `scripts/ugc_batch.py` 等 |

Run 目录：

```text
data/runs/{run_id}/
  run.json            # schema_version/status/stages/inputs/errors
  pool_digest.json
  brief.json
  guidance.json
  variants.json
  v01/contract.json prompt_h3.txt voiceover.txt subtitles.srt
  v02/...
  evaluation.json
```

`run.json` 是断点恢复的事实源；`--resume` 只重跑未完成的阶段/变体。

