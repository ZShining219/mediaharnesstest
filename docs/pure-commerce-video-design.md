# 纯带货视频生成链路（B 线）设计

> 日期：2026-10-18  
> 关联文档：[clipcat-product-reference.md](clipcat-product-reference.md)  
> 2026-10-18 修订：输入确定为 **「意图文本 + 资源图片」**；资源图片按 **固定资产（人物/背景）** 与 **流动资产（商品/其他）** 分层。目标是让项目从一句话 + 一组图，端到端完成一条可审核/可发布的带货视频。  
> 2026-10-18 实现修订：B 线确定 **不做口播**，以画面冲击展示商品。实际实现以 `pipelines/product_video/` + `web/src/views/ProductVideo.vue` 为准：DirectorPlan 使用 `shot_function / camera / lighting / person_action / product_action / on_screen_text / transition / prompt`；无 TTS/唇形/台词，声音只保留 BGM。本文档中 `audio / voiceover / dialogue / voice_id` 等字段为早期口播方案，已不再采用。  
> **P0 已实现（2026-10-18）**：H3 每镜原生音轨丢弃；按计划 2–4 秒裁剪；成片统一 BGM + 淡入淡出 + 响度归一；规划/编译加入 `pacing / start_state / end_state / transition / 服装锁定`；负面约束禁止慢动作与新增服装部件。

---

## 0. 一句话模型

```
B 线 = 一条意图（文本）
     + 固定资产（人物、背景：跨视频复用）
     + 流动资产（商品、道具、包装、logo、优惠等：本期可变）
     → Agent 解析意图、绑定资产、生成 VideoPlan
     → 编译逐镜提示词
     → 逐镜生成（参考视频不参与）
     → 合成、审核、发布
```

**核心原则**：

1. **固定资产定义"谁、在哪"**：账号人设与视觉世界，长期复用、版本化、可摊销。
2. **流动资产定义"这期卖什么"**：商品与本期内容，按活动/批次变化，可归档。
3. **意图定义"为什么、怎么说"**：目标、平台、时长、语言、风格、CTA、约束。
4. **参考视频只做结构分析，永远不做生成输入**：B 线不向视频模型提交 `reference_video`。

---

## 1. 资产模型：固定资产 vs 流动资产

### 1.1 定义

| 层 | 包含 | 生命周期 | 作用 | 示例 |
|---|---|---|---|---|
| 固定资产 | 人物、背景（可选品牌资产） | 长期，跨视频复用，带版本 | 建立人设与视觉世界，保证一致性 | 角色"小雨"的正面/侧面/全身图；"冬日街头"场景图 |
| 流动资产 | 商品、道具、包装、logo、优惠、其他内容 | 短期，按活动/批次，可归档 | 本期要带的货与内容 | 轻量羽绒服的多角度图、卖点、价格；圣诞礼盒；本期优惠 |
| 意图 | 文本 | 每条约一条 | 描述视频目标与表达方式 | "用小雨在冬日街头，给这件羽绒服拍一条 20 秒种草视频，突出轻和暖，9:16，中文口播" |
| 结构参考（可选） | 参考视频/链接、模板、灵感库 | 每条可选 | 只提供结构 blueprint | 一条爆款 TikTok；"痛点-展示-证明-CTA"模板 |

### 1.2 为什么这个分层成立

- **一致性**：固定资产的参考图和描述在每条视频里保持稳定，人物不漂移、背景不跳变。
- **复用与摊销**：固定资产一次整理，长期使用；每条视频只换流动资产，边际成本低。
- **批量能力**：
  - 同一固定资产 × 不同流动资产 = 同一账号/人设的系列带货；
  - 同一流动资产 × 不同固定资产 = 多人物/多场景的 A/B 变体；
  - 同一固定资产 + 同一流动资产 × 不同意图/钩子 = 同品多创意。
- **生命周期清晰**：固定资产需要版本管理（换装、换场景），流动资产需要归档/过期（活动结束、商品下架）。
- **权限与成本**：固定资产是"账号资产"，流动资产的成本只落在本期；生成时可以只对流动资产做商品保真校验。

### 1.3 资产 schema

#### 固定资产：人物

```json
{
  "id": "char_xiaoyu",
  "role": "fixed",
  "kind": "character",
  "name": "小雨",
  "images": {
    "front": "assets/characters/xiaoyu/looks/front.png",
    "side": "assets/characters/xiaoyu/looks/side.png",
    "full": "assets/characters/xiaoyu/looks/full.png"
  },
  "voice_id": "female-shaonv",
  "descriptors": ["25岁女性", "短发", "自然妆容", "亲和力"],
  "variants": [
    {"id": "winter", "name": "冬季通勤", "images": ["..."]},
    {"id": "summer", "name": "夏季休闲", "images": ["..."]}
  ],
  "version": 3,
  "status": "active",
  "created_at": "2026-10-01T10:00:00+08:00"
}
```

#### 固定资产：背景

```json
{
  "id": "bg_winter_street",
  "role": "fixed",
  "kind": "background",
  "name": "冬日街头",
  "images": ["assets/backgrounds/winter_street_day.png"],
  "descriptors": ["冬日城市街头", "暖色橱窗光", "背景轻微虚化", "自然光"],
  "variants": [
    {"id": "day", "name": "白天", "images": ["..."]},
    {"id": "night", "name": "夜晚", "images": ["..."]}
  ],
  "version": 1,
  "status": "active"
}
```

#### 流动资产：商品

```json
{
  "id": "prod_down_jacket",
  "role": "liquid",
  "kind": "product",
  "name": "轻量羽绒服",
  "images": {
    "front": "assets/products/jacket_front.png",
    "back": "assets/products/jacket_back.png",
    "detail": "assets/products/jacket_detail.png"
  },
  "selling_points": ["90% 白鸭绒", "仅 280g", "可收纳进小包"],
  "claims": ["保暖", "轻量", "通勤"],
  "forbidden_claims": ["绝对最暖", "医疗功效"],
  "price": "¥399",
  "sku": "DOWN-JK-2026-01",
  "status": "active",
  "expires_at": null
}
```

#### 流动资产：其他内容

```json
{
  "id": "prop_gift_box",
  "role": "liquid",
  "kind": "prop",
  "name": "圣诞礼盒",
  "images": ["assets/props/gift_box.png"],
  "note": "仅用于节日活动，活动结束后归档"
}
```

### 1.4 角色可配置

默认规则：

- `character`、`background` → `role = fixed`
- `product`、`prop`、`packaging`、`logo`、`offer`、`other` → `role = liquid`

但允许用户调整：

- 品牌 logo 可以提升为固定资产（跨视频统一）；
- 某个人物如果只用于一次活动，也可以临时标为流动资产；
- 固定资产可以有多个 `variants`（冬季/夏季、白天/夜晚），每条视频绑定一个变体。

### 1.5 资产库与绑定

