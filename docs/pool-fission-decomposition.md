# 素材池 → 裂变提示词：对标拆解

> 日期：2026-10-20
> 对象：`data/reference_pool.json`（29 条）+ `data/reference_cases/*`（描述）
> 裂变案例：`data/reference_runs/fission-20261019-235919/`、`outputs/fission/fission-20261019-235919/`
> 结论先行：**对标不上是结构性的**。素材池的描述层有 6 层、约 40 个字段；最终进入 H3 提示词的只有“手写商品描述 + 5 个方向名 + 固定 4 镜模块”。中间没有字段级的选择、回填和谱系。

---

## 1. 素材池拆解

### 1.1 语料构成

| 项 | 数值 |
|---|---|
| 参考池 | `data/reference_pool.json`，29 条 |
| 品类 | 文胸 5 条 / 内裤 24 条 |
| 时长 | 12.1–55.3 秒，中位数约 40 秒 |
| 镜头数 | 每条 3–8 镜，多数 8 镜 |
| 描述完整度 | 29/29 都有 global + shots + 9 角色 + H3 蓝图 |
| 每案例产物 | `evidence.json`、`descriptions.json`、`prompt_blueprint.json/.md`、`frames/` |
| 检索索引 | 628 个 facet 文档（`data/reference_index/documents.jsonl`） |

注意：`data/material_pool.json` 是另一个“自动采集备料池”，当前为空；本次讨论的素材池实际是 `reference_pool.json` + `reference_cases/`，两套命名不要混。

5 条文胸案例（本次裂变目标品类）：

| ref_id | 时长 | 镜头 | 备注 |
|---|---:|---:|---|
| ref-1792419234-32b0 | 12.1s | 3 | 背心式无钢圈，短时长 |
| ref-1792419234-15b4 | 53.1s | 4 | 桑蚕丝，甜点架场景 |
| ref-1792419234-b27a | 28.9s | 8 | 蕾丝，梦幻 CG 开场 |
| **ref-1792419234-1471** | **42.5s** | **7** | **本次商品帧来源** |
| ref-1792419234-84e9 | 28.1s | 8 | 官方旗舰店 |

### 1.2 描述层拆解（6 层）

| 层 | 字段 | 信息用途 | 进入检索？ | 进入最终提示词？ |
|---|---|---|---|---|
| L0 `evidence` | 镜头切点、关键帧、ASR、音量 | 证据 | 否（转写除外） | 否 |
| L1 `meta` | id/title/note/tags/source_url/duration | 过滤、元数据 | 仅 metadata | 否 |
| L2 `global` | category/scene/visual_style/lighting/color_palette/pacing/camera_language/on_screen_text_style/product | 整条视频判断 | 压成 1 个 doc | 否 |
| L2 `shots[]` | shot_size/angle/camera/lighting/color/composition/subject/action/product/product_visibility/on_screen_text/transition/confidence + start/end | 逐镜视觉事实 | 每镜 1 个 doc | 否 |
| L2 `roles{}` | audience/director/cinematographer/editor/art/sound/marketing/platform/generator × observations/inferences/key_moments/confidence | 多角色观察与推断 | 每角色 1 个 doc | 否 |
| L2 `blueprint` | global_style/shot_prompts/camera_language/lighting/pacing/on_screen_text_style/negative/invariants/variables/hard_constraints/soft_constraints/reference_role_map/structure | 可迁移提示词蓝图 | 只摊平为 style/structure/shot_prompts 3 个 doc | 否 |
| ASR `transcript` | 逐句转写 | 口播/文案 | 1 个 doc | 否 |

关键点：素材池的“完备描述”其实分成两类信息——
- **事实/风格描述**（scene、lighting、color、camera、composition 等），是“这条片子长什么样”；
- **可迁移结构**（blueprint.structure 的 hook/beat_order/proof/cta，加上 invariants/variables/soft_constraints），是“下一条怎么拍”。

当前链路只把前者当检索语料，后者没有被当成结构化契约使用。

### 1.3 可对标维度清单（建议的“槽位”视角）

把 29 条案例的描述按“裂变时可能需要复用”的维度重分组：

