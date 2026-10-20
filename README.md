# AI 传媒工作台

一个**独立、产品化、傻瓜式**的 AI 自媒体生产工具：**数字人口播**、**对标视频转换（换人/换衣/换背景）**、**自动化创作**，生成内容统一进**审核队列**，验收后自动发布到抖音等平台。

> 全部功能 = 网页上的固定操作卡片，不需要懂节点/工作流。
> 进阶操作有 **节点画布** 页签（ComfyUI 式节点连线视图，但节点是固定功能卡）。
> 选型决策详见 [docs/decisions.md](docs/decisions.md)，对标产品分析见 [docs/benchmarks.md](docs/benchmarks.md)。

## 产品形态

```
本地开发/服务器 (Docker 或裸跑, 无GPU)
└── aimf-app  Web 工作台 http://127.0.0.1:8800
      ├─ 工作台:    三张功能卡(数字人/视频转换/自动创作) → 一键提交 → 审核队列
      ├─ 节点画布:  Vue Flow 节点编辑器, 节点类型由后端注册表驱动
      │             素材/模型/后处理/输出 四类21种节点, 类型化连线, 图即任务
      │             提交 → 后端拓扑执行 → 节点实时染色 → 产出进审核队列
      ├─ 任务中心:  实时进度 + 失败原因 + 结果定位
      ├─ 素材库:    分桶管理(对标视频/参考图/服装/声音/BGM) + 拖拽上传 + 角色管理
      ├─ 审核队列:  预览 → 通过(填标题/定时)/打回
      ├─ 成果展示:  全部产出作品墙(审核中/待发布/已发布/已打回) + 筛选/搜索/详情/下载
      ├─ 发布:      social-auto-upload → 抖音(扫码登录,cookie持久化)
      └─ 定时任务:  cron 定时生成/定点发布, 运行时可增删(写回 config.yaml)

推理引擎(全部托管 API, 按次付费, 零 GPU 部署)
  ├─ MiniMax H3(秘塔代理)   视频生成主力: 换脸/人物替换、形象口播、文生视频  ~¥0.09/秒
  ├─ MiniMax 官方站          情感 TTS + 声音克隆 (秘塔不代理 TTS)
  ├─ DeepSeek               文案/画面提示词 (自动创作; 超时自动降级模板文案)
  └─ WaveSpeed / ComfyUI    可选备选通道, config.yaml backend 一键切换
```

`ComfyUI` 保留为高级通道（config.yaml `backend: comfyui`），用于将来接入自建 GPU 做更精细的局部编辑——用户界面不变，普通使用完全不需要它。

## 前端 (web/)

Vite + Vue 3 + Vue Flow(画布) + Element Plus(组件库)，深色主题。

```bash
cd web && npm install       # 首次
npm run build               # 产出 web/dist/, 由 FastAPI 静态托管到 /
npm run dev                 # 开发模式(可选): vite dev server, 前端热更新
```

后端启动后 `/` 即新工作台；旧版 litegraph 页保留在 `/legacy`。
路由: `/#/` 工作台 `/#/transform` 视频转换(独立功能页) `/#/product-video` 带货视频(视觉编导型, 无口播) `/#/canvas` 画布 `/#/jobs` 任务 `/#/review` 审核 `/#/gallery` 成果展示 `/#/assets` 素材 `/#/schedules` 定时 `/#/status` 状态。

## 节点画布（工作流引擎）

图即任务定义：`素材(视频/图片/音频/文本/角色形象)` → `模型(TTS/InfiniteTalk/Wan-Animate/图像编辑/H3)` → `后处理(音轨/BGM/字幕/响度/拼接)` → `输出(审核队列/存目录/发布到平台)`。

- 双击画布搜索添加节点；端口类型校验（video 不会接错 image 口）
- 图可保存为模板复用；运行时逐节点状态染色（黄=运行/绿=完成/红=失败/灰=跳过）
- 后端 `orchestrator/app/nodedefs.py` 是节点唯一注册表，加节点=加一个 `fn`

## 三条管线（等价便捷入口）

| 功能 | 操作 | 底层 |
|---|---|---|
| 数字人口播 | 选角色 + 粘文案 + 选情绪 → 生成 | MiniMax TTS(官方站) → H3 形象+音频生视频 → 字幕/BGM/响度 |
| 视频转换(换脸) | 上传对标视频 + 选形象图 → 转换 | MiniMax-H3 `reference_video`+`reference_image` → 整人替换、动作场景保留 |
| 自动创作 | 填主题 → 生成 | DeepSeek 写文案+画面提示词 → MiniMax TTS → H3 文生视频 → 合成音轨 |
| 带货视频（B 线） | 固定人物照片 + 本期商品图 + 意图 → 编导方案 → 确认生成 | DeepSeek 生成视觉编导 DirectorPlan → 逐镜 H3（无参考视频、无口播）→ 拼接/BGM → 审核 |