- **固定资产库**：角色、背景；支持多版本、变体、默认项。
- **流动资产库**：商品、道具、包装、logo、优惠；支持按活动/批次、有效期、归档。
- **一条视频绑定**：
  - 1 个角色（可空，纯商品特写视频可以无人物）；
  - 1 个背景（也可多场景，但每条视频默认一个主背景）；
  - 1..N 个流动资产（至少 1 个商品）。
- 绑定结果写入 `VideoPlan`；生成时按分镜分配参考图。

---

## 2. B 线与 A 线的边界

### 2.1 A：对标视频转换（现有）

**输入**：参考视频（必需）+ 人物/服饰参考图 + 可选背景 + 提示词。  
**生成**：H3 的 `reference_video` + `reference_image`，保留原视频动作/场景/节奏，替换人物/服饰/背景。  
**适用**：已有一条验证过的视频，快速做同款换人/换装。

### 2.2 B：纯带货视频生成（新增）

**输入**：意图文本 + 固定资产（人物/背景）+ 流动资产（商品/其他）+ 可选结构参考（仅分析）。  
**生成**：逐镜文本 + 人物/商品/背景参考图，**不提交参考视频**；Agent 生成并编辑 VideoPlan，PromptCompiler 编译逐镜提示词。  
**适用**：没有现成视频，只有商品和人物素材，需要原创多镜带货视频。

### 2.3 对比表

| 维度 | A 对标视频转换 | B 纯带货视频生成 |
|---|---|---|
| 是否必须有参考视频 | 是（生成输入） | 否；参考视频仅可选用于分析 |
| 视频模型是否收到 `reference_video` | 是 | **否（代码层硬约束）** |
| 画面来源 | 原视频画面/动作 | 固定资产 + 流动资产 + 提示词 |
| 结构来源 | 原视频本身 | 意图 / 参考视频分析 / 商品 brief / 模板 / 灵感库 |
| 资产复用 | 参考视频每条不同 | 固定资产长期复用，流动资产按本期换 |
| 动作保真 | 高 | 低（模型自由生成） |
| 创作自由度 | 低 | 高 |
| 多镜叙事 | 单条视频为主 | 多分镜 + 拼接 |
| 失败模式 | 换脸崩、动作崩、音轨丢失 | 商品变形、人物漂移、镜头不连贯 |
| 审核重点 | 人物是否像、动作是否保真 | 商品是否可识别、人物是否一致、卖点是否出现 |
| 典型用户 | 有对标视频的卖家 | 有商品/人物资产、想做原创的卖家 |

### 2.4 共享底座

- 素材上传/资产库/角色库
- H3/WaveSpeed/ComfyUI 模型客户端
- 单镜生成能力（`generate_shot`）
- 音轨/字幕/BGM/响度/拼接
- 审核队列、任务中心、定时发布
- 成本预估、模型注册表
- 项目空间、发布记录、数据分析

**结论**：共享底座，两条产线；不要把 `video_transform` 改成"source 可选"的双模管线。

---

## 3. 端到端流程

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 输入                                                      │
│    意图文本："用小雨在冬日街头，给这件羽绒服拍一条 20 秒      │
│              种草视频，突出轻和暖，9:16，中文口播"            │
│    固定资产：人物小雨 / 背景冬日街头                          │
│    流动资产：轻量羽绒服（多角度图 + 卖点）                    │
│    可选：参考视频/链接、模板、灵感库（仅分析）                │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│ 2. Intent Parser                                             │
│    解析：目标/平台/时长/画幅/语言/风格/CTA/约束/缺失槽位      │
│    读现场：已有资产、默认角色/背景、最近项目                  │
│    缺关键槽位 → 最多 3 个带默认值的问题                       │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│ 3. Asset Binder                                              │
│    绑定人物(固定) + 背景(固定) + 商品/其他(流动)              │
│    选择固定资产变体（冬季/白天）                              │
│    校验：商品图是否足够、卖点是否完整、禁用声明                │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│ 4. Plan Agent                                                │
│    生成 VideoPlan：hook + shots[] + dialogue + refs + model  │
│    可编辑、可对话改写、可单镜重生成                            │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│ 5. Prompt Compiler                                           │
│    每镜 prompt = 全局风格 + 固定资产描述 + 流动资产描述 +     │
│                 本镜动作 + 镜头/光线 + 负面约束 + 模型参数    │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│ 6. Shot Generator                                            │
│    H3：文本 + 人物图 + 商品图 + 背景图（无参考视频）          │
│    每镜独立任务 → 状态/成本/重试                              │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│ 7. Assembler                                                 │
│    TTS 口播 → 拼接 → 字幕 → BGM → 响度 → 审核队列            │
│    通过/打回 → 定时发布 → 数据复盘                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 意图输入（Intent）

### 4.1 意图可以有多自然

一条意图可以是一句话，也可以是一段 brief：

- "用小雨在冬日街头，给这件羽绒服拍一条 20 秒种草视频，突出轻和暖，9:16，中文口播。"
- "给这款咖啡机做一条 15 秒痛点-解决型视频，人物用默认角色，背景用厨房。"
- "参考这条 TikTok 的结构，换成我们的新品，做 3 条不同钩子的变体。"
- "用品牌固定角色和圣诞背景，推这款礼盒，30 秒，英文，带 CTA。"
- "不要人物，只拍商品特写，10 秒，突出材质和细节。"

### 4.2 IntentSpec

```json
{
  "raw": "用小雨在冬日街头，给这件羽绒服拍一条 20 秒种草视频，突出轻和暖，9:16，中文口播",
  "goal": "product_video",
  "platform": "douyin",
  "duration": 20,
  "aspect_ratio": "9:16",
  "language": "zh",
  "tone": "真实生活感",
  "fixed_assets": {
    "character_id": "char_xiaoyu",
    "character_variant": "winter",
    "background_id": "bg_winter_street",
    "background_variant": "day"
  },
  "liquid_assets": ["prod_down_jacket"],
  "structure_source": {
    "type": "brief",
    "text": "痛点-展示-证明-CTA，突出轻、暖、可收纳"
  },
  "cta": "点击购物车",
  "constraints": ["不出现品牌 logo", "不要字幕", "不虚构价格"],
  "missing": []
}
```

### 4.3 解析规则

1. **先读现场**：已有固定资产库、流动资产库、默认角色/背景、最近项目、历史偏好。
2. **能从意图解析的直接填**：人物名、背景名、商品名、时长、画幅、语言、平台、风格、CTA。
3. **不能解析的用默认值**：默认角色/背景、默认时长（15s/20s）、默认画幅（9:16）、默认语言（中文）、默认模型。
4. **关键缺失才提问**：人物、商品、时长/平台这类高影响字段；最多 3 个问题，每个带默认选项。
5. **不猜商品事实**：卖点、价格、功效必须来自流动资产；不得虚构。
6. **确认卡**：展示"将使用：人物 X / 背景 Y / 商品 Z / 时长 / 画幅 / 语言 / 模型 / 预估成本"，用户确认后才生成。
7. **参考视频只进分析**：如果意图里包含链接/视频，解析为 `structure_source`，不进入生成请求。

