# 云端 GPU ComfyUI 部署指南

本机 Mac M4 (16GB) 跑不动 Wan2.x 视频模型，数字人/视频转换的推理需云端 GPU。
编排器通过 `COMFYUI_BASE_URL` 远程调用，本机零负担。

## 方案对比

| 方案 | 优点 | 缺点 | 适用 |
|---|---|---|---|
| 腾讯云云函数 SCF「ComfyUI 应用」 | 一键部署、Serverless 按需计费、你在用腾讯云 | GPU 型号受限、冷启动 | 间歇任务首选 |
| 腾讯云 HAI / CVM GPU | 完整控制、可随时开关机 | 按量/包月计费 | 高频/批量 |
| AutoDL / 仙宫云等 | 便宜、按分钟计费、社区镜像多 | 需另注册平台 | 预算敏感 |
| RunningHub/Liblib 在线 ComfyUI | 免部署直接画工作流 | 排队、按次计费 | 先验证工作流再自部署 |

推荐先用 **RunningHub 等在线 ComfyUI** 把工作流跑通并导出 JSON(免费/低成本)，
再决定是否在腾讯云自部署常驻实例。

## 自部署步骤 (腾讯云 HAI/CVM Ubuntu)

1. 购买 GPU 实例: 建议 **L20 / RTX 4090 级 ≥24GB 显存**
   (InfiniteTalk/VACE GGUF Q8/Q5 在 24-32G 可跑; 14B fp16 需 ≥40G)
2. `nvidia-smi` 确认驱动可用
3. 上传并执行:
   ```bash
   scp scripts/cloud_comfyui_bootstrap.sh root@<IP>:~/
   ssh root@<IP> 'bash cloud_comfyui_bootstrap.sh'
   ```
   脚本会装 ComfyUI + 所需自定义节点 + 下载模型(约 40-60GB)。
   **国内机器建议先设 HF 镜像**: `export HF_ENDPOINT=https://hf-mirror.com`
4. 启动: `python main.py --listen 0.0.0.0 --port 8188`
5. **安全**: 不要裸奔 8188 到公网。用 Nginx/Caddy 加 basic auth，
   然后在本机 .env 填 `COMFYUI_AUTH=user:pass`，
   `COMFYUI_BASE_URL=https://comfyui.你的域名`。
   更稳妥: SSH 隧道 `ssh -L 8188:127.0.0.1:8188 root@<IP>` 走本地地址。

## 工作流搭建(可视化操作)

1. 浏览器打开 `http://<IP>:8188`
2. 拖入工作流参考:
   - 数字人: github.com/boat2moon/infinitetalk-comfyui-workflow (InfiniteTalk 中文口播现成模板)
   - 视频转换: docs.comfy.org/tutorials/video/wan/vace (VACE 官方示例)
3. 调好后 `导出(API格式)` 存到 `orchestrator/workflows/<名字>.json`
4. 写同名 `<名字>.map.yaml` 参数映射(变量见 workflows/README.md)
   - `curl http://127.0.0.1:8800/api/workflows/<名字>/inspect` 可列出节点方便写映射
5. config.yaml 中指定 workflow 名即可被管线调用

## 成本参考

- AutoDL 4090(24G): 约 ¥2-3/小时; 生成一条 10s 口播视频约 5-15 分钟
- 腾讯云 L20: 按量约 ¥10+/小时; SCF serverless 按调用计费适合低频
- MiniMax-H3 API: 按秒/条计费，零部署成本，适合先跑通流程
