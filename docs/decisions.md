# 技术选型决策记录

> 调研日期: 2026-09-30；v2 修订: 同日 (用户反馈 + 服务器环境确认)。
> 原则: 优先复用成熟开源工程，自建只做胶水层；产品要傻瓜式，推理走托管 API。

## v2 架构修订 (2026-09-30)

**环境事实**: 本机 Mac M4 16GB；服务器 103.52.153.212 为 4核/4GB/**无 GPU** 的小 VPS (有 Docker、公网 IP，已运行其他业务)。
两者均无法本地跑视频扩散模型。

**用户反馈**: ComfyUI 对用户太重 —— 它不是给使用者的界面。结论:
**ComfyUI 只作为可选的自建 GPU 推理后端，产品前端是我们自己的傻瓜式 Web 工作台。**

**推理引擎改为托管 API** (按次付费，零部署，国内可直连):

| 环节 | 托管 API | 模型 |
|---|---|---|
| 音频→口播视频 | WaveSpeed `wavespeed-ai/infinitetalk` (含 fast/multi) | InfiniteTalk 开源模型的托管版 |
| 对标视频换人(脸+衣) | WaveSpeed `wavespeed-ai/wan-2.2/animate` mode=replace | Wan2.2-Animate |
| 动作迁移+换背景 | WaveSpeed `wavespeed-ai/wan-2.2/animate-2` (prompt 控背景) | Wan2.2-Animate-2 |
| 换装/换发型(图片) | WaveSpeed `wavespeed-ai/qwen-image/edit-plus` | Qwen-Image-Edit-2509 |
| 情感 TTS/声音克隆 | MiniMax `t2a_v2` / `voice_clone` | speech-2.8-hd |
| 备选 | MiniMax H3 视频生成 / fal.ai 同族模型 / 阿里云 wan2.2-animate-mix | |

**关键洞察**: Wan2.2-Animate `replace` 模式是"把参考图里整个人换进视频、保留动作场景"——
所以"换脸+换衣服"= 先用图像编辑模型把形象照改成目标造型 → 整人替换，一条 API 链路完成。

**关于 speech2speech**: 按名字检索 GitHub，该项目族均为"实时语音对话 pipeline"
(VAD→STT→LLM→TTS，如 huggingface/speech-to-speech)，方向是**交互式语音助手**，
与本需求(输入文字→有感情朗读→口播视频)不同，未采用。
最接近"产品化数字人"的开源成品是 Linly-Talker / HeyGem.ai / metahuman-stream，
但均需 GPU，故数字人链路用托管 InfiniteTalk 实现同等能力。待用户确认其所指项目后再评估。

## 总体架构(v2)

```
服务器 103.52.153.212 (Docker, 无GPU)
└─ aimf-app: FastAPI 编排器 + 傻瓜式Web工作台 + 审核队列 + APScheduler + sau发布
       │ HTTP API 调用
       ├─ WaveSpeed AI: InfiniteTalk 口播 / Wan2.2-Animate 换人 / Qwen-Edit 换装
       ├─ MiniMax: speech-2.8 TTS / voice_clone / H3
       └─ (可选) 云端 ComfyUI: VACE 精修通道

本机 Mac: 开发 + 同一套代码本地可跑 (scripts/run_orchestrator.sh)
```

## v1 备选架构 (自建 GPU 通道, 保留)

当需要更精细的局部编辑(VACE 遮罩级)、或不想按次付费时，可在 GPU 服务器上部署
ComfyUI 作为推理引擎，编排器通过 `COMFYUI_BASE_URL` 调用 —— 对用户仍然透明。

```
┌─────────────────────────── 本机 (Mac M4, 编排/审核/上传) ───────────────────────────┐
│  orchestrator (FastAPI + 审核页 :8800)                                              │
│    ├── pipelines: digital_human / video_transform / auto_content                  │
│    ├── APScheduler 定时任务            ┌──────────────┐                           │
│    └── publisher ──────────────────▶ │ social-auto  │ 抖音/小红书/B站/视频号      │
│                                       │ -upload(sau) │ (Playwright+cookie)        │
│                                       └──────────────┘                           │
└──────────────┬───────────────────────────────┬────────────────────────────────────┘
               │ HTTP                          │ HTTP
   ┌───────────▼───────────┐      ┌────────────▼─────────────┐      ┌─────────────┐
   │ ComfyUI (云端GPU 24G+) │      │ MiniMax API              │      │ MPT 本地服务 │
   │ InfiniteTalk 口播数字人 │      │ H3 视频生成               │      │ 脚本→成片    │
   │ Wan2.2-VACE 换装换背景 │      │ speech-2.8 TTS+克隆       │      │ WebUI+API   │
   │ Qwen-Image-Edit 换装   │      │ image/LLM                 │      └─────────────┘
   └───────────────────────┘      └──────────────────────────┘
```

本机 16GB 内存无法跑视频扩散模型 (Wan2.x 14B 需 ≥24G 显存，GGUF 量化后也吃显存/速度)，
因此推理一律走 **云端 GPU ComfyUI** 或 **MiniMax API**，本机只做编排、审核、后处理、发布。

## 数字人方案

需求: 固定人物图片规范形象 → 可换装换发型 → 按文本有感情地朗读(非交互) → 替代本人出镜。

| 环节 | 选型 | 备选 | 理由 |
|---|---|---|---|
| 音频→口型视频 | **InfiniteTalk** (MeiGen-AI) | HunyuanVideo-Avatar、Hallo3、EchoMimicV2、SadTalker | 图+音频→无限长口播视频，嘴唇+头部+身体姿态+表情同驱动，身份一致性好；官方 ComfyUI 支持+GGUF 低显存；中文 wav2vec2 有现成工作流 |
| 云端零部署路径 | **MiniMax-H3** reference/first-frame 视频生成 | 腾讯数智人 SaaS、HeyGen API | H3 支持多模态输入(图/文/音频)，用户已有额度；口型精度不如 InfiniteTalk，适合氛围镜头/备用 |
| 情感朗读 TTS | **MiniMax speech-2.8-hd** | IndexTTS-2.5(B站，情绪向量/参考音频，开源首选备选)、CosyVoice3 | 已有 API 额度；emotion 参数 + voice_clone 克隆本人声音 + 300+ 系统音色 |
| 形象一致性/换装换发型 | **图像编辑模型**: Qwen-Image-Edit-2509 / Flux Kontext (ComfyUI) | RefVTON(CVPR2026 虚拟试穿 LoRA)、opentryon SDK、Nano Banana API | 固定底图 + "换成XX衣服/XX发型" 编辑出 looks/*.png 版本库，与口播管线解耦 |

数字人形态说明: 本项目采用 **"形象照 + 情感TTS + 音频驱动视频"** 路线（2D 生成式数字人），
不采用 3D 建模/驱动路线（成本高、周期长，适合实时交互场景而非内容生产）。

## AI 视频工作流

| 需求 | 选型 | 说明 |
|---|---|---|
| 可视化图形操作界面 | **ComfyUI** | 节点式工作流即"可视化操作页面"，Web 端，社区生态最大；API 化后可被编排器调度 |
| 对标视频换脸/换衣/换背景 | **Wan2.2-VACE(-Fun) + Phantom** | VACE: 视频局部重绘/参考迁移/运动保持单模型搞定；Phantom LoRA 解决跨帧脸部/服装漂移；点选式遮罩 + 姿态迁移 |
| 脸部精修(可选二级) | ReActor / PuLID / FaceFusion | VACE 出片后脸部细节不够时过一帧级换脸 |
| 云端算力 | 腾讯云(云函数一键 ComfyUI / HAI GPU) 或 AutoDL | 用户已有腾讯云；bootstrap 脚本见 docs/cloud-gpu.md |
| 腾讯云 MPS | 转码/智能字幕/封面/审核 可选后处理 | 计费接口，.env 填密钥后可用 |

## 自动化创作与剪辑

| 需求 | 选型 | 说明 |
|---|---|---|
| 主题→成片(教程/科普) | **MoneyPrinterTurbo** (84K★) | WebUI+API+CLI；AI 写稿(支持 MiniMax LLM)、素材(Pexels/AI生成含 MiniMax-H3)、TTS、字幕、BGM 全链路 |
| 精剪扩展 | pyJianYingDraft | 程序化生成剪映草稿；注意 Mac 不支持自动导出，导出需 Windows 剪映 |
| 审核→发布 | **social-auto-upload** (13K★) | `sau` CLI；抖音扫码登录存 cookie，支持定时发布；抖音开放平台 API 需企业资质故不采用 |

## 审核/调度层

**自建轻量编排器** (orchestrator/): FastAPI + 单页审核界面 + SQLite 任务记录 + APScheduler。
理由: 这是把各开源组件串成"生成→审核→发布"流水线的胶水层，通用框架(n8n 等)反而更重；
代码量小且完全可控。

## 半自动化闭环

```
生成(定时任务/手动) → outputs/review/ → 审核页预览 →
  通过 → outputs/approved/ → sau 发布(立即或定时) → outputs/published/
  打回 → outputs/failed/
```

前期: 人工调提示词 + 逐条验收; 稳定后: cron 定时生成 + 只做验收 + 定时发布。