### 4.4 自主级别

| 级别 | 行为 | 适用 |
|---|---|---|
| L0 手动 | 用户自己写 Plan、自己改每一镜 | 精细创作 |
| L1 提案 | Agent 生成 Plan，用户确认后生成 | **默认推荐** |
| L2 一键 | Agent 用默认值直接生成，用户只看结果 | 熟练用户/批量 |
| L3 批量 | 同一固定资产 × 多流动资产/多钩子自动出多条 | 矩阵运营 |

> 建议 MVP 先做 L1：Agent 提案 + 确认卡；跑顺后再开放 L2/L3。这样既能让用户"一句话完成视频"，又避免一次生成多条昂贵的废片。

---

## 5. VideoPlan 数据模型

`VideoPlan` 是 B 线的唯一事实源。前端编辑它，Agent 改写它，PromptCompiler 读取它，生成管线执行它。

### 5.1 完整示例

```json
{
  "id": "plan_20261018_001",
  "title": "冬季轻量羽绒服种草",
  "intent_id": "intent_20261018_001",
  "meta": {
    "duration": 20,
    "aspect_ratio": "9:16",
    "language": "zh",
    "style": "真实生活感、自然光、手持轻晃、暖色调",
    "resolution": "720p",
    "platform": "douyin"
  },
  "fixed_assets": {
    "character": {
      "id": "char_xiaoyu",
      "variant": "winter",
      "name": "小雨",
      "refs": [
        "assets/characters/xiaoyu/looks/front.png",
        "assets/characters/xiaoyu/looks/side.png"
      ],
      "voice_id": "female-shaonv",
      "descriptors": ["25岁女性", "短发", "自然妆容", "亲和力"]
    },
    "background": {
      "id": "bg_winter_street",
      "variant": "day",
      "name": "冬日街头",
      "refs": ["assets/backgrounds/winter_street_day.png"],
      "descriptors": ["冬日城市街头", "暖色橱窗光", "背景轻微虚化"]
    }
  },
  "liquid_assets": {
    "product": {
      "id": "prod_down_jacket",
      "name": "轻量羽绒服",
      "refs": [
        "assets/products/jacket_front.png",
        "assets/products/jacket_detail.png",
        "assets/products/jacket_back.png"
      ],
      "selling_points": ["90% 白鸭绒", "仅 280g", "可收纳进小包"],
      "claims": ["保暖", "轻量", "通勤"],
      "forbidden_claims": ["绝对最暖", "医疗功效"]
    },
    "props": [],
    "logo": null
  },
  "hook": {
    "text": "冬天穿得像个粽子？",
    "visual": "人物抱着厚重外套走进画面，表情无奈",
    "evidence": "痛点反问 + 反差"
  },
  "shots": [
    {
      "index": 1,
      "duration": 3,
      "camera": "中景，手持轻晃",
      "subject_action": "人物抱着厚重外套，皱眉看向镜头",
      "product_action": "无",
      "background": "冬日街头，暖色橱窗光",
      "dialogue": "冬天穿得像个粽子？",
      "on_screen_text": "冬天穿得像个粽子？",
      "refs": {
        "fixed": {"character": [0, 1], "background": [0]},
        "liquid": {"product": [], "props": [], "logo": []}
      },
      "prompt": "",
      "model": "minimax_h3",
      "status": "pending"
    },
    {
      "index": 2,
      "duration": 4,
      "camera": "近景，固定机位",
      "subject_action": "人物从包里抽出轻薄羽绒服，抖开",
      "product_action": "羽绒服展开，面料反光",
      "background": "街头，背景虚化",
      "dialogue": "直到我换了这件，轻到像没穿。",
      "on_screen_text": "仅 280g",
      "refs": {
        "fixed": {"character": [0], "background": [0]},
        "liquid": {"product": [0, 1], "props": [], "logo": []}
      },
      "prompt": "",
      "model": "minimax_h3",
      "status": "pending"
    },
    {
      "index": 3,
      "duration": 5,
      "camera": "特写，缓慢推近",
      "subject_action": "人物把羽绒服揉成一团，塞进小包",
      "product_action": "面料压缩回弹，细节清晰",
      "background": "室内暖光桌面",
      "dialogue": "90% 白鸭绒，收起来只有这么大。",
      "on_screen_text": "90% 白鸭绒",
      "refs": {
        "fixed": {"character": [0], "background": []},
        "liquid": {"product": [0, 1, 2], "props": [], "logo": []}
      },
      "prompt": "",
      "model": "minimax_h3",
      "status": "pending"
    },
    {
      "index": 4,
      "duration": 4,
      "camera": "中景，人物面向镜头",
      "subject_action": "人物穿上羽绒服，转身展示版型",
      "product_action": "版型挺括，颜色自然",
      "background": "冬日街头，暖色橱窗光",
      "dialogue": "通勤、约会都能穿，冬天不用再裹成球。",
      "on_screen_text": "通勤百搭",
      "refs": {
        "fixed": {"character": [0, 1], "background": [0]},
        "liquid": {"product": [0, 2], "props": [], "logo": []}
      },
      "prompt": "",
      "model": "minimax_h3",
      "status": "pending"
    }
  ],
  "audio": {
    "voiceover": true,
    "voice_id": "female-shaonv",
    "bgm": "winter_light.mp3",
    "subtitles": true
  },
  "source": {
    "type": "brief",
    "text": "痛点-展示-证明-CTA，突出轻、暖、可收纳",
    "analysis_id": null
  },
  "created_at": "2026-10-18T15:00:00+08:00",
  "updated_at": "2026-10-18T15:00:00+08:00"
}
```

### 5.2 字段说明

| 字段 | 作用 | 注意 |
|---|---|---|
| `intent_id` | 关联原始意图 | 便于回看/复用 |
| `meta` | 全局时长/画幅/语言/风格/分辨率/平台 | 风格作为每镜 prompt 前缀 |
| `fixed_assets.character` | 固定人物与变体 | 多视角图；每镜出现人物时引用 |
| `fixed_assets.background` | 固定背景与变体 | 可分镜切换，但默认主背景固定 |
| `liquid_assets.product` | 本期商品 | 多角度图；卖点/声明进入口播与负面约束 |
| `liquid_assets.props/logo` | 本期道具/品牌 | 按需出现；logo 可后期叠加 |
| `hook` | 开场钩子 | 前 3 秒决定留存 |
| `shots[]` | 分镜列表 | 每镜独立生成/重试 |
| `shots[].refs.fixed` | 本镜使用哪些固定资产图 | 人物/背景 |
| `shots[].refs.liquid` | 本镜使用哪些流动资产图 | 商品/道具/logo |
| `shots[].prompt` | 编译后的提示词 | 可人工微调 |
| `shots[].model` | 本镜模型 | 按镜路由 |
| `shots[].status` | `pending/running/done/failed` | 前端进度/重试 |
| `audio` | 口播/音色/BGM/字幕 | 先合成音轨再拼接 |
| `source` | 结构来源与证据 | 参考视频只在这里出现 |