| 槽位 | 素材池来源 | 裂变时的用途 |
|---|---|---|
| A 叙事结构 | `blueprint.structure`：hook / beat_order / proof / cta | 决定本条的方向、节拍顺序 |
| B 镜头语法 | `shots[].shot_size/angle/camera/transition/composition` | 决定每镜景别、机位、转场 |
| C 光影色彩 | `global.lighting/color_palette` + `shots[].lighting/color` | 决定布光与色调 |
| D 场景道具 | `global.scene`、`reference_role_map.scene`、`composition` | 决定背景与道具 |
| E 商品证据 | `shots[].product/product_visibility`、blueprint 硬约束 | 决定每镜必须露出什么 |
| F 人物/手部 | `shots[].subject/action`、roles.director/cinematographer | 决定手部动作与人物出现方式 |
| G 字幕/口播 | `on_screen_text`、`on_screen_text_style`、`transcript` | 决定字幕策略、文案节奏 |
| H 平台/合规 | `roles.platform`、`hard_constraints` | 决定禁用词、安全区 |
| I 节奏/时长 | `duration`、`pacing`、`shots[].start/end` | 决定总时长与每镜时长 |
| J 可替换槽位 | `variables`、`invariants`、`soft_constraints` | 决定哪些必须保留、哪些可以换 |

### 1.4 单案例样本：ref-1471（本次商品来源）

- 全局：室内暖光布景，纱帘 + 橙色花艺 + 木质台面；固定机位、浅景深、手部托举；**缓慢**，7 镜约 6 秒/镜；白色描边黑体字幕。
- 结构：痛点否定 → 无钢圈调整型 → 舒适聚拢 → 肩带加宽 → 四排扣背面 → 内里软支撑 → 促销 CTA。
- 逐镜：正面托举 → 调整角度 → 倾斜展示 → 捏肩带 → 翻背面四排扣 → 翻开内里 → 捏侧边细节。
- 商品：米白蕾丝无钢圈调整型文胸，金色包边、前中蝴蝶结、宽肩带、四排扣、内里软支撑。

这里已经有一个明显冲突：**参考案例是 7×6 秒的慢节奏口播片，裂变产物却是 12 秒 4×3 秒的快节奏无口播片**。参考的节奏/时长槽位（I）在解码时被整体替换，且没有任何“为什么替换、替换成什么”的记录。

---

## 2. 已有裂变案例拆解

### 2.1 链路与产物

```
手写 query + 手写 PRODUCT_DESC
  → reference_retrieval.retrieve()        # BM25 top-12
  → generalize()                          # LLM 归纳成 template
  → make_variant_briefs()                 # LLM 生成 5 个方向
  → build_controlled_plan()               # 每个方向固定 4 镜
  → compile_video()                       # 渲染整条 H3 prompt
  → MiniMax H3 生成
  → validate_output()                     # 只校验商品身份/颜色/细节
```

产物分工：

| 文件 | 内容 |
|---|---|
| `brief.json` | query、商品帧、12 个检索 doc、template |
| `template.json` | 8 invariants / 8 variables / 7 hard / 7 soft / 3 structure_options / 8 evidence_refs |
| `plans.json` | 5 个 DirectorPlan；每个 plan 里存了 `fission_variant` 和 `fission_template` |
| review item JSON | 最终 H3 prompt 全文（`outputs/review/*.json`） |
| `manifest.json` / `validation_*.json` | 5 条视频 + 商品校验分 |

### 2.2 5 个方向：意图 vs 实际落镜

每个方向都声明了 5 个 beat，但 `_controlled_shots()` 只会生成 4 个固定模块（hook/material/structure/end），并通过关键词把 beat_order 折叠进去（`reference_fission.py:263`、`:288`）。结果：

| 方向 | 方向声明的 beat_order（5 个） | 实际 4 镜顺序 | 主要丢失 |
|---|---|---|---|
| 一 指尖倒计时 | 正面点蝴蝶结 → 侧面肩带 → 背面四排扣 → 内里按压 → 回正面 | 结构证明 → 材质特写 → **视觉钩子（第3镜）** → 结尾 | 前两个 beat 被并掉；“钩子”被推到 6–9 秒 |
| 二 单镜连续翻转 | 背面起幅 → 侧面金边 → 正面 → 内里 → 回正面 | 结构证明 → 材质特写 → **视觉钩子（第3镜）** → 结尾 | “一镜到底”没有体现，仍是 4 次硬切 |
| 三 材质微距 | 微距按压 → 拉远金边 → 中景翻转 → 内里微距 → 全景 | 材质特写 → 结构证明 → **视觉钩子（第3镜）** → 结尾 | 微距/拉远/全景的递进关系丢失 |
| 四 双手对照 | 双手对折 → 展开正面 → 单手翻转背面 → 双手翻开内里 → 托举收束 | 结构证明 → 材质特写 → **视觉钩子（第3镜）** → 结尾 | “左右互证/对照”全部丢失 |
| 五 暗背景聚光 | 聚光正面 → 侧光扫金边 → 聚光四排扣 → 侧光内里 → 正面收束 | 材质特写 → 结构证明 → **视觉钩子（第3镜）** → 结尾 | 暗背景只作用于第 3 镜，其余三镜仍是均匀柔光 |

