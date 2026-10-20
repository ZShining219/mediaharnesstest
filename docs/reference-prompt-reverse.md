# 参考视频池：描述、检索、泛化与裂变

> 日期：2026-10-19  
> 关联：`data/reference_pool.json`、`orchestrator/app/reference_analysis.py`、
> `orchestrator/app/reference_retrieval.py`、`orchestrator/app/reference_fission.py`

## 1. 定位

参考视频池不是“规则库”，而是**案例库（case library）**：

```
视频池
  → Encoder：多角色、分面、带证据的描述
  → 案例库 + 索引
  → Retriever：按新 brief 检索相关描述
  → Generalizer：多案例 → 约束模板
  → Decoder：约束模板 + 新素材 + H3 → 提示词/素材
```

池子本身不提供具体指引；描述尽量全，归纳与泛化发生在下游。

## 2. 数据布局

```
data/reference_cases/{ref_id}/
  evidence.json          # 镜头、关键帧、ASR、音频统计
  descriptions.json      # 全局 + 逐镜 + 9 角色 + H3 蓝图
  prompt_blueprint.json  # 机器可读蓝图
  prompt_blueprint.md    # 人读版本
  frames/shot_XX.jpg

data/reference_index/
  documents.jsonl        # facet 文档（global/shot/role/blueprint/transcript）
  index.json

data/reference_runs/{run_id}/
  brief.json             # 检索结果 + 约束模板 + 5 个方向
  plans.json             # DirectorPlan
  outputs/variant_XX.mp4 # 5 条裂变素材
  validation_XX.json     # 商品硬约束校验
  summary.json
```

## 3. 描述层（Encoder）

- **L1 证据**：PySceneDetect 切镜；每镜中间帧；faster-whisper ASR；ffmpeg 音量统计。
- **L2 视觉事实**：DeepSeek 多图视觉理解，输出全局判断 + 逐镜字段：
  `shot_size / angle / camera / lighting / color / composition / subject /
  action / product / product_visibility / on_screen_text / transition / confidence`
- **L2 角色视角**：9 个角色（观众/编导/摄影/剪辑/美术/声音/营销/平台/生成工程），
  每个角色输出 `observations / inferences / key_moments / confidence`；
  严格区分“观测”与“推断”。
- **L2 H3 蓝图**：`global_style / shot_prompts / camera_language / lighting /
  pacing / on_screen_text_style / negative / invariants / variables /
  hard_constraints / soft_constraints / reference_role_map / structure`

## 4. 检索与泛化（Retriever + Generalizer）

- `documents.jsonl` 把每个案例摊平成可独立检索的 facet 文档；
- 中文用 jieba 分词 + BM25；支持按 `role / dimension / tags` 过滤；
- `generalize()` 把 top-k 文档交给 LLM，归纳成：
  `summary / invariants / variables / hard_constraints / soft_constraints /
  structure_options / evidence_refs`
- 检索是“找相关经验”，泛化是“把多条经验压成可执行约束”，不是复述单条案例。

## 5. 裂变（Decoder + 生成 + 校验）

- `make_variant_briefs()` 基于约束模板生成 N 个结构差异明显的方向；
- 复用 `pipelines/product_video/plan.create()` 生成 DirectorPlan；
- `harden_plan()` 强制写入商品硬约束与禁止项；
- `pipelines/product_video/pipeline.run()` 调用 MiniMax H3 生成；
- `validate_output()` 用商品参考图 + 生成帧做 VLM 校验：
  `product_present / identity_match / color_match / detail_match / verdict`。

## 6. 命令

```bash
# 单条测试（不跑 ASR）
PYTHONPATH=. .venv/bin/python scripts/reference_describe.py \
  --ids ref-1792419234-1471 --no-transcribe

# 全量描述 + 建索引
PYTHONPATH=. .venv/bin/python scripts/reference_describe.py

# 只检索/泛化/生成方向，不建方案
PYTHONPATH=. .venv/bin/python scripts/reference_fission.py --dry-run

# 建方案但不生成视频
PYTHONPATH=. .venv/bin/python scripts/reference_fission.py --no-generate

# 完整链路：5 条
PYTHONPATH=. .venv/bin/python scripts/reference_fission.py --n 5
```

## 7. 借鉴的开源项目

| 项目 | 用途 |
|---|---|
| PySceneDetect | 镜头切分 |
| faster-whisper | ASR |
| DeepSeek V4 Flash Vision | 多图视觉理解（当前 `LLM_MODEL` 已支持读图） |
| MiniMax H3 | 视频生成 |
| TimeChat-Captioner / SkyCaptioner / Vript | 结构化 caption schema 参考 |
| OpenVideoSearch / vid-lens / AdaVideoRAG | 多索引 + 混合检索 + 证据引用参考 |
| LlamaIndex / LangGraph | parent-child 检索、状态图编排（后续可替换当前轻量实现） |

## 8. 当前边界

- ASR 默认 `base`，中文识别有误差，仅作补充；画面文字以 VLM 读数为主。
- 检索当前是 BM25，未上向量库；29 条规模足够，后续可换 embedding + hybrid。
- `validate_output()` 只校验商品硬约束，不做逐帧结构保真。
- B 线硬约束不变：参考视频不进入 H3 生成请求；参考图只使用人物/商品静帧。

## 9. 首次跑通结果（2026-10-19 / 20）

- 29/29 条参考视频完成描述：每条 3–8 镜、9 个角色视角、H3 蓝图、ASR 转写。
- 索引：628 个 facet 文档（global / shot / role / blueprint / transcript）。
- 选品：`ref-1792419234-1471` 中的奶白色蕾丝无钢圈文胸（t=8s 商品帧）。
- 裂变：5 条 12 秒、9:16、768P 产品素材，全部通过商品硬约束校验。
- 产物：`outputs/fission/fission-20261019-235919/`。
- 经验：
  - `deepseek-v4-flash` 的 reasoning 会吃掉输出预算，长 JSON 容易截断；
    案例描述改用 `deepseek-chat`（`REFERENCE_LLM_MODEL` 可覆盖）。
  - faster-whisper 1.2 与 PyAV 19 不兼容；已将音频读成 numpy 数组绕过。
  - 产品图从参考视频静帧裁剪，提示词中显式声明“忽略手/背景/文字”。
  - 受控裂变方案不提交人物图，只提交商品图，避免身份/服装迁移带来的额外风险。

## 10. 前端与 API

- 页面：`/#/fission`（侧栏“裂变素材”）
  - 选择参考视频；显示是否已描述、案例描述抽屉（全局/分镜/角色/H3 蓝图）
  - 设置商品帧时间、素材数量
  - 提交后台任务，展示阶段进度（检索/方案/生成/校验）
  - 裂变记录：5 条视频预览、identity/color/detail 校验分、问题、下载
- API：
  - `GET /api/reference-cases` / `GET /api/reference-cases/{ref_id}`
  - `GET /api/reference-runs` / `GET /api/reference-runs/{run_id}`
  - `POST /api/jobs/reference-fission` → `reference_fission` 任务
- 产物导出：`outputs/fission/{run_id}/`（5 条 mp4 + `manifest.json` + 校验 JSON）
- 前端构建：`cd web && npm run build`，后端静态托管 `web/dist`。