### 5.3 结构模板（无参考视频时）

| 段落 | 时长 | 目的 | 典型内容 |
|---|---|---|---|
| Hook | 0–3s | 抓注意力 | 痛点反问、反差、好奇、场景代入 |
| Product reveal | 3–7s | 让商品出现 | 产品特写、上手、抖开/试用 |
| Proof / usage | 7–15s | 证明卖点 | 使用过程、细节、对比、效果 |
| Objection handling | 15–20s | 消除顾虑 | 材质/价格/场景/信任 |
| CTA | 20–25s | 行动号召 | 购物车、直播、评论区、限时 |

---

## 6. Agent：解析、绑定、编排、改写

### 6.1 Agent 的职责边界

Agent **不直接生成视频**，它做四件事：

1. **解析意图**：把自然语言转成 `IntentSpec`。
2. **绑定资产**：从固定资产库/流动资产库中选出本条视频使用的资产；缺什么问什么。
3. **生成/改写 Plan**：把意图、资产、结构来源编排成 `VideoPlan`。
4. **解释与确认**：告诉用户"我将用谁、在哪、卖什么、分几镜、大概多少钱"，等确认。

真正的生成由 `Shot Generator` 执行；Agent 修改的是 Plan，不是像素。

### 6.2 参考视频分析（可选）

如果用户提供参考视频/链接，Agent 只做结构分析：

- 逐分镜：时间区间、镜头类型、画面描述（机位/走位/构图/神态）、口播。
- 爆款要素：hook、hook_evidence、pain_point、selling_points、visual_elements、emotion、audience。
- 反推提示词：Style / Environment / Camera / Lighting / Character / Shots。

输出进入 `VideoPlan.source`，用于"结构迁移"，不进入生成请求。

### 6.3 从分析到 Plan 的映射

| 参考视频 | 新视频 |
|---|---|
| 原分镜的功能（钩子/展示/证明/CTA） | 保留 |
| 原分镜的镜头语言（中景/特写/推近） | 尽量保留 |
| 原分镜的画面内容 | 替换为固定资产 + 流动资产 |
| 原分镜的口播 | 改写为商品卖点/本期内容 |
| 原视频的人物 | 替换为固定角色 |
| 原视频的场景 | 替换为固定背景 |
| 原视频的商品 | 替换为流动资产商品 |

### 6.4 对话式改写

中间栏的 Agent 支持这些指令：

- "把第 2 镜改成手持商品特写，3 秒"
- "开头钩子换成'你还在穿臃肿的羽绒服吗？'"
- "第 3 镜突出可收纳，加一个塞进包里的动作"
- "整体节奏再快一点，总时长压到 15 秒"
- "把口播改成更口语化，适合小红书"
- "换一个背景，用圣诞场景"
- "商品换成礼盒，其他不变"

Agent 只修改 Plan 中对应字段，然后：

1. 重新编译受影响分镜的 prompt；
2. 前端高亮"哪些分镜会重新生成"；
3. 用户确认后只重跑受影响的分镜。

### 6.5 Prompt Compiler 规则

每个分镜的提示词按固定结构编译：

```
[全局风格] {meta.style}，{aspect_ratio} 竖屏，{language} 口播
[固定人物] 参考图1/2中的人物（{character.name}，{character.descriptors}），
          保持五官、发型、体型、肤色一致
[固定背景] 参考图3中的场景（{background.name}，{background.descriptors}）
[流动资产] 参考图4/5中的商品（{product.name}），保持颜色、版型、材质、细节一致；
          卖点：{selling_points}
[本镜] {camera}；{subject_action}；{product_action}；口播："${dialogue}"
[约束] 不生成字幕，不出现品牌 logo，不出现多余人物，
      手部结构稳定，商品不变形；禁止：{forbidden_claims}
```

编译规则：

1. **参考图编号与实际提交顺序一致**：prompt 里写"参考图1=人物正面，参考图2=人物侧面，参考图3=背景，参考图4=商品正面……"，`content` 数组按同样顺序提交。
2. **按镜分配参考图**：人物镜少放商品图，商品特写多放商品图，场景镜多放背景图；避免无关参考图污染。
3. **固定资产描述稳定**：角色/背景的 `descriptors` 每条视频一致，保证跨镜/跨视频一致性。
4. **流动资产描述按本期变化**：商品名、颜色、版型、卖点来自流动资产。
5. **每镜独立 prompt**：不要把 4 个分镜写成一段长 prompt；模型对长 prompt 的多镜控制弱，且失败后无法单镜重试。
6. **负面约束**：品牌 logo、文字、水印、多余人物、手部畸形、商品变形、禁用声明。
7. **模型参数**：时长、分辨率、画幅来自模型注册表，通过 API 参数控制，不写进 prompt。

---

## 7. UI 设计

### 7.1 布局

```
┌──────────────────────────────────────────────────────────────────────┐
│ 意图输入："用小雨在冬日街头，给这件羽绒服拍一条 20 秒种草视频..."    │
│ [解析意图]  [使用默认资产]                        预计 ¥2.4 · 20s     │
├──────────────────────┬──────────────────────────────┬───────────────┤
│ 固定资产              │ Agent / VideoPlan             │ 成片          │
│                      │                              │               │
│ 人物 [小雨 ▾]         │ 绑定：人物小雨 / 背景冬日街头 │ [预览/占位]   │
│  ┌────┐ ┌────┐       │       / 商品轻量羽绒服        │               │
│  │正面│ │侧面│       │                              │ 20s · 9:16    │
│  └────┘ └────┘       │ Tabs: 脚本 | 分镜 | 提示词 | JSON│ 4 镜 · ¥2.4  │
│  [换变体] [管理]      │                              │               │
│                      │ ┌ 分镜 1  3s  中景 ─────────┐ │ [生成视频]    │
│ 背景 [冬日街头 ▾]     │ │ 动作：抱厚外套皱眉       │ │               │
│  ┌────┐              │ │ 口播：冬天穿得像个粽子？ │ │ 分镜状态      │
│  │街景│              │ │ [编辑] [改写] [重生成]   │ │ 1 ✓ 2 ● 3 ○  │
│  └────┘              │ └──────────────────────────┘ │               │
│  [换变体] [管理]      │ ┌ 分镜 2  4s  近景 ─────────┐ │ [逐镜重试]    │
│                      │ │ ...                      │ │               │
│ ── 流动资产 ──        │ └──────────────────────────┘ │               │
│ 商品 [羽绒服 ▾]       │ [+ 添加分镜]                 │               │
│  ┌────┐ ┌────┐       │                              │               │
│  │正面│ │细节│       │                              │               │
│  └────┘ └────┘       │                              │               │
│  卖点：轻盈/保暖/收纳 │                              │               │
│                      │                              │               │
│ 道具/其他 [可选]      │                              │               │
│                      │                              │               │
│ 结构参考（可选）      │                              │               │
│ [粘贴链接/上传]       │                              │               │
│ ⓘ 仅用于分析，        │                              │               │
│   不会作为生成输入    │                              │               │
└──────────────────────┴──────────────────────────────┴───────────────┘
```