共性：
1. **所有 5 条都把 hook 放在第 3 镜（6–9 秒）**，与“0–1 秒钩子”“第 1 镜 1 秒内出现商品”的意图直接冲突。
2. 5 个 beat 被压成 4 个模块，模块动作是通用文案，不是方向里的具体动作。
3. 方向的 camera/lighting 只作用于 `hook` 模块；material/structure/end 用硬编码的机位与布光。
4. 方向的差异最后只剩“第 3 镜的一句钩子描述 + 标题/创作意图”，第 1、2、4 镜五条几乎同构。

### 2.3 最终 H3 提示词解剖（以方向一为例）

最终 prompt 的段落与来源：

| 段落 | 内容来源 | 是否来自素材池 |
|---|---|---|
| 【主体定义】 | `PRODUCT_DESC`（`reference_fission.py:29`，手写） | 否 |
| 【创作意图】 | variant 的 name/concept/hook + 手写 visual_language | 间接（template 曾作为 LLM 上下文） |
| 【全局合同】 | plan.meta / 手写“明亮商业产品广告” | 否 |
| 【保留审计】 | `_product_only_retention()` 手写 | 否 |
| 【硬约束】 | `HARD_CONSTRAINTS`（`:37`，手写） | 否 |
| 【逻辑分镜时间轴】 | `_controlled_shots()` 的 4 个固定模块 | 否 |
| 【负面约束】 | 手写列表 | 否 |

template 的 8 invariants、7 soft_constraints、3 structure_options、8 evidence_refs **没有任何一项被逐字段渲染进 prompt**；`plan["fission_template"]` 只是整块存进了 plan JSON，下游 `render_video()` 不读它。

每镜实际渲染的字段：`shot_function / camera / lighting / product_action / start_state / end_state / product_evidence / cut_to_next`。
未渲染的素材池字段：`shot_size / angle / color / composition / subject / product_visibility / on_screen_text / confidence`，以及全部 roles 视角、transcript、reference_role_map、negative/invariants/variables。

### 2.4 校验层拆解

`validate_output()` 只做商品硬约束校验（product_present / identity / color / detail），5 条全部 pass；其中方向二的 issues 是“运动模糊、细节被遮挡”，仍判 pass。**校验不检查方向是否执行、hook 是否在前 3 秒、beat 顺序是否成立**。所以“5 条全过”不等于“5 个方向都对标”。

---

## 3. 对标断点表

| # | 维度 | 素材池来源 | 期望去向 | 实际去向 | 结果 |
|---|---|---|---|---|---|
| 1 | 品类过滤 | `meta.tags`（文胸/内裤） | 检索时硬过滤 | 只用 query 做 BM25，无 category filter | top-12 混入大量内裤案例；`evidence_refs` 8 条里 42c0/f290 等是内裤 |
| 2 | 结构选择 | `template.structure_options`（3 个） | variant 必须选一个并记录 | `make_variant_briefs` 只把 template 当上下文，输出 schema 没有 `structure_choice` | 3 个结构选项无人认领 |
| 3 | beat 顺序 | variant.beat_order（5 个） | 逐 beat 落成分镜 | `_order_from_beat_order` 关键词折叠成 4 模块 | 5→4；hook 被推到第 3 镜；无关键词的 beat 直接丢 |
| 4 | 镜头语法 | `shots[].shot_size/angle/camera/composition` | 每镜景别/机位/构图 | 只保留 4 个模块的固定 camera 字符串 | shot_size/angle/composition 全丢 |
| 5 | 光影色彩 | `global.lighting/color_palette` + `shots[].lighting/color` | 每镜布光、整体色调 | 只有 hook 镜用 variant lighting，其余硬编码 | 方向五的“暗背景聚光”只影响 1/4 画面 |
| 6 | 场景道具 | `global.scene`、`reference_role_map.scene` | 场景/道具槽位 | 完全不进 prompt（产品-only 白台面） | 参考场景信息 0 使用 |
| 7 | 商品证据 | `shots[].product/product_visibility`、blueprint.hard_constraints | 每个 beat 指定证据 | 手写 `PRODUCT_EVIDENCE` 列表，按模块轮转 | 证据有，但与参考镜头无对应关系 |
| 8 | 手部/人物 | `shots[].subject/action`、roles.director | 具体手部动作 | 固定“无人物，仅手部入画” | 方向里的“手指点扣/双手对折”等动作丢失 |
| 9 | 字幕/口播 | `on_screen_text`、`transcript`、`on_screen_text_style` | 文本策略 | 硬编码“无字幕、无口播” | 与参考案例（有字幕有口播）相反；template.soft 里的 CTA 字幕也冲突 |
| 10 | 节奏/时长 | `duration`、`pacing`、`shots[].start/end` | 时长分配规则 | 固定 4×3 秒 | 参考 7×6 秒慢节奏 → 12 秒快节奏，无映射说明 |
| 11 | 合规 | `roles.platform`、`hard_constraints` | 禁用词/安全区 | 只有“无 logo/无字幕”等，功效词约束未渲染 | template 的“抗菌/聚拢”合规约束没有进入 prompt |
| 12 | 谱系 | `evidence_refs` | 每个槽位标注来源 ref_id | 只有 plan 级别的整块 `fission_template` | 无法回答“这句提示词来自哪条案例的哪个字段” |

