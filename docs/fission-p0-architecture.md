# 裂变 P0：商品锚定 + 风格采样

> 日期：2026-10-20
> 目标：不再靠补“口播/文案”提示词解决同质化；把**商品锚定**和**风格生成**拆成两个正交层。

## 1. 为什么不是继续改 prompt

之前 `presentation_lanes` 仍然是固定分类：
- 每条变体要手动挑“口播/手部/静物”；
- adapter 缺字段时回落到真人、手持、客厅、口播；
- 文案缺字段时回落到同一组 `profile.claims`；
- 所以 prompt 改得再细，最后仍会收敛到同一套。

P0 的原则：**anchor 是硬约束，style 是可采样空间；缺字段就失败，不回落默认值。**

## 2. 两个正交层

### ProductAnchor（`pipelines/fission/anchor.py`）

```json
{
  "product_id": "...",
  "identity": "...",
  "references": [
    {"view": "front", "path": "...", "policy": "..."},
    {"view": "back",  "path": "...", "policy": "..."},
    {"view": "inner", "path": "...", "policy": "..."}
  ],
  "must_show": [],
  "must_not_change": [],
  "claim_atoms": [
    {"id": "claim_01", "kind": "claim", "fact": "...",
     "source": "profile.claims", "safe_for_no_person": true}
  ],
  "proof_points": [],
  "forbidden_claims": [],
  "person": {},
  "authorization": "self_owned_test"
}
```

- 商品事实、参考图、必须出现项、禁用主张都是不可变的；
- 风格层只能决定“怎么拍、怎么说”，不能新增/改变商品事实；
- `claim_atoms` 允许文案改写，但不允许文案引入新功效/价格/授权。

### StyleAtlas（`pipelines/fission/style_atlas.py`）

从 29 条 facet 里抽取：

```json
{
  "visual": {
    "person_visibility": "full|partial|hands_only|none",
    "presenter_mode": "direct_speech|voiceover|ambient|text_only",
    "camera": "...", "camera_family": "...",
    "scene": "...", "scene_family": "...",
    "lighting": "...", "pacing": "...", "pacing_bucket": "...",
    "text_style": "...", "text_density": "...",
    "proof_style": "...", "narrative_device": "...",
    "audio_design": "..."
  },
  "copy": {
    "tone": "...", "person": "...", "hook_type": "...",
    "sentence_style": "...", "cta_style": "...", "text_density": "..."
  },
  "visual_signature": {},
  "copy_signature": {},
  "evidence_refs": ["ref-...:shot:1"]
}
```

视觉属性和文案属性分开存储；planner 可以**重组**：视觉来自一条参考，文案来自另一条参考，从而生成池子里没出现过的组合。

### DiversityPlanner（`pipelines/fission/planner.py`）

- 视觉风格和文案风格分别做 **seeded max-min** 采样；
- 距离按人物/声音/机位/场景/节奏/文案 tone/hook/CTA 等轴加权；
- 输出 N 个 `StyleSpec`，并记录 `seed`、`parents`、两两距离；
- 同一个 seed 可复现，不同 seed 自然产生不同批次；
- 商品参考图不支持的风格（例如没有背面图却要求背面证明）会降权。

### CreativeWorld（`pipelines/fission/concept/`）

Style 解决“怎么拍”，但不解决“这条片子为什么值得看”。P0.2 增加一层可插拔的创意世界：

```text
configs/concepts/operators.json   生成算子（invert/ritualize/test/POV/...，不是固定世界分类）
        │
        ├─ proposer.py   高温度 LLM 发散 15+ 个候选 world
        ├─ critic.py     确定性校验：字段完整、claim 合法、proof 覆盖 must_show、批内去重
        ├─ semantic.py   LLM semantic 字段 -> 单批加权语义距离
        └─ selector.py   单批 semantic max-min + cast/operator 覆盖，选 N 个
```

一个 world 是 `premise → tension → device → turn → payoff` 的完整小世界，商品只能通过 `proof_rituals`（可拍动作 + 商品证据 + claim_ids）进入。`person_need` 是 `on_body|hands|any`，由 proof 动作推导，不靠固定模板。