### 7.2 关键交互

1. **顶部意图栏**：一句话输入 + "解析意图"；解析后显示绑定结果与缺失槽位。
2. **左栏分两层**：
   - 固定资产：人物、背景；显示当前变体、默认项、管理入口。
   - 流动资产：商品、道具/其他；显示本期卖点、有效期/状态。
3. **中间是 Plan 编辑器**：Agent 对话 + Tabs（脚本/分镜/提示词/JSON）+ 分镜卡片。
4. **右栏是结果与成本**：预览、时长、画幅、预估成本、生成按钮、分镜状态、逐镜重试。
5. **结构参考独立抽屉**：明确标注"仅用于分析，不会作为生成输入"。
6. **确认卡**：生成前显示"将使用人物 X / 背景 Y / 商品 Z / 4 镜 / 20s / ¥2.4"，用户可改。
7. **缺失槽位**：用高亮/提示；"使用默认"一键补全。
8. **失败可恢复**：单镜失败不影响其他镜；重试只重跑该镜。

### 7.3 与现有 Transform 页的区分

| 页面 | 主输入 | 中间区 | 主输出 |
|---|---|---|---|
| 爆款复刻（原视频转换） | 参考视频 + 人物/服饰图 | 视频预览 + 提示词 | 换人后的视频 |
| 带货视频（新增 B 线） | 意图 + 固定资产 + 流动资产 | Agent 分析 + Plan/分镜 | 多镜原创带货视频 |

导航建议：

- **爆款复刻**：有对标视频，快速换人/换装。
- **带货视频**：有商品/人物资产，从意图生成原创视频。

两者共享素材库、角色库、审核、发布。

---

## 8. 后端与 API 设计

### 8.1 模块划分

```
pipelines/
├── video_transform/          # 现有：参考视频驱动
│   └── pipeline.py
└── product_video/            # 新增：意图 + 资产驱动
    ├── pipeline.py           # intent → bind → plan → compile → shots → assemble
    ├── intent.py             # 意图解析/缺失槽位/确认卡
    ├── binder.py             # 固定资产/流动资产绑定
    ├── plan.py               # VideoPlan schema/校验/默认值
    ├── compiler.py           # PromptCompiler
    └── shots.py              # 单镜生成/重试/状态

orchestrator/app/
├── assets.py                 # 资产模型（role/kind/version/status）
├── models.py                 # 模型注册表（能力/价格/约束）
├── media.py                  # 复用：mux/subtitle/bgm/loudnorm/concat
├── store.py                  # 复用/扩展：jobs/plans/review
└── main.py                   # 新增路由
```

### 8.2 共享能力抽取

从现有 `pipelines/video_transform/pipeline.py` 抽取：

- `run_minimax()` 的 H3 提交/轮询/下载 → `minimax.generate_video(content, ...)`
- `media.ref_image/ref_video` → 保持
- 音轨回填/BGM/拼接/字幕/响度 → `media.*` 复用
- 审核入库 → `store.add_review_item` 复用

新增 `generate_shot(spec)`：

```python
@dataclass
class ShotSpec:
    prompt: str
    fixed_refs: dict[str, list[Path]]     # {"character": [...], "background": [...]}
    liquid_refs: dict[str, list[Path]]    # {"product": [...], "props": [...], "logo": [...]}
    mode: str = "product_video"           # product_video | transform
    reference_video: Path | None = None   # 仅 transform 使用；product_video 必须为 None
    model: str = "minimax_h3"
    resolution: str = "720p"
    duration: int = 5
    aspect_ratio: str = "9:16"

def generate_shot(spec: ShotSpec, out: Path) -> Path:
    if spec.mode == "product_video":
        assert spec.reference_video is None, "纯带货链路禁止提交参考视频"
    content = [part_text(spec.prompt)]
    if spec.reference_video:
        content.append(part_video(spec.reference_video))
    for p in flatten(spec.fixed_refs) + flatten(spec.liquid_refs):
        content.append(part_image(p))
    ...
```

> 关键：`reference_video` 在 B 链路的类型/断言层面被禁止，而不是靠 UI 约定。

### 8.3 API

| 方法 | 路径 | 输入 | 输出 |
|---|---|---|---|
| POST | `/api/product-video/intent` | `{text, fixed_assets?, liquid_assets?}` | `IntentSpec + missing + suggestions` |
| POST | `/api/product-video/plan` | `{intent_id, character_id?, background_id?, product_ids?, template?}` | `VideoPlan` |
| GET | `/api/product-video/plan/{id}` | — | `VideoPlan` |
| PUT | `/api/product-video/plan/{id}` | `VideoPlan` 局部更新 | 更新后的 Plan |
| POST | `/api/product-video/plan/{id}/rewrite` | `{shot_index?, instruction}` | 更新后的 Plan |
| POST | `/api/product-video/plan/{id}/compile` | — | 每镜 prompt |
| POST | `/api/jobs/product-video` | `{plan_id, model?, resolution?, aspect_ratio?}` | `{job_id}` |
| GET | `/api/jobs/{id}/shots` | — | 每镜状态/成本/错误 |
| POST | `/api/jobs/{id}/shots/{index}/retry` | `{prompt?}` | 重试任务 |
| GET | `/api/assets?role=fixed|liquid&kind=...` | — | 资产列表 |
| POST | `/api/assets` | `{role, kind, name, images, metadata}` | 资产 |
| POST | `/api/characters/from-video-frame` | `{video, time}` | `{character_id, image}` |
| GET | `/api/models` | — | 模型注册表 |
| POST | `/api/product-video/estimate` | `{plan_id, model, resolution}` | `{total_cny, shots[]}` |

复用：

- `POST /api/upload`、`GET /api/assets`
- `GET/POST /api/characters`
- `GET /api/review`、`POST /api/review/{id}/approve|reject`
- `GET /api/jobs`、`GET /api/jobs/{id}`

### 8.4 数据存储

- `data/plans/{plan_id}.json`：Plan 完整 JSON（唯一事实源）。
- `data/assets.json` 或 SQLite `assets` 表：
  ```sql
  CREATE TABLE assets (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,          -- fixed | liquid
    kind TEXT NOT NULL,          -- character | background | product | prop | logo | offer | other
    name TEXT,
    images_json TEXT,
    metadata_json TEXT,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',
    created_at INTEGER,
    updated_at INTEGER
  );
  ```