### 带货视频（B 线：视觉编导型，无口播）

- 输入：意图文本 + 固定人物照片（1–5 张）+ 本期商品图（2–6 张）+ 可选背景图
- 流程：DeepSeek 生成视觉编导方案（DirectorPlan：视觉概念/分镜/运镜/光线/逐镜提示词）→ 前端确认/编辑 → 逐镜 H3 生成 → 拼接/BGM → 审核队列
- 原则：不提交参考视频；不做口播；人物照片长期复用，商品图每条换
- API：`POST /api/product-video/plan`、`PUT /api/product-video/plan/{id}`、`POST /api/product-video/plan/{id}/compile`、`POST /api/jobs/product-video`
- 方案文件：`data/plans/*.json`；素材桶：`assets/persons`、`assets/products`、`assets/backgrounds`

### 参考视频池 → 提示词逆向 → 裂变（PRE）

- 定位：参考视频池是**案例库**，不是规则库；描述尽量全，归纳/泛化在下游
- Encoder：PySceneDetect 切镜 + 关键帧 + faster-whisper ASR + DeepSeek 多图视觉
  → 全局/逐镜 + 9 角色视角 + H3 蓝图
- Retriever/Generalizer：BM25 facet 检索 + LLM 归纳约束模板
- Decoder：约束模板 → DirectorPlan → H3 5 条裂变素材 → 商品硬约束校验
- 产物：`data/reference_cases/*`、`data/reference_index/`、`data/reference_runs/*`、
  `outputs/fission/*`
- 前端（历史 PRE 入口）：`/#/fission` 裂变素材页；当前默认引擎已切到 P0.2，
  见下一节
- API：`GET /api/reference-cases`、`GET /api/reference-runs`、
  `POST /api/jobs/reference-fission`
- 文档：[docs/reference-prompt-reverse.md](docs/reference-prompt-reverse.md)
- 命令：
  ```bash
  PYTHONPATH=. .venv/bin/python scripts/reference_describe.py
  PYTHONPATH=. .venv/bin/python scripts/reference_fission.py --n 5
  ```

### P0.2 创意裂变 job（当前主链路）

参考池先被拆成 StyleAtlas；商品 Profile 提供 ProductAnchor；CreativeWorld 负责创意装置，
最后由 Composer 编译契约和 H3 prompt。

- 一个后端 job 串起：素材解读 → anchor → style → world → contract → audit → H3 → 审核
- API：`POST /api/jobs/fission-p0`
- 前端：`/#/fission` 默认 P0.2 引擎；可只生成契约，也可生成视频
- 产物：`data/runs/p0-*/vNN/{contract.json,prompt_h3.txt,variant_NN.mp4}`
- 文档：[docs/fission-p0-architecture.md](docs/fission-p0-architecture.md)
- Harness：[docs/fission-harness.md](docs/fission-harness.md)（稳定输入/输出与移植边界）

```bash
curl -s -X POST http://127.0.0.1:8800/api/jobs/fission-p0 \
  -H 'Content-Type: application/json' \
  -d '{"profile_id":"panty-cotton-lace","n":5,"seed":42}'
```

命令行同样可用：`python -m pipelines.digital_human.pipeline --text "..." --character default` 等。

## 本地启动

最简单：Finder 里双击 `启动工作台.command`（已运行则直接打开页面），
停止用 `停止工作台.command`。或终端执行：

```bash
# 1. 后端 (FastAPI, 端口 8800)
.venv/bin/uvicorn orchestrator.app.main:app --host 127.0.0.1 --port 8800
#   或: bash scripts/run_orchestrator.sh

# 2. 前端 (首次需构建一次; FastAPI 会托管 web/dist 到 /)
cd web && npm install && npm run build && cd ..

# 3. 打开 http://127.0.0.1:8800
```

必要环境变量（`.env`，模板见 `.env.example`，已 gitignore）：