---

## 4. 根因

1. **检索粒度不对**：`flatten_case()` 把 6 层描述压成 22 个纯文本 doc，role/platform、shot 视觉、blueprint 结构混在一个 BM25 池里；查询没有品类和 facet 类型的硬过滤。对“文胸结构裂变”最该命中的 `blueprint.structure` 和 `shots`，反而不如 platform 角色文档分高。
2. **泛化产物不是契约**：`generalize()` 输出的是自然语言数组（invariants / soft_constraints / structure_options），没有槽位、没有时长、没有每 beat 的镜头/光影/商品证据字段，也没有“选哪个结构”的决策字段。下游无法逐字段消费，只能当“参考建议”看。
3. **解码器覆盖了参考**：`make_variant_briefs()` 让 LLM 重新发明 5 个方向；`build_controlled_plan()` 完全不读 template 内容；`_controlled_shots()` 再用 4 个固定模块覆盖 variant 的 5 个 beat。最终 prompt 的商品描述、硬约束、证据列表也全是手写常量。素材池在这条链路里只影响“方向文案”，不影响“分镜执行”。
4. **没有产物谱系与结构校验**：prompt / shot / beat 都不带 `ref_id + facet` 来源；校验只看商品是否变形变色，无法发现“方向一的一镜到底变成了四镜硬切”。

---

## 5. 下一步建议（先不动代码）

要“对标下来”，需要把现在的“描述池 → 自由创作”改成“描述池 → 槽位契约 → 逐槽位回填”。最小闭环：

1. **给每条案例抽一份 `fission_facets.json`**（机器可读，不替代现有描述）：
   ```json
   {
     "ref_id": "ref-1792419234-1471",
     "structure": {
       "hook": {"type": "痛点否定", "text": "不要再穿钢圈", "time": [0,3]},
       "beats": [
         {"function": "产品正面", "time": [0,6], "shot_size": "close_up",
          "camera": "固定平视略俯", "lighting": "暖黄柔光",
          "composition": "双手托举居中", "action": "双手调整角度",
          "product_evidence": ["正面蕾丝", "金色包边", "蝴蝶结"]}
       ],
       "proof": "...", "cta": "..."
     },
     "style": {"pacing": "缓慢", "color": ["米白","暖橙","浅金"]},
     "scene_kit": ["纱帘", "橙色花艺", "木质台面"],
     "text_policy": {"subtitles": "白色描边黑体", "position": "居中偏下"},
     "compliance": ["避免抗菌/聚拢等功效词，除非有依据"],
     "slots": {"invariants": [], "variables": []}
   }
   ```
2. **裂变 brief 改成显式选择**：每个方向必须写
   `basis: [{ref_id, facet, 用途}]` + `structure_choice` + `beats[]`（每 beat 带时长、景别、机位、光影、动作、商品证据、文本策略）。没有来源的槽位要么显式标 “free”，要么拒绝生成。
3. **编译器 1:1 渲染 beats**：禁止 `_order_from_beat_order` 这类关键词折叠；beat 数 = 分镜数，hook 必须在 time[0]=0。4 镜不是常量，而是结构选择的结果。
4. **检索加两道硬过滤**：`category`（文胸/内裤）+ `facet_type`（structure/shot/style），并强制 top-k 里至少 N 条来自 `blueprint.structure`；同时把 `evidence_refs` 限制在同品类。
5. **校验加结构项**：除了商品 identity/color/detail，再校验 hook 首帧、beat 数、每镜商品证据、方向专属动作是否出现；并输出 `facet_coverage`（哪些槽位用了哪条参考，哪些显式放弃）。

---

## 6. 一句话总结

素材池不是不够全，而是**“全”停在了描述层**：检索只取文本相似度，泛化只产出建议，解码又用一套手写模板覆盖了建议。要让裂变提示词真正对标素材池，缺的不是更多描述，而是一层**带来源、可逐槽位回填、能被校验的结构化契约**。