每个 world 还带一个由 LLM 生成的 `semantic` 签名：

```text
social_frame / core_device / core_action /
proof_form / visual_motif / turn_type
```

字段名、权重、阈值和距离算法在 `concept/semantic.py` 固定；具体值由 LLM 生成，
不维护固定世界枚举。selector 用该签名做单批 max-min；audit 再检查 world 和
contract 的语义距离，semantic 不过线时跳过 H3。

这样才能同时满足：
- **商品锚定**：world 不能新增卖点，proof 必须绑定 anchor claim；
- **风格泛化**：world 与 StyleSpec 独立生成，最后做兼容配对（hands world 不配无人物，on_body world 不配纯手部）；
- **可优化/可扩展**：新增算子只改 JSON；替换 critic/selector 不改 composer；
  P0.2 不做跨 run 记忆，分化只依赖当前批次的 semantic 距离。

### Composer（`pipelines/fission/composer.py`）

对每个 StyleSpec 调 LLM 写 beat 计划，然后确定性构建 contract：

- 每个 beat 必须有 `claim_id`，且只能来自 anchor；
- `hands_only/none` 不允许使用需要真人身体的 claim；
- 每条变体会分配不同的 `claim_ids` 窗口，避免 5 条都围绕同一组事实；
- 无口播风格强制 `voiceover=""`，但保留 H3 原生环境音/BGM；
- 文案按 `style.copy` 写，并传入已生成变体的 claim/hook/CTA/voice 作为禁用列表；
- 批量文案编辑（`diversify_copy`）在所有变体生成后统一去重，保留事实和每条风格。

### Audit（`pipelines/fission/audit.py`）

- **Anchor**：非法 claim_id、缺 product evidence、缺商品图；
- **Style**：两两视觉/文案距离、覆盖度、seed/plan；
- **Copy**：hook/CTA 唯一性、跨变体重复句、跨变体重复短语比例（阈值 25%）；
- **Semantic**：world 的 `semantic` 字段加权距离、unique core_device、contract 的 world/action/cast/claim 语义距离；
  semantic 不过线时跳过 H3，保留契约供检查。

2026-10-20 语义冒烟（panty，n=5，seed=7，只出契约）：
`unique_core_devices=5`，world semantic `min_distance=1.0`，
contract semantic `min_distance=0.7672`，`semantic.ok=true`。
本批 world 为“盲捏局 / 抬手闯关 / 退休仪式 / 洗衣袋旅程 / 待产包清单”，
不再出现“只拍腰头/抽屉/胶囊”这类换词复用。

## 3. 流水线

```text
reference_pool ──> materials（增量：descriptions/facets/alignments）
      │
      └─> reference_facets ──> StyleAtlas
                                   │
profile ──> ProductAnchor ─────────┼─> DiversityPlanner(seed, N) ─> N StyleSpec
                                   │
                                   ├─> CreativeWorld proposer/critic/selector ─> N World
                                   │            （world × style 兼容配对）
                                   │
                                   ├─> Composer（LLM beat plan + 确定性 contract）
                                   │
                                   ├─> 批量文案编辑（去重）
                                   │
                                   └─> Audit（anchor/style/copy/concept）
                                         │
                                         └─> data/runs/<run>/vNN/
                                              {contract,prompt_h3,audit}
                                              -> run_contract -> variant_NN.mp4
                                              -> outputs/review
```

## 4. 这次 P0 测试

命令（不调用 H3）：

```bash
.venv/bin/python scripts/fission_p0.py \
  --profile bra-milk-lace --n 5 --seed 42 \
  --out-root data/runs/fission-p0-test
```

产物：

- `anchor.json`：3 个商品视角（front/back/inner）+ 10 个 claim atoms；
- `style_atlas.json`：29 条参考的风格图谱；
- `style_plan.json`：5 条 StyleSpec、seed、parents、两两距离；
- `v01..v05/contract.json`、`prompt_h3.txt`、`prompt_audit.md`；
- `audit.json`、`run.json`。

5 条风格：