| 变量 | 用途 | 必填 |
|---|---|---|
| `MINIMAX_API_KEY` + `MINIMAX_BASE_URL=https://metaso.cn/api/minimax/v2` | 秘塔代理 H3 视频生成(换脸/口播/文生视频主力) | 是 |
| `MINIMAX_VIDEO_VIA` | 视频通道：`metaso`(只用秘塔, 默认)/`official`/`auto`(秘塔优先,官方兜底) | 可选 |
| `MINIMAX_API_KEY_OFFICIAL` | 官方站 sk- key，仅 TTS/声音克隆（视频不走官方） | 数字人/自动创作需 |
| `LLM_API_KEY` `LLM_BASE_URL` `LLM_MODEL` | DeepSeek 文案(自动创作; 不可用时自动降级) | 可选 |
| `WAVESPEED_API_KEY` | 备选推理通道 | 可选 |
| `PEXELS_API_KEY` | 自动选材素材源(不配则走 Wikimedia Commons 兜底) | 可选 |
| `ORCH_TOKEN` | 设置后 /api /media 需 token | 部署到公网必设 |

## 换脸链路怎么跑（已实测）

1. 素材库上传：`sources/` 放对标视频、`images/` 放形象参考图（或在弹窗里直接传）
2. 工作台 → "对标视频转换" 卡 → 选视频 + 选形象图 → 提交
   （等价 API: `POST /api/jobs/video-transform {source, face, prompt?, resolution?}`；
   画布等价模板: `素材·视频+素材·图片+素材·文本 → H3 人物替换(换脸) → 输出·进审核队列`）
3. 约 1 分钟后任务完成（秘塔 H3，~¥0.09/秒），产出自动进 **审核队列**
4. 审核页播放验收 → 通过(可填标题/定时) / 打回

实测记录见下方"验收证据"。

## 社媒采集（小红书 / 抖音）

Transform 页 → 「自动选材 · 批量生成」→ ② 社媒对标视频：

- **AI规划检索词**: DeepSeek 把主题展开成小红书/抖音/服装检索词组 + 筛选偏好
- **搜索**: 走 `services/MediaCrawler`（vendored, `uv run mc_search.py`），无头 Chrome + 持久化登录态，候选合入①的网格（带"红/抖"角标、作者/点赞）
- **扫码登录**: 首次使用点平台右侧「扫码登录」→ 本机弹 Chrome → App 扫码 → 登录态存 `services/MediaCrawler/browser_data/`（复用数周到数月）
- **AI初筛前8**: DeepSeek 按标题/作者/点赞给候选排序并自动勾选，理由见悬浮提示
- 勾选后与 Pexels 候选混选, 「仅入库」进 `assets/sources/` 或「批量生成」直接发矩阵单
- 端点: `GET /api/materials/social/search|status` `POST /api/materials/social/login` `POST /api/materials/plan` `POST /api/materials/rank`
- 服务端串行执行（`user_data_dir` 单实例锁），单次搜索 10-60s，慢是正常的

### 每日备料（备料模式, ≈¥0/天）

**内容方向** `data/directions.json`（任务意图唯一事实源, 改它=改全链路）:

```json
[{"name": "方向名", "active": true, "brief": "主题描述",
  "daily_quota": {"xhs": 8, "douyin": 8},
  "rank_rule": "筛选偏好(喂给DeepSeek初筛)",
  "garment_themes": ["服装方向..."], "transform_prompt": "生成提示词模板"}]
```

定时任务新增 `material_scout`（如 `0 9 * * *`）或弹窗里点「立即备料」，每方向每日流程：
DeepSeek 规划检索词 → xhs/抖音按 quota 搜 → 平台 id 跨天去重 → DeepSeek 初筛打分 →
topK 自动下载入 `assets/sources`(视频)/`assets/garments`(图) → 记入备料池。

弹窗「⓪ 备料池」按方向分组展示（带 AI 理由/评分悬浮提示），点击即勾选，与手动搜索候选混用走同一入库/批量链路。DeepSeek 日耗 ~2k token/方向，唯一花钱的生成环节不做。

注意：MediaCrawler 为学习研究许可（非商用），目前以本地可选连接器方式 vendored，未拷贝进产品代码；下载内容做转换参考时注意肖像权/版权与平台条款。

## 部署

服务器曾部署：`docker compose -p aimf` 于 `/opt/aimf`（本次未动线上服务）。

重新部署（代码更新后）：

```bash
SSH_PASS=<服务器密码> uv run --with paramiko scripts/deploy_server.py
```

## 待办授权清单（需要你操作）

