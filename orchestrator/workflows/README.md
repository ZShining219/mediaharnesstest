# ComfyUI 工作流模板

本目录存放 ComfyUI **API 格式** 导出的工作流 JSON 以及对应的参数补丁映射。

## 工作流模板 (.json)

在 ComfyUI 网页里搭好流程后:
1. 右上角菜单 → `工作流` → `导出(API 格式)` (需先在设置里开启 Dev Mode)
2. 保存到本目录, 命名如 `digital_human_infinitetalk.json`

## 参数补丁映射 (.map.yaml)

同名 `.map.yaml` 定义管线如何把运行时参数注入节点:

```yaml
patches:
  # match 三选一: id(节点编号) / title(节点标题) / class_type(唯一时)
  - match: {id: "6"}
    inputs: {text: "$PROMPT"}
  - match: {title: "加载参考图"}
    inputs: {image: "$PORTRAIT"}
  - match: {class_type: "LoadAudio"}
    inputs: {audio: "$AUDIO"}
```

`$XXX` 变量由管线注入, 各管线支持的变量:

| 管线 | 变量 |
|---|---|
| digital_human | `$PORTRAIT` 形象图, `$AUDIO` 语音, `$PROMPT` 提示词 |
| video_transform | `$SOURCE` 源视频, `$FACE` 人脸, `$CLOTH` 服装, `$BG` 背景, `$MASK` 遮罩, `$PROMPT` |

查看某模板的节点列表(帮你写映射):

```bash
curl http://127.0.0.1:8800/api/workflows/<模板名>/inspect
```

## 推荐工作流配方

### digital_human_infinitetalk — 数字人口播
- 自定义节点: `ComfyUI-WanVideoWrapper`(kijai) 或官方 `WanInfiniteTalkToVideo`,
  `ComfyUI-VideoHelperSuite`, `ComfyUI-GGUF`, `ComfyUI-KJNodes`
- 模型: Wan2.1-I2V-14B-480p(GGUF Q8 推荐) + InfiniteTalk_Single +
  wav2vec2-chinese-base + Wan2.1 VAE + umt5-xxl + clip-vision + lightx2v LoRA
- 输入: 参考图 + 音频 -> 输出: 对口型说话视频(支持超长)
- 参考实现: github.com/boat2moon/infinitetalk-comfyui-workflow

### video_vace_transform — 换脸/换衣/换背景
- 自定义节点: `ComfyUI-WanVideoWrapper` / 官方 VACE 节点, `comfyui_controlnet_aux`,
  `ComfyUI-segment-anything-2`(遮罩), `ComfyUI-VideoHelperSuite`
- 模型: Wan2.2-VACE-Fun-A14B(GGUF Q5/FP8) + Phantom-Wan(人物/服装一致性 LoRA)
- 输入: 源视频 + 遮罩 + 参考图(脸/衣/背景) + 动作控制(源视频姿态)
- 参考: docs.comfy.org/tutorials/video/wan/vace

### portrait_edit — 数字人换装/换发型 (可选)
- 模型: Qwen-Image-Edit-2509 或 FLUX.1-Kontext (GGUF 可跑低显存)
- 输入: 当前形象图 + 编辑提示词("换成红色卫衣" "换成齐肩短发")