- `jobs.db`：
  - `jobs` 增加 `plan_id`、`shot_index`、`parent_job_id`。
  - `plan_shots` 表（可选，快速查状态）。
  - `asset_snapshots` 表：记录每条 Plan 使用过的流动资产图/字段快照，防止资产删除后无法复现。
- 审核项 `inputs` 记录：
  - 固定资产图、流动资产图、每镜 prompt、Plan ID；
  - **不记录参考视频路径**（B 线没有生成参考视频）。

### 8.5 生成流程伪代码

```python
def run_product_video(plan_id: str, jid: str):
    plan = load_plan(plan_id)
    shots = plan["shots"]
    results = []
    for shot in shots:
        spec = ShotSpec(
            prompt=compile_prompt(plan, shot),
            fixed_refs=resolve_fixed(plan, shot),
            liquid_refs=resolve_liquid(plan, shot),
            reference_video=None,          # 硬约束
            model=shot["model"],
            duration=shot["duration"],
            resolution=plan["meta"]["resolution"],
            aspect_ratio=plan["meta"]["aspect_ratio"],
        )
        out = TMP / f"{jid}_shot{shot['index']}.mp4"
        generate_shot(spec, out)
        results.append(out)
        store.update_shot(plan_id, shot["index"], "done", out)

    video = media.concat(results)
    if plan["audio"]["voiceover"]:
        audio = tts(plan["shots"], plan["audio"]["voice_id"])
        video = media.mux_audio(video, audio)
    if plan["audio"]["subtitles"]:
        video = media.subtitles(video, plan["shots"])
    if plan["audio"]["bgm"]:
        video = media.mix_bgm(video, plan["audio"]["bgm"])
    video = media.loudnorm(video)
    store.add_review_item(video, "product_video", {...})
```

---

## 9. 生成与一致性策略

### 9.1 固定资产如何保证一致性

| 资产 | 策略 |
|---|---|
| 人物 | 同一角色 ID + 同一组多视角图 + 同一段 descriptors；每镜出现人物时都带人物参考图；TTS 用同一 voice_id |
| 背景 | 同一背景 ID + 同一组场景图 + 同一段光线/时间描述；换场景时在 Plan 中显式标记 |
| 变体 | 固定资产的 `variant` 在 Plan 中固定；同一视频内不混用不同变体 |
| 跨视频 | 固定资产版本号记录；升级版本后旧视频仍引用旧快照 |

### 9.2 流动资产如何保证商品保真

| 策略 | 说明 |
|---|---|
| 多角度参考 | 商品正面/背面/细节/包装至少 2–3 张 |
| 商品特写 | 钩子和 CTA 至少各有一个商品可见镜头 |
| 商品描述固定 | 颜色、版型、材质、关键细节写进 prompt |
| 负面约束 | 商品变形、颜色偏差、错误 logo、额外文字 |
| 卖点对齐 | 口播/字幕必须来自 `selling_points`，不虚构 |
| 禁用声明 | `forbidden_claims` 进入负面约束和审核检查 |

### 9.3 按镜选模型

| 分镜类型 | 推荐模型/方式 | 理由 |
|---|---|---|
| 人物口播 | H3 形象口播（人物图 + TTS 音频） | 口型与人物一致性最好 |
| 人物 + 商品互动 | H3 图/文生视频（人物图 + 商品图 + 背景图） | 多参考图可控 |
| 商品特写/材质 | 图生视频（商品图为主参考） | 保商品细节 |
| 场景/氛围 | 文生视频或图生视频（背景图为主） | 自由度高 |
| 产品静帧/封面 | 图像模型 | 缩略图/贴图 |
| 高质量 hero | Seedance/Veo/Kling/Wan（后续） | 画质/运镜更强 |

### 9.4 自动质检（MVP 可先人工）

| 检查 | 方法 | 处理 |
|---|---|---|
| 人物一致性 | 人脸 embedding 相似度 / 人工 | 低于阈值 → 重试该镜 |
| 商品可识别 | CLIP/图像相似度 / 人工 | 商品缺失/变形 → 换参考图或重试 |
| 商品卖点出现 | 检查口播/字幕关键词 | 缺失 → 改写该镜 |
| 禁用声明 | 关键词匹配 | 命中 → 阻断/提示 |
| 时长/画幅 | ffprobe | 不符合 → 重新生成或裁剪 |
| 字幕/口播对齐 | 时间轴检查 | 偏移 → 调整 TTS 或字幕 |

### 9.5 成本控制

- 每镜生成前估算：`duration × cny_per_sec[model][resolution]`。
- 生成前显示总价；超过预算上限时要求确认。
- 单镜最多重试 N 次（默认 2）；失败不自动无限重试。
- 失败/取消的镜头不计入成片；已完成镜头保留，避免重复烧钱。
- 固定资产的整理成本一次性投入；每条视频的边际成本主要是流动资产镜头 + 重试。

---

## 10. Clipcat 迁移清单（按固定资产/流动资产重排）

> 判定说明：  
> **直接复用** = 信息架构/交互/数据字段可直接照做；  
> **改造复用** = 思路可用，但需要按 B 线调整；  
> **仅借鉴** = 只借概念，不落实现；  
> **不适用** = 与当前目标无关。

| # | Clipcat 能力 | 对应 B 线 | 判定 | 落地要点 |
|---|---|---|---|---|
| 1 | 固定出镜人物 | 固定资产·人物 | **直接复用** | 角色库 + 多视角图 + voice_id + 跨视频固定 |
| 2 | 从视频帧建角色 | 固定资产·人物 | **直接复用** | ffmpeg 抽帧 + 角色建档 |
| 3 | 商品图上传/多角度 | 流动资产·商品 | **改造复用** | 新增 product 资产与多角度槽位 |
| 4 | 背景/场景参考 | 固定资产·背景 | **改造复用** | 新增 background 资产与变体 |
| 5 | 视频分析（逐分镜 + 口播） | 结构来源（仅分析） | **直接复用 schema** | 时间区间/镜头/画面/口播 |
| 6 | 反推提示词（Style/Environment/Camera/Lighting/Character/Shots） | Plan 的 blueprint | **直接复用 schema** | 作为 Plan Agent 的输入 |
| 7 | 分镜脚本 schema | VideoPlan.shots | **直接复用** | 映射到 shots[] |
| 8 | 钩子/痛点/卖点 | hook + product.selling_points | **改造复用** | 进入 Plan 与口播 |
| 9 | 四种复刻模式 | 结构策略 | **改造复用** | 结构复刻/人物固定/钩子保留/分镜替换 |
| 10 | 模型注册表 | 按镜路由 | **直接复用** | 能力/价格/约束 |
| 11 | 算力/成本预估 | 生成前总价 | **改造复用** | 先人民币，后算力 |
| 12 | 跨页预填 | 从灵感库/分析带入 Plan | **直接复用** | localStorage + TTL |
| 13 | 爆款社区/灵感库 | 结构来源 | **改造复用** | 先用现有备料池，不承诺 GMV |
| 14 | 项目空间 | 资产/任务分组 | **直接复用** | 固定资产/流动资产/项目 |
| 15 | 发布队列 | 成片发布 | **直接复用** | 补发布记录/失败重试 |
| 16 | 数据分析 + 复刻裂变 | 同固定/流动资产的变体 | **改造复用** | 从数据页带入意图/Plan |
| 17 | Skill/CLI | Agent 调用 B 线 | **改造复用** | 暴露 `product_video` 工具 |
| 18 | 商品套图 | 流动资产素材 | **仅借鉴** | 不做全量，先整理商品参考图 |
| 19 | 数字人视频 | 固定资产·人物口播 | **直接复用** | 口播镜复用现有数字人链路 |
| 20 | 采集爆款 + 爆款总结 | 结构来源 | **改造复用** | MediaCrawler + DeepSeek |
| 21 | GMV 榜单 | — | **仅借鉴** | 公开互动指标/人工精选 |
| 22 | 程序化 SEO | — | **不适用** | 内部工具不需要 |
| 23 | 算力订阅/团队 | — | **后续** | 对外商业化时再做 |

