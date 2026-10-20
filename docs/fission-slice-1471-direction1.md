# 垂直切片：ref-1471 + 方向一

> 日期：2026-10-20
> 目的：验证 `fission-facets/v0` 是否足够支撑“参考结构 → 裂变分镜”的逐槽位回填。
> 范围：只生成 contract / H3 prompt / 对比报告，**未调用 H3 生成视频**。

## 1. 产物

```bash
.venv/bin/python scripts/fission_slice.py
```

输出到 `data/fission_slices/slice-1471-direction1/`（本地，`data/` 已 gitignore）：

| 文件 | 内容 |
|---|---|
| `contract.json` | 完整契约：目标、5 个 beat、来源、改写/放弃记录、校验 |
| `prompt_h3.txt` | 可直接提交 H3 的整条视频提示词 |
| `prompt_audit.md` | 人读审计：逐 beat 来源、facet 使用/改写/放弃、校验 |
| `diff.md` | 与旧 `variant_01` 的逐项对比 |

核心代码：
- `orchestrator/app/reference_contract.py` — 契约校验、H3 渲染、审计渲染
- `scripts/fission_slice.py` — 本次切片的方向/映射定义

## 2. 契约结构

```text
target.product      商品身份、必须出现、不得改变、参考图使用策略
target.format       12s / 9:16 / 768P / fast / 无口播 / 无字幕
structure.hook      0-1s 动作钩子
structure.beats[5]  每 beat：time / shot_size / angle / camera / lighting /
                    composition / action / product_evidence / transition /
                    source{beat_indices, shot_indices, fields_used, overrides}
facet_coverage      used / adapted / waived
```

每个 beat 都回答三个问题：
1. 用了参考的哪几个 beat / 镜头？
2. 用了哪些字段？
3. 哪些字段被目标方向改写或放弃，为什么？

## 3. 与旧链路的对比

| 维度 | 旧 `variant_01` | 新契约 |
|---|---|---|
| 分镜数 | 4 | **5**（方向声明的 5 个 beat 全部保留） |
| hook 位置 | 第 3 镜 6.0–9.0s | **第 1 beat 0.0–2.5s（动作 0–1s 开始）** |
| 每镜字段 | function/time/camera/action/evidence/transition（6） | **12 项**，含景别/角度/光线/构图/来源 |
| 参考来源 | 0 条显式来源 | **5/5 beat 带来源** |
| 参考 beat 使用 | 无记录 | **6/7**（beat 1 痛点否定放弃；beat 7 仅放弃 CTA 文案） |
| 参考镜头使用 | 无记录 | **7/7**（shot 7 为部分复用） |
| 方向 camera/lighting | 仅 hook 镜使用，其余硬编码 | **5/5 beat 均写入** |
| 结构选项 | 0 项进入 prompt | 方向 beats **1:1** 进入 prompt |
| 字段可追溯 | 无 | 每 beat 有 `source.*` |

## 4. 本切片的映射

| beat | 时间 | 功能 | 来源 | 关键改写 |
|---:|---|---|---|---|
| 1 | 0.0–2.5s | 视觉钩子 | beat 2-3 → shot 1-3 | 痛点文案 → 手指点蝴蝶结；暖黄柔光 → 中性柔光 |
| 2 | 2.5–4.5s | 结构证明·肩带 | beat 4 → shot 4 | 双手捏肩带 → 单手指捏连接处 |
| 3 | 4.5–7.0s | 结构证明·四排扣 | beat 5 → shot 5 | 保留翻转 + 四排扣构图 |
| 4 | 7.0–9.5s | 材质证明·内里 | beat 6 → shot 6 | 双手翻开 → 指腹按压回弹 |
| 5 | 9.5–12.0s | 结尾卡 | beat 3+7 → shot 2,3,7 | 正面英雄镜头；shot 7 只借侧边蕾丝/金边，不复用 CTA |

明确放弃：
- 参考 beat 1「痛点否定」——目标方向无口播、无痛点叙事；
- 参考 beat 7「促销 CTA 文案」——目标方向无 CTA；
- 参考字幕样式、口播转写、platform 字幕安全区提示——目标方向无字幕/无口播；
- 参考场景（纱帘/花艺/木质台面）——目标方向指定纯白台面。

## 5. 字段是否够用

结论：**够用**。本方向需要的景别、角度、机位、光线、构图、动作、商品证据、转场、来源与改写记录，都能在 facet 中找到并落到契约里；没有出现“缺字段导致无法落笔”。

边界：
1. 手部动作只有 `timeline[].action` 的文本粒度；若要精确到手指姿态/左右手/力度，需要给 facet 增加 hand 子槽位或关键帧描述。
2. `shot_size` / `camera` 是参考描述里的枚举/短句（`close_up`、`static`），批量渲染前需要一层词典或人工确认。
3. 场景/光线是目标方向主动覆盖参考的槽位，已在 `facet_coverage.adapted` 记录；下游必须尊重 override，不能把“改写”当成“丢失”。

## 6. 下一步

把本切片的契约结构泛化到批量链路：

1. `make_variant_briefs()` 的输出 schema 从自由文本方向改成 `structure.beats[]`（带 time/shot_size/camera/lighting/composition/action/evidence/source）；
2. `build_controlled_plan()` 直接消费 beats，删除 `_order_from_beat_order()` 的关键词折叠和固定 4 模块；
3. `compile_video()` 1:1 渲染 beats；
4. 校验增加结构项：hook 首帧、beat 数、每 beat 商品证据、source 覆盖率、override 是否显式；
5. 先用本切片跑一条 H3，和旧 `variant_01` 做人工对比，再决定是否批量。

## 7. 实跑结果（2026-10-20）

已用本切片 prompt 跑通 1 条 H3：

| 项 | 结果 |
|---|---|
| provider | metaso，task `2112361224941895680` |
| 成片 | `data/fission_slices/slice-1471-direction1/variant_contract.mp4` |
| 规格 | 12.0s / 768×1344 / 24fps |
| 审核队列 | `outputs/review/variant_contract.mp4` |
| 商品校验 | identity 9 / color 9 / detail 9 / pass（旧 variant_01 同为 9/9/9） |
| 切点 | 实际 2.46 / 4.58 / 7.08 / 9.58s vs 契约 2.5 / 4.5 / 7.0 / 9.5s |

抽帧观察：
- 0.2–1.25s：正面产品，手指入画点向蝴蝶结，hook 成立；
- 3.5s：侧面肩带/侧比；
- 5.75s：背面四排扣；
- 8.25s：内里点状纹理微压；
- 10.75s：正面英雄收尾。

偏差：H3 在 0.2–1.25s 右上角保留了木质托盘/叶片阴影，和“纯白台面、无背景道具”不完全一致；
下一版 negative 增加“无木质托盘/无植物/无花艺/背景纯白无缝”。另外 8.25s 内里特写过近，
商品整体不可见；若要求每 beat 都可识别商品，可加“材质特写保留外轮廓/肩带边缘”。

结论：契约结构被完整执行，商品校验与旧链路持平；可以进入批量链路改造。
详细逐帧对比见 `data/fission_slices/slice-1471-direction1/compare.md`。
