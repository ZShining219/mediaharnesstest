# 文胸 UGC 裂变测试：3 条变体

> 日期：2026-10-20
> Run：`data/runs/ugc-bra-20261020-150644/`
> 人物：`assets/persons/半身照.png`
> 商品：`data/reference_runs/fission-20261019-235919/product.jpg`（奶白蕾丝文胸）
> 产出：3 条 12 秒竖屏 UGC，H3 原生中文口播 + 硬字幕

## 1. 链路

```text
pool_query.py        29 条全池多视角 digest
brief_synth.py      商品图 -> 动态 brief（11 facts / 5 unknowns / 5 assumptions）
guidance_synth.py   brief + 全池 -> 7 patterns / 3 directions
variant_gen.py      -> 3 个动态变体（5/4/5 beat）
contract_gen.py     -> 3 个契约（全部通过校验，0 warning）
run_contract.py     -> H3 原生音视频 + 硬字幕 + 审核
evaluation.json     -> 商品校验
```

## 2. 三条变体

| # | 方向 | 主参考 | Beat | 实际切点 | 商品校验 | 审核 |
|---|---|---|---:|---|---|---|
| v01 | 正面细节 + 翻转结构证明，末镜真人 CTA | 1471 | 5 | 2.42 / 4.88 / 7.50 / 10.13s | 9 / 9 / 9 pass | `outputs/review/variant_01.mp4` |
| v02 | 固定人物上身氛围 + 宽肩带验证 | 32b0 | 4 | 2.83 / 6.00 / 9.00s | 8 / 8 / 9 pass | `outputs/review/variant_02.mp4` |
| v03 | 背面四排扣 + 内里软支撑，末镜回正面 + 真人 CTA | 1471 | 5 | 2.46 / 4.92 / 7.46 / 10.04s | 8 / 8 / 9 pass | `outputs/review/variant_03.mp4` |

成片：

- `data/runs/ugc-bra-20261020-150644/v01/variant_01.mp4`
- `data/runs/ugc-bra-20261020-150644/v02/variant_02.mp4`
- `data/runs/ugc-bra-20261020-150644/v03/variant_03.mp4`

抽帧：

- `v01/contact_sheet.jpg`
- `v02/contact_sheet.jpg`
- `v03/contact_sheet.jpg`

## 3. 实际口播（H3 原生音频）

### v01

> 先看这个罩杯，花卉蕾丝里织了金线。前中一个金色蝴蝶结，下面还坠着小吊坠。肩带做了加宽，侧边一路都是金色包边。翻过来看背面，四排扣，内里是点状纹理。喜欢这种细节的姐妹，点下方看活动价。

### v02

> 先上身给你们看看，米白蕾丝这件。肩带是加宽的，抬手也不容易滑下来。拉近看，蕾丝和金边细节都很清楚。喜欢这种居家感的姐妹，点下方看活动价。

### v03

> 先翻到背面，四排扣，一排一排看得很清楚。内里是点状纹理，手指按下去能感觉到回弹。背带带点弹力，侧边一路金色包边。翻回正面，花卉蕾丝配金色蝴蝶结。结构都在这了，喜欢的姐妹点下方看活动价。

用 faster-whisper 转写原生音轨，3 条都与脚本逐句对齐（ASR 有同音字误差），时间点与切点基本吻合。

## 4. 观感

- **v01**：产品微距 + 手部翻转；末镜真人手持 CTA。适合“细节证明”型素材，信息密度高，但前 10 秒没有真人。
- **v02**：真人居家上身，宽肩带抬手验证；最接近“个体带货/种草”的观感，但商品在真人穿着时出现轻微杯型/肩带差异。
- **v03**：从背面四排扣开场，反序讲结构，末镜回正面 + 真人 CTA；适合“结构差异”型素材，手部遮挡较多。

## 5. 校验与问题

| 变体 | 校验 | 问题 |
|---|---|---|
| v01 | 9/9/9 pass | 无 |
| v02 | 8/8/9 pass | 杯型在真人穿着时略有变形；蕾丝花纹/肩带宽度与参考图有差异 |
| v03 | 8/8/9 pass | 图4手部遮挡较多；图5模特穿其他衣物，商品仅手持展示 |

其他：
- 商品颜色保持奶白/米白，没有生成黑/灰；
- 字幕均已硬烧，位置居中偏下；
- 人物资产已从旧 `1792312878_1.png` 更新为 `assets/persons/半身照.png`；
- 3 条均保留 H3 原生音轨，没有走 TTS。

## 6. 文件

```text
data/runs/ugc-bra-20261020-150644/
  pool_digest.json
  brief.json
  guidance.json
  variants.json
  v01/ contract.json prompt_h3.txt voiceover.txt subtitles.srt variant_01.mp4 contact_sheet.jpg
  v02/ ...
  v03/ ...
  evaluation.json
```

复现：

```bash
.venv/bin/python scripts/ugc_batch.py \
  --product-image data/reference_runs/fission-20261019-235919/product.jpg \
  --person-image assets/persons/半身照.png \
  --text "商品是文胸，人物用固定人物图，产出3条裂变素材" \
  --n 3
```