### 10.1 最值得先迁移的 6 项

1. **固定人物 + 从视频帧建角色** → 固定资产·人物的基础。
2. **视频分析/反推提示词 schema** → 结构来源与 Plan Agent 的核心。
3. **分镜脚本 schema** → VideoPlan 的骨架。
4. **模型注册表 + 成本预估** → 多镜生成的成本可控。
5. **跨页预填 + 灵感库** → 从看到爆款到生成 Plan 的最短路径。
6. **项目空间/发布/分析** → 固定资产与流动资产的生产闭环。

### 10.2 不建议迁移

- **把参考视频作为 B 的生成输入**：违背 B 线原则，会退化成 A。
- **一条 prompt 生成整条视频**：多镜控制弱、失败不可局部重试。
- **GMV 榜单承诺**：没有数据源。
- **"绝不判重/保证合规"话术**：平台判定不可控。
- **程序化 SEO/大规模工具矩阵**：内部工具阶段不适用。
- **算力订阅/复杂套餐**：除非确定对外商业化。

---

## 11. 代码映射（当前仓库）

### 11.1 可复用

| 现有能力 | 位置 | 在 B 中的用法 |
|---|---|---|
| H3 提交/轮询/下载 | `orchestrator/app/minimax.py` | 单镜生成 |
| 参考图/音频封装 | `minimax.Minimax.part_image/part_audio` | 单镜 content 组装 |
| 素材压缩 | `orchestrator/app/media.py` `ref_image` | 人物/商品/背景图预处理 |
| 音轨/BGM/字幕/响度/拼接 | `media.py` `mux_audio/mix_bgm/subtitles/loudnorm/concat` | 成片后期 |
| 任务记录 | `orchestrator/app/store.py` | 分镜/总任务 |
| 审核入库 | `store.add_review_item` | 成片进审核 |
| 角色/声音克隆 | `assets/characters`、`/api/characters`、`/api/voice/clone` | 固定资产·人物 |
| 素材库/上传 | `assets/*`、`/api/upload`、`/api/assets` | 固定资产/流动资产 |
| 提示词模板 | `templates.py`、`data/prompt_templates.json` | 结构模板/复刻模式 |
| 节点注册表 | `nodedefs.py` | 新增分析/编译节点（可选） |
| 前端槽位/选择器 | `web/src/views/Transform.vue` | 资产槽位组件 |
| 审核/发布 | `Review.vue`、`Schedules.vue` | 成片审核/发布 |

### 11.2 需要新增

| 新增 | 路径 | 作用 |
|---|---|---|
| 产品视频管线 | `pipelines/product_video/pipeline.py` | intent → bind → plan → compile → shots → assemble |
| 意图解析 | `pipelines/product_video/intent.py` | IntentSpec/缺失槽位/确认卡 |
| 资产绑定 | `pipelines/product_video/binder.py` | 固定资产/流动资产绑定 |
| Plan 模型 | `pipelines/product_video/plan.py` | VideoPlan schema/校验/默认值 |
| Prompt Compiler | `pipelines/product_video/compiler.py` | Plan → 逐镜 prompt |
| 单镜执行 | `pipelines/product_video/shots.py` | generate_shot/retry/status |
| 资产模型 | `orchestrator/app/assets.py` | role/kind/version/status |
| 模型注册表 | `orchestrator/app/models.py` + `data/models.json` | 能力/价格/约束 |
| 前端产品视频页 | `web/src/views/ProductVideo.vue` | 意图栏 + 资产栏 + Plan + 成片 |
| 意图栏 | `web/src/components/IntentBar.vue` | 一句话输入/解析/确认卡 |
| 资产栏 | `web/src/components/AssetRail.vue` | 固定资产/流动资产分组 |
| 分镜编辑器 | `web/src/components/PlanEditor.vue`、`ShotCard.vue` | 编辑/改写/重试 |
| 分析页 | `web/src/views/Analysis.vue` | 链接/上传 → 分镜表/反推提示词 |
| 灵感库 | `web/src/views/Inspiration.vue` | 结构来源/收藏/一键带入 |
| 数据 | `data/plans/{id}.json`、`data/assets.json` | Plan/资产 |

### 11.3 需要改动

| 改动 | 位置 | 说明 |
|---|---|---|
| 资产类型扩展 | `materials.py` `_KIND_DIR`、`Assets.vue` | 新增 `product`、`background`、`prop` 桶 |
| 资产角色字段 | 资产模型/上传 API | `role = fixed|liquid`、`kind`、`version` |
| 任务表扩展 | `store.py` / `jobs.db` | `plan_id`、`shot_index`、`parent_job_id` |
| 导航 | `web/src/App.vue` | 新增"带货视频"入口，与"爆款复刻"并列 |
| 提示词模板 | `templates.py` | 增加结构模板/模式字段 |
| 审核项 | `store.add_review_item` | B 的 `inputs` 不含参考视频，包含 Plan |
| 成本 | `models.py`/`credits.py` | 分镜/总价预估 |

### 11.4 不建议的改动

- **不要把 `video_transform` 的 `source` 改成可选**：会让 A/B 的失败模式、音频处理、审核输入混在一起。
- **不要在 B 中复用 `run_minimax(source=...)` 的默认 prompt**：默认 prompt 是"替换参考视频人物"，与 B 语义冲突。
- **不要把 Plan 存进 `jobs` 的 JSON blob**：Plan 需要版本化/可编辑/可 diff，独立 JSON 更合适。

---

## 12. MVP 实施顺序

### P0（3–5 天）：一句话 + 一组图 → 一条 15 秒视频

