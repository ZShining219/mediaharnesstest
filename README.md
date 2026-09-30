# AI 传媒工作台

一个**独立、产品化、傻瓜式**的 AI 自媒体生产工具：**数字人口播**、**对标视频转换（换人/换衣/换背景）**、**自动化创作**，生成内容统一进**审核队列**，验收后自动发布到抖音等平台。

> 全部功能 = 网页上的固定操作卡片，不需要懂节点/工作流。
> 进阶操作有 **节点画布** 页签（ComfyUI 式节点连线视图，但节点是固定功能卡）。
> 选型决策详见 [docs/decisions.md](docs/decisions.md)，对标产品分析见 [docs/benchmarks.md](docs/benchmarks.md)。

## 产品形态

```
你的服务器 103.52.153.212 (Docker, 无GPU也够用)
└── aimf-app  Web 工作台 http://103.52.153.212:8800
      ├─ 工作台:    三张功能卡(数字人/视频转换/自动创作) + 素材上传
      ├─ 节点画布:  ComfyUI 式节点编辑器(litegraph.js), 节点类型由后端注册表驱动
      │             素材/模型调用/后处理/输出 四类18种节点, 类型化连线, 图即任务
      │             提交 → 后端拓扑执行 → 节点实时染色 → 产出进审核队列
      ├─ 素材库:    浏览器上传 视频/形象图/服装图/声音样本/BGM + 角色管理(传形象/克隆声音/换装)
      ├─ 审核队列:  预览 → 通过/打回 → 填标题/定时
      ├─ 发布:      social-auto-upload → 抖音(扫码登录,cookie持久化)
      └─ 定时任务:  config.yaml cron → 夜间批量生成/定点发布

推理引擎(全部托管 API, 按次付费, 零 GPU 部署)
  ├─ WaveSpeed AI   InfiniteTalk(图+音频→口播) / Wan2.2-Animate(换人) / Qwen-Image-Edit(换装)
  ├─ MiniMax        speech-2.8 情感TTS + 声音克隆 / H3 视频生成
  └─ MoneyPrinterTurbo (可选本地服务) 主题→自动成片
```

`ComfyUI` 保留为高级通道（config.yaml `backend: comfyui`），用于将来接入自建 GPU 做更精细的局部编辑——用户界面不变，普通使用完全不需要它。

## 节点画布（工作流引擎）

图即任务定义：`素材(视频/图片/音频/文本/角色形象)` → `模型(TTS/InfiniteTalk/Wan-Animate/图像编辑/H3)` → `后处理(音轨/BGM/字幕/响度/拼接)` → `输出(审核队列/存目录/发布到平台)`。

- 双击画布搜索添加节点；端口类型校验（video 不会接错 image 口）
- 图可保存为模板复用；运行时逐节点状态染色（黄=运行/绿=完成/红=失败/灰=跳过）
- 后端 `orchestrator/app/nodedefs.py` 是节点唯一注册表，加节点=加一个 `fn`

## 三条管线（等价便捷入口）

| 功能 | 操作 | 底层 |
|---|---|---|
| 数字人口播 | 选角色 + 粘文案 + 选情绪 → 生成 | MiniMax 克隆音色 TTS → InfiniteTalk 对口型 → 字幕/BGM/响度 |
| 视频转换 | 上传对标视频 + 选形象图 → 转换 | (可选)Qwen-Image-Edit 先换装 → Wan2.2-Animate 整人替换；animate2 模式提示词换背景 |
| 自动创作 | 填主题 → 生成 | MoneyPrinterTurbo 全链路 |

命令行同样可用：`python -m pipelines.digital_human.pipeline --text "..." --character default` 等。

## 部署

服务器已部署：`docker compose -p aimf` 于 `/opt/aimf`，容器 `aimf-app`，访问需 token：

```
http://103.52.153.212:8800/?token=<见服务器 .env ORCH_TOKEN>
```

重新部署（代码更新后）：

```bash
SSH_PASS=<服务器密码> uv run --with paramiko scripts/deploy_server.py
```

本地开发：`scripts/setup.sh` → `scripts/run_orchestrator.sh` → http://127.0.0.1:8800

## 待办授权清单（需要你操作）

| # | 事项 | 操作 |
|---|---|---|
| 1 | **WaveSpeed key**（最优先，承担数字人+视频转换） | wavespeed.ai 注册充值 → `.env` 填 `WAVESPEED_API_KEY`（服务器 `/opt/aimf/.env` 同步填，改后 `docker compose up -d --force-recreate`） |
| 2 | MiniMax key | `.env` 填 `MINIMAX_API_KEY`（+GroupID），用于情感 TTS/声音克隆/H3 |
| 3 | 抖音登录 | `ssh root@103.52.153.212` → `docker exec -it aimf-app sau douyin login --account main`，终端会出二维码，抖音 App 扫码 |
| 4 | 声音克隆 | Web 素材库上传 10s+ 干净录音 → 角色卡"克隆声音"按钮一键完成 |
| 5 | 形象照 | 角色卡"上传形象图"传一张清晰正面半身照 |
| 6 | 腾讯云 MPS（可选） | `.env` 填 `TENCENT_SECRET_ID/KEY` |
| 7 | MPT（可选） | 本地 `bash scripts/setup.sh --mpt`；或后续加到 compose |

## 目录结构

```
orchestrator/        编排器: FastAPI + 工作台UI + ComfyUI/MiniMax/WaveSpeed/MPT/sau 客户端
pipelines/           digital_human / video_transform / auto_content
services/            开源组件: social-auto-upload(已入镜像) / MoneyPrinterTurbo / ComfyUI
assets/              characters(形象looks+声音配置) / sources / garments / voices / bgm
outputs/             review → approved → published / failed / tmp
data/jobs.db         任务记录
docs/                decisions / cloud-gpu / douyin / minimax
scripts/             setup.sh / run_*.sh / deploy_server.py / cloud_comfyui_bootstrap.sh
Dockerfile           单容器产品镜像 (编排器 + sau + ffmpeg + chromium)
```

## 路线图

- [x] 产品化 Web 工作台（固定功能卡 + 上传 + 审核 + 发布）
- [x] WaveSpeed 托管推理接入（InfiniteTalk / Wan-Animate / Qwen-Image-Edit）
- [x] MiniMax TTS/克隆 API、Docker 化部署到你的服务器、token 保护
- [ ] 端到端首条数字人样片（待 WaveSpeed/MiniMax key）
- [ ] 定时任务跑通（cron 批量生成 + 定点发布）
- [ ] 角色形象版本库完善（多 look 切换）
- [ ] MPT 容器化加入 compose（可选）
- [ ] 多平台分发（小红书/B站/视频号一键多发）
- [ ] ComfyUI 高级通道（自建 GPU 时启用 VACE 精修）

---
*README 随项目演进持续更新。*