| 变体 | 人物 | 声音 | 机位/场景 | 文案 tone |
|---|---|---|---|---|
| v01 | hands_only | voiceover | 桌面俯拍/桌面 | 朋友安利 |
| v02 | partial | direct_speech | 手持/居家 | 痛点否定 |
| v03 | full | direct_speech | 多机位/影棚 | 结构评测 |
| v04 | full | direct_speech | 手持/户外 | 痛点否定 |
| v05 | hands_only | voiceover | 微距/桌面 | 结构评测 |

审计结果：

```text
anchor errors: 0
visual min distance: 0.2857
copy min distance: 0.4286
hooks unique: 5/5
CTAs unique: 5/5
claims unique: 21/21
voiceovers unique: 21/21
text overlays unique: 21/21
cross-variant sentence duplicates: 1（约 0.5%）
```

## 5. P0 初始边界（历史）

> P0.2 已通过 `POST /api/jobs/fission-p0` 接入 H3 和前端；以下保留为 P0 初始阶段的记录。

- P0 初始阶段只生成契约/提示词，不调用 H3；
- StyleAtlas 目前是启发式抽取（人物/声音/机位/场景/文案标签）；下一步可用 LLM 批量标注 + embedding 距离替代启发式。
- P0 初始阶段尚未接入前端；P0.2 已接入 `/#/fission`。
- 文案还有 2 条跨变体重复短语，属于商品结构描述；文案编辑可继续提高阈值，但不应为了去重牺牲商品事实。

## 6. 成片验证（2026-10-20）

5 条视频已用 H3 生成，均为 12 秒 / 768×1344 / 9:16 / 原生音轨 + 硬字幕：

| 变体 | 实际画面 | 商品校验 |
|---|---|---|
| v01 | 桌面手部翻看，无真人 | 9/9/9 pass |
| v02 | 真人开场+手部结构+真人收尾 | 8/8/7 pass（蕾丝/蝴蝶结轻微差异） |
| v03 | 真人试穿+背面/内里特写 | 8/9/8 pass（杯型/排扣轻微差异） |
| v04 | 真人手持+商品特写 | 9/9/9 pass |
| v05 | 微距手部结构展示 | 9/9/9 pass |

入口：

```text
http://127.0.0.1:8800/#/fission?run=fission-p0-test
data/runs/fission-p0-test/v01..v05/variant_*.mp4
```

注意：v03 首镜是真人穿文胸+短裤的试穿画面，比 profile 里“外搭只露肩带/领口”的约束更暴露；如果要严格按品牌尺度，应只重跑 v03 并把 wardrobe 约束写死在 prompt/参考策略里。

## 7. P0.1：覆盖策略与 shot 级风格

P0 的第一次 5 条被池子偏置收敛成“全部有声音、全部高字幕、只有 3 种人物模式”。P0.1 增加：

- `style_atlas.shot_styles`：每个镜头记录人物呈现、机位、场景、是否有字幕；
- `planner._apply_coverage()`：N≥5 时保证覆盖
  - `person_visibility`: full / partial / hands_only / none
  - `presenter_mode`: direct_speech / voiceover / text_only / ambient
  - `text_density`: high / medium / low
  - 至少 3 类 copy tone
- 合成风格标记 `generated_by=coverage_synthesis`，保留 parents/evidence_refs，不伪装成池子里的原参考。

P0.1 契约测试：

```bash
.venv/bin/python scripts/fission_p0.py \
  --profile bra-milk-lace --n 5 --seed 42 \
  --out-root data/runs/fission-p0-coverage-test
```

结果：

| 变体 | 人物 | 声音/字幕 | 字幕密度 | 文案 tone |
|---|---|---|---|---|
| v01 | hands_only | text_only | medium | 朋友安利 |
| v02 | partial | direct_speech | high | 痛点否定 |
| v03 | full | direct_speech | high | 结构评测 |
| v04 | full | voiceover | high | 痛点否定 |
| v05 | none | ambient | low | 价格直给 |

审计：

```text
person_visibility: 4 种
presenter_mode: 4 种
camera_family: 4 种
scene_family: 3 种
copy_tone: 4 种
text_density: high/medium/low
cross-variant sentence duplicates: 0
min visual distance: 0.5714
min copy distance: 0.2857
```