| # | 事项 | 操作 |
|---|---|---|
| 1 | 抖音登录 | `ssh root@103.52.153.212` → `docker exec -it aimf-app sau douyin login --account main`，终端会出二维码，抖音 App 扫码 |
| 2 | 声音克隆 | Web 素材库上传 10s+ 干净录音 → 角色卡"克隆声音"按钮一键完成(官方站接口) |
| 3 | WaveSpeed key（可选备选） | wavespeed.ai 注册 → `.env` 填 `WAVESPEED_API_KEY`，config.yaml 切 backend 即可启用 InfiniteTalk/Wan-Animate 通道 |
| 4 | 腾讯云 MPS（可选） | `.env` 填 `TENCENT_SECRET_ID/KEY` |
| 5 | MPT（可选） | 本地 `bash scripts/setup.sh --mpt`；或后续加到 compose |

## 目录结构

```
orchestrator/        编排器: FastAPI + ComfyUI/MiniMax/WaveSpeed/DeepSeek/MPT/sau 客户端
  app/nodedefs.py    节点注册表(21种: 素材5/模型8/后处理5/输出3)
  app/nodegraph.py   图校验+拓扑执行+节点状态回写
web/                 新前端: Vite + Vue3 + Vue Flow + Element Plus (构建产物 dist/)
pipelines/           digital_human / video_transform / auto_content
services/            开源组件: social-auto-upload(已入镜像) / MoneyPrinterTurbo / ComfyUI
assets/              characters(形象looks+声音配置) / sources / garments / voices / images / bgm
outputs/             review → approved → published / failed / tmp
data/jobs.db         任务记录(SQLite)
docs/                decisions / cloud-gpu / douyin / minimax
scripts/             setup.sh / run_*.sh / deploy_server.py / cloud_comfyui_bootstrap.sh
Dockerfile           单容器产品镜像 (编排器 + sau + ffmpeg + chromium)
```

## 验收证据 (2026-10-02 实测)

| 链路 | 任务ID | 产出 | 耗时/成本 |
|---|---|---|---|
| 换脸(管线卡) | `video_transform-20261002-034411-8ca9ff` | `outputs/review/video_transform-20261002-034411-8ca9ff_swap.mp4` (1344×768 h264+aac 4.4MB) | ~56s, ≈¥0.9 |
| 换脸(节点画布) | `graph-20261002-034900-27c2de` | `outputs/review/swap.mp4` (5 节点全绿 ok) | ~60s, ≈¥0.9 |
| 数字人口播 | `digital_human-20261002-035543-6f473c` | `outputs/review/digital_human-...-6f473c_sub.mp4` (TTS→H3→响度→软字幕) | ~3min, ≈¥0.8 |
| 自动创作 | `auto_content-20261002-041610-101c60` 等 | `outputs/review/auto_content-..._final.mp4` (768×1366 竖屏 11s, DeepSeek超时→模板降级→TTS→H3) | ~4min, ≈¥0.7 |

- 前端页面截图: `docs/evidence/`(studio/canvas/jobs/review/assets/schedules/status, 1440×900)
- API 调用记录: 秘塔 `POST /video_generation` + `GET /query/video_generation/{id}` 轮询至 `succeeded` → 下载 `task.content.url`; 官方站 `POST /v1/t2a_v2?GroupId=`。uvicorn 日志 `logs/orch_dev.log`。
- 费用量级: 单次任务 ¥1 以内(秘塔 ~¥0.09/秒); 本次验证总计 ≈¥5。

## 素材来源(公开渠道)

| 文件 | 来源 | 说明 |
|---|---|---|
| `assets/sources/obama_5s.mp4` | Wikimedia Commons `2016-06-25_President_Obama's_Weekly_Address.webm` | 美国政府作品, 公有领域(public domain); 截取讲话段 |
| `assets/images/unsplash_*.jpg` | Unsplash CDN | Unsplash License, 可商用人像参考图 |

## 路线图

- [x] 产品化 Web 工作台 v3 (Vue3+Vue Flow: 功能卡/素材库/任务/审核/定时/节点画布)
- [x] MiniMax 主链路跑通: H3 换脸 ✓ 数字人口播 ✓ TTS/克隆(官方站) ✓
- [x] 审核队列全链路: 产出→预览→通过/打回→定时/发布
- [x] 节点画布真实执行 + 状态染色 + 图模板保存/加载
- [ ] 定时任务跑通（cron 批量生成 + 定点发布, 接口已就绪待真实 cron 触发验证）
- [ ] 角色形象版本库完善（多 look 切换）
- [ ] MPT 容器化加入 compose（可选）
- [ ] 多平台分发（小红书/B站/视频号一键多发）
- [ ] ComfyUI 高级通道（自建 GPU 时启用 VACE 精修）
- [ ] DeepSeek 恢复后用回 LLM 文案（当前有模板降级兜底）

---
*README 随项目演进持续更新。*