1. 资产模型：`role/kind/version/status`，固定资产（人物/背景）+ 流动资产（商品）。
2. 意图解析 v0：LLM 解析 `IntentSpec`；缺人物/商品/时长时用默认值或提问。
3. `VideoPlan` schema + 默认结构模板。
4. `PromptCompiler`（全局风格 + 固定资产 + 流动资产 + 本镜 + 负面约束）。
5. `generate_shot()`（H3，文本 + 人物图 + 商品图 + 背景图，无参考视频）。
6. 简单合成（concat + TTS + 字幕 + BGM + loudnorm）→ 审核队列。
7. 前端 `ProductVideo.vue` 最小版：意图栏 + 固定资产/流动资产栏 + 3 个分镜 + 生成/预览。

**验收**：输入一句话 + 人物图 + 背景图 + 商品图，生成 12–15 秒竖屏视频，人物/商品可识别，进审核队列，全程不需要参考视频。

### P1（1–2 周）：Agent 分析与可编辑 Plan

1. 视频分析（链接/上传 → 分镜表 + 口播）。
2. 反推提示词（Style/Environment/Camera/Lighting/Character/Shots）。
3. Plan 编辑器（编辑/改写/增删分镜/单镜重试）。
4. 商品多角度图 + 卖点字段；背景多图。
5. 成本预估 + 分镜状态。
6. 从视频帧建角色。
7. 资产变体（人物冬季/夏季、背景白天/夜晚）。

**验收**：粘贴一条参考视频，Agent 生成 Plan；用户改一镜，只重生成该镜；成本可见。

### P2（2–4 周）：从工具变成产线

1. 灵感库/项目空间/发布记录/数据分析。
2. 模型注册表 + 按镜路由。
3. 自动质检（人脸/商品相似度）。
4. Skill/MCP/CLI 暴露 `product_video`。
5. 批量变体（同一固定资产 × 多流动资产/多钩子）。
6. L2 一键生成/L3 批量。

**验收**：从灵感库一键带入 Plan，批量生成 5 条变体，审核后定时发布，数据可回看。

---

## 13. 风险与边界

| 风险 | 说明 | 缓解 |
|---|---|---|
| 意图歧义 | 用户一句话信息不足 | 读现场 + 默认值 + ≤3 个带默认选项的问题 |
| 资产错配 | 选错人物/背景/商品 | 确认卡 + 绑定结果高亮 + 可一键更换 |
| 商品保真 | 模型改变商品颜色/版型/细节 | 多角度参考图 + 特写镜 + 负面约束 + 人工审核 |
| 人物漂移 | 跨镜人物长相/发型变化 | 同角色参考图 + 同 descriptors + 人脸相似度检查 |
| 跨镜不连贯 | 光线/背景/色调跳变 | 同背景参考 + 统一风格前缀 + 后期调色 |
| 模型时长限制 | 单镜 4–15 秒，长视频需拼接 | 分镜规划 + 拼接 + 转场 |
| 成本失控 | 多镜 × 重试 | 预算上限 + 单镜重试次数 + 已完成镜头保留 |
| 口播/字幕不同步 | TTS 与画面时长不一致 | 先定分镜时长，再按字数控制 TTS；字幕按句切分 |
| 固定资产版本漂移 | 角色/背景升级后旧视频不一致 | 资产版本 + Plan 快照 |
| 流动资产删除 | 商品下架后无法复现 | `asset_snapshots` 保存 Plan 使用的图/字段 |
| 合规 | 商品声明、肖像权、版权、平台判重 | 禁用声明 + 审核闸门 + AI 标注提示 + 不承诺"不判重" |
| 参考视频版权 | 分析参考视频仍可能涉及版权 | 只提取结构，不复制画面；保留来源记录 |

---

## 14. 附录

### 14.1 意图示例

```
1) 用小雨在冬日街头，给这件羽绒服拍一条 20 秒种草视频，突出轻和暖，9:16，中文口播。
2) 给这款咖啡机做一条 15 秒痛点-解决型视频，人物用默认角色，背景用厨房。
3) 参考这条 TikTok 的结构，换成我们的新品，做 3 条不同钩子的变体。
4) 用品牌固定角色和圣诞背景，推这款礼盒，30 秒，英文，带 CTA。
5) 不要人物，只拍商品特写，10 秒，突出材质和细节。
```

### 14.2 资产 schema 速查

```
Asset {
  id, role: fixed|liquid, kind: character|background|product|prop|logo|offer|other,
  name, images{}, descriptors[], metadata{},
  version, status, created_at, updated_at
}

Character(Asset) += {
  voice_id, variants[{id,name,images[]}]
}

Background(Asset) += {
  variants[{id,name,images[],time_of_day,lighting}]
}

Product(Asset) += {
  sku, selling_points[], claims[], forbidden_claims[], price, expires_at
}
```

### 14.3 单镜提示词模板（自有文案）

```
[全局] {style}，{aspect_ratio} 竖屏，画面干净，真实质感
[固定人物] 参考图1/2中的人物（{character.name}，{character.descriptors}），
          保持五官、发型、体型、肤色一致
[固定背景] 参考图3中的场景（{background.name}，{background.descriptors}）
[流动资产] 参考图4/5中的商品（{product.name}），保持颜色、版型、材质、细节一致；
          卖点：{selling_points}
[本镜] {camera}；{subject_action}；{product_action}
[口播] {dialogue}
[约束] 不生成字幕，不出现品牌 logo，不出现多余人物，手部结构稳定，商品不变形；
      禁止：{forbidden_claims}
```

### 14.4 API 请求示例

```http
POST /api/product-video/intent
{
  "text": "用小雨在冬日街头，给这件羽绒服拍一条20秒种草视频，突出轻和暖，9:16，中文口播",
  "fixed_assets": {"character_id": "char_xiaoyu", "background_id": "bg_winter_street"},
  "liquid_assets": ["prod_down_jacket"]
}
→ {
  "intent_id": "intent_001",
  "spec": {...},
  "missing": [],
  "estimate": {"duration": 20, "shots": 4, "cny": 2.4}
}

POST /api/product-video/plan
{
  "intent_id": "intent_001",
  "template": "problem_solution_cta"
}
→ VideoPlan

POST /api/jobs/product-video
{
  "plan_id": "plan_20261018_001",
  "resolution": "720p",
  "aspect_ratio": "9:16"
}
→ { "job_id": "product_video-20261018-..." }
```

### 14.5 一句话行动建议

> 先把 **「意图 + 固定资产（人物/背景）+ 流动资产（商品）」→ VideoPlan → PromptCompiler → generate_shot(no reference_video) → 合成 → 审核** 这条最小链路跑通；  
> 用一句话 + 3 张图做出一条 15 秒视频，再逐步加视频分析/反推提示词、Plan 编辑器和批量变体。  
> Clipcat 能迁移的是"分析 → 结构 → 提示词"的方法论和交互，不是它的参考视频生成路径；B 线的价值恰恰在于 **只借结构，不借画面**。