P0.1 的 5 条只有契约，尚未生成视频。

## 8. 第二个商品：无痕纯棉内裤（P0.1 契约测试）

商品来源：`都市丽人服饰内衣旗舰店` 作品 `7684473170019028230` 的商品锚点
（`product_id=3830205932193841627`，价格约 ¥39.9，销量 210）。

Profile：`configs/products/panty-cotton-lace.json`

- 商品图：从账号作品帧提取（`assets/products/panty-cotton-lace*.jpg`）
- `allowed_person_visibility: ["full","partial","hands_only","none"]`，允许真人上身；暴露尺度交给人工审核，不写死“外搭/不露”约束
- 5 条契约：`data/runs/fission-p0-panty-onbody-test/`
- 覆盖：人物 4 种、声音 4 种、机位 4 种、文案 tone 4 种、字幕 high/medium/low
- 全部契约 `ok=True`，0 warning；跨变体重复只剩 2 个商品结构词
- 该 run 未生成视频

| 变体 | 人物 | 声音 | 字幕密度 | 文案 tone |
|---|---|---|---|---|
| v01 | hands_only | text_only | medium | 朋友安利 |
| v02 | partial | direct_speech | high | 痛点否定 |
| v03 | full | direct_speech | high | 结构评测 |
| v04 | full | voiceover | high | 痛点否定 |
| v05 | none | ambient | low | 价格直给 |


## 9. P0.2：CreativeWorld 创意世界（契约测试）

入口：

```bash
.venv/bin/python scripts/fission_p0.py \
  --profile panty-cotton-lace --n 5 --seed 42 \
  --out-root data/runs/fission-p0-concept-test
```

结果（只出契约/prompt，未生成视频）：

| 变体 | CreativeWorld | 人物 | 声音 | 文案 tone |
|---|---|---|---|---|
| v01 | 闺蜜的退货理由清单 | hands_only | text_only | 朋友安利 |
| v02 | 只拍腰头的一句话 | partial | direct_speech | 痛点否定 |
| v03 | 衣柜抽屉的早晨旁白 | hands_only | ambient | 价格直给 |
| v04 | 三条内裤的行李胶囊 | full | direct_speech | 结构评测 |
| v05 | 十A标签的日常巡逻表 | full | voiceover | 痛点否定 |

审计：

```text
concept min_distance: 0.9897
unique titles/premises/devices: 5/5/5
person_visibility: 3 种
presenter_mode: 4 种
camera_family: 4 种
scene_family: 3 种
copy_tone: 4 种
cross-variant sentence duplicates: 1（“10A抗菌面料”，商品事实词）
audit.ok: true
```

人工审核重点：

- v01 的 world 写了“两位闺蜜”，但 hands_only 只保留一双手；叙事靠清单道具和字幕成立；
- v02/v04/v05 允许真人上身，暴露尺度必须人工看 prompt/首帧后再决定，不加硬编码服装约束；
- v03 是 hands_only + ambient，只有环境音/操作音，没有口播；
- world 的“创意是否合适/是否冒犯”不由 critic 判断；critic 只校验字段、claim、proof 和重复。

### 视频生成（历史手工验证）

产品化入口见下一节 `POST /api/jobs/fission-p0`。在它之前，本轮用
`scripts/run_contract.py` 手工提交 H3；保留这段作为可复现的底层层入口：

```bash
.venv/bin/python scripts/run_contract.py \
  --contract data/runs/fission-p0-concept-test/v01/contract.json \
  --prompt data/runs/fission-p0-concept-test/v01/prompt_h3.txt \
  --out data/runs/fission-p0-concept-test/v01 \
  --name variant_01.mp4
```

5 条均为 12s / 768x1344 / 24fps / 带 AAC 音轨；run manifest 已更新为 `status=done`，
视频在 `data/runs/fission-p0-concept-test/vNN/variant_NN.mp4`，审核队列在
`outputs/review/`，每目录另有 `contact_sheet.jpg`。

