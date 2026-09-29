# MiniMax API 速查

控制台: https://platform.minimaxi.com (国内) / https://platform.minimax.io (海外)
本项目封装见 `orchestrator/app/minimax.py`。

## 已封装能力

| 能力 | 接口 | 模型/参数 | 用途 |
|---|---|---|---|
| TTS | POST /v1/t2a_v2 | speech-2.8-hd / speech-2.6-hd | 数字人配音, emotion=happy/sad/angry/fear/disgust/surprise/neutral |
| 声音克隆 | /v1/files/upload + /v1/voice_clone | 10s-5min 样本音频 | 克隆本人声音做专属音色; 7天不用会被清 |
| 视频生成 | /v1/video_generation + /v1/query/video_generation + /v1/files/retrieve | MiniMax-H3 | 参考图生视频/首尾帧/文生视频, 768P-2K, 4-15s |

MiniMax-H3 多模态视频生成: 支持 text / image / first-last-frame / **reference** 输入。
`subject_reference` 可锁定人物形象一致性 —— 也是"固定人物图片规范数字人"的 API 路线。

## 首次设置

```bash
# .env
MINIMAX_API_KEY=你的key
MINIMAX_BASE_URL=https://api.minimaxi.com
MINIMAX_GROUP_ID=控制台-账户信息里的GroupID
```

## 克隆声音流程

```python
from orchestrator.app.minimax import Minimax
mm = Minimax()
mm.clone_voice(Path("assets/voices/my_voice.wav"), voice_id="zfh_main")
# 然后把 "zfh_main" 写入 assets/characters/default/config.json 的 voice_id
```

或直接 TTS 用系统音色: 300+ 内置 voice_id 见控制台"声音列表"。

## 配额注意

- TTS: 按字符计费，同步接口单次 ≤10000 字
- H3 视频: 按条/秒计费，成片 4-15s
- 声音克隆: 免费额度有限次/日
