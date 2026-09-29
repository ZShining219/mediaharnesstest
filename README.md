# AI 传媒工作流

基于开源组件搭建的个人 AI 自媒体生产流水线：**数字人口播**、**对标视频转换(换脸/换衣/换背景)**、**自动化创作**，统一经 **审核队列** 后自动发布到抖音等平台。

> 选型决策与对比详见 [docs/decisions.md](docs/decisions.md)。

## 架构

```
本机 (Mac, 编排/审核/后处理/上传)
  orchestrator  FastAPI + 审核页 http://127.0.0.1:8800
    ├─ pipelines/digital_human   文案→情感TTS→口型视频→字幕BGM→审核
    ├─ pipelines/video_transform 对标视频+参考图→VACE 转换→审核
    ├─ pipelines/auto_content    主题→MoneyPrinterTurbo 成片→审核
    ├─ APScheduler 定时任务 (config.yaml)
    └─ publisher → social-auto-upload (sau) → 抖音/小红书/B站/视频号

算力 (二选一或混用)
  ComfyUI 云端GPU ≥24G   InfiniteTalk 口播 / Wan2.2-VACE 视频编辑 / Qwen-Image-Edit 换装
  MiniMax API            H3 视频生成 / speech-2.8 情感TTS+声音克隆 (零部署)
```

复用的开源工程（`services/`，不要重复造轮子）：

| 组件 | 用途 | 说明 |
|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 可视化工作流页面 | 你要的"图形操作页面"就是它，节点式可调可控 |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 自动化成片 | WebUI+API，AI 写稿/素材/字幕/BGM 全链路 |
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | 多平台发布 | `sau` CLI，抖音扫码登录 + 定时发布 |

## 快速开始

```bash
bash scripts/setup.sh                 # 装编排器 + sau + 克隆组件
cp .env.example .env                  # 填 MINIMAX_API_KEY 等
cp config.example.yaml config.yaml    # 按需调整
scripts/run_orchestrator.sh           # 打开 http://127.0.0.1:8800
```

页面功能：**审核队列**(预览/通过/打回/填标题定时发布) · **提交任务** · **任务记录** · **待发布** · **服务状态**。

## 三条管线

### 1. 数字人口播
```
文案 → MiniMax TTS(克隆音色+情绪) → InfiniteTalk(图+音频→口型视频) → 字幕/响度/BGM → 审核
```
```bash
.venv/bin/python -m pipelines.digital_human.pipeline \
  --text "大家好，今天分享三个效率工具" --character default --emotion happy --tags AI,效率
```

### 2. 对标视频转换（换脸/换衣/换背景）
```
舞蹈视频 + 人脸/服装/背景参考图 → ComfyUI VACE 工作流 → 审核
```
```bash
.venv/bin/python -m pipelines.video_transform.pipeline \
  --source assets/dance.mp4 --face assets/characters/default/looks/default.png \
  --cloth assets/garments/red_dress.jpg --prompt "现代都市夜景，年轻女性街舞"
```

### 3. 自动化创作（教程/科普类）
```bash
.venv/bin/python -m pipelines.auto_content.pipeline --subject "Kimi 用法教程"
# 需先启动 MPT: cd services/MoneyPrinterTurbo && uv run python main.py
```

审核通过 → `outputs/approved/` → sau 发布（立即或 `--schedule` 定时）→ `outputs/published/`。
稳定后开 `config.yaml` 的 `schedules.jobs` 即可只做验收。

## 待办授权清单（需要你操作）

| # | 事项 | 操作 |
|---|---|---|
| 1 | MiniMax API | `.env` 填 `MINIMAX_API_KEY`（+`MINIMAX_GROUP_ID`） |
| 2 | 抖音登录 | `services/social-auto-upload/.venv/bin/sau douyin login --account main` 扫码 |
| 3 | 云端 GPU ComfyUI | 见 [docs/cloud-gpu.md](docs/cloud-gpu.md)；或先用 RunningHub 在线版验证工作流 |
| 4 | 本人声音样本 | 10s–5min 干净录音 → `assets/voices/`；调 `Minimax.clone_voice` 得 voice_id 写入 `assets/characters/default/config.json` |
| 5 | 人物照片 | 清晰正面半身照 → `assets/characters/default/looks/default.png`；更多参考放 `refs/` |
| 6 | ComfyUI 工作流 | 云端搭好后"导出API格式"存 `orchestrator/workflows/` 并配 `.map.yaml`（见该目录 README） |
| 7 | 腾讯云 MPS（可选） | `.env` 填 `TENCENT_SECRET_ID/KEY` 启用转码/智能字幕 |
| 8 | MPT（可选） | `bash scripts/setup.sh --mpt`；`config.toml` 里 LLM 可填 MiniMax key |

## 目录结构

```
orchestrator/        编排器: FastAPI 审核/提交/调度 + ComfyUI/MiniMax/MPT/sau 客户端
  workflows/         ComfyUI API格式工作流模板 + 参数映射 (.map.yaml)
pipelines/           三条管线 (digital_human / video_transform / auto_content)
services/            克隆的开源组件 (gitignore)
assets/              characters(形象+声音配置) / garments / bgm / scripts / voices
outputs/             review → approved → published / failed, tmp 中间产物
docs/                decisions / cloud-gpu / douyin / minimax
scripts/             setup.sh, run_*.sh, cloud_comfyui_bootstrap.sh
data/jobs.db         任务记录 (sqlite)
```

## 路线图

- [x] 编排器 + 审核页 + 三条管线骨架
- [x] MiniMax TTS/克隆/视频 API 封装，sau 发布封装
- [ ] 云端 ComfyUI 部署 + 工作流模板导入验证（待 GPU 资源）
- [ ] 数字人换装/换发型管线（Qwen-Image-Edit 模板 + `looks/` 版本管理）
- [ ] VACE 工作流模板调优（遮罩策略/Phantom 权重）
- [ ] pyJianYingDraft 剪映草稿生成（教程类精剪）
- [ ] 审核通过→多平台分发（小红书/B站/视频号）
- [ ] IndexTTS-2.5 本地 TTS 引擎接入（开源备选）

---
*README 随项目演进持续更新。*