| 变体 | 视觉结果 | 结论 |
|---|---|---|
| v01 | 三色内裤+退货清单+手部验证，字幕清楚 | 可用；两位闺蜜只以手部关系存在 |
| v02 | 真人腰头一厘米+内裤上身，字幕/口播完整 | 可用；暴露尺度需人工看 |
| v03 | 抽屉内侧 POV，三色内裤、手部选择、环境音 | 可用，world 落地最好 |
| v04 | 收纳袋生成成灰色圆柱物，真人段落变成灰色短裤，商品不可见 | **不可用，需要重跑** |
| v05 | 健身包+PATROL 表+三条内裤装袋，画外口播 | 可用；人物只露手，voiceover 成立 |

v04 的问题不是 contract 审计能发现的，是 H3 把“掌心收纳袋/三条卷装”理解成了灰色圆柱容器，
且第三个 beat 用灰色运动短裤替代了商品内裤。下一轮应把道具写成“透明网纱小袋，袋内三卷颜色可见”，
并在真人 beat 明确“外裤褪到胯部，露出灰色内裤蕾丝腰头与包边”，同时把“圆柱瓶/灰色短裤”加入 negative。

## 10. 产品化 job：POST /api/jobs/fission-p0

P0.2 现在是一个后端 job，不再需要手工逐条提交：

```bash
curl -s -X POST http://127.0.0.1:8800/api/jobs/fission-p0 \
  -H 'Content-Type: application/json' \
  -d '{
    "profile_id": "panty-cotton-lace",
    "n": 5,
    "seed": 42,
    "prepare_materials": true,
    "skip_generate": false
  }'
```

阶段：

```text
materials -> anchor -> style_atlas -> planner -> worlds
          -> contracts -> audit -> generation
```

- `materials`：增量运行 `reference_describe.py` / `reference_facets.py` /
  `reference_align.py`；已有描述/facet 不重复调用视觉模型；
- `generation`：逐条调用 `scripts/run_contract.py`；单条失败不终止整批；
- 每条结果写 `vNN/run.json`（provider_task/review_path），父级写
  `run.json` 的 `generation.variants`；
- `skip_generate=true` 只到契约，顶层 `status=contracts_done`；
- `partial` 表示部分视频成功，可从 `POST /api/fission/runs/{run_id}/resume` 续跑；
- `run.json` 从一开始就落盘，并带 `inputs`，可用于审计和恢复；
- 前端 `/#/fission` 默认使用 P0.2 引擎；Jobs 页可直接打开对应 run；
- 前端暂不暴露“补充文字”；`FissionP0Req.text` 仅保留给 API/内部使用，
  避免默认模板文字干扰 Composer 的软约束。

冒烟验证（n=1，真实 H3）已端到端跑通：job 状态 `done`，generation.v01 有
`provider_task` / `review_path`；为避免污染正式 run 列表，验证产物已清理。

## 11. Harness 封装与移植

稳定入口在 `pipelines/fission/harness/`，输入/输出和端口清单见
[docs/fission-harness.md](fission-harness.md)。

当前是 **facade + 本地适配器**：`FissionHarness` 已接管请求/结果归一化、
`VideoBackend` 注入和 progress；LLM/material/profile 仍是本地实现。
真正跨项目移植前，先把 `LLMProvider` / `MaterialProvider` / `ReviewSink`
从 `composer`、`proposer`、`p0_runner` 中抽成端口。

## 12. P0.2 当前边界

- `fission_p0.py` 默认仍只出契约；`--generate` 或 API job 才会调用 H3；
- 商品目录：店铺 H5/API 当前无法稳定枚举 456 个商品，只有已抓到的内裤/文胸锚点；
- 商城接口 `ec.snssdk.com/shop/goodsList` 返回 `100111`，需要登录态/商品链接才能扩品类；
- `person` 资产授权：当前 `authorization=self_owned_test`，真实投放前必须确认肖像授权；
- P0.2 不读取 `data/worlds/registry.jsonl`，也不写新的 registry 记录；历史文件保留但不再参与生成；
- 生成后的商品/道具/暴露仍需人工审核；当前没有自动重跑 v04 这类视觉失败的阶段。
