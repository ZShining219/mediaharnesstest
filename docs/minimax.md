# MiniMax API 速查

封装见 `orchestrator/app/minimax.py`。v3 起分两条线路：

## 线路一: 秘塔 Metaso 代理 (视频生成, 默认)

- `MINIMAX_BASE_URL=https://metaso.cn/api/minimax/v2`, key 为 `mk-` 开头
- **只代理视频接口**（`t2a_v2` 等返回 404），TTS 必须走官方站
- 新版多模态接口（不是旧 `subject_reference` 写法）：

```
POST {base}/video_generation
{"model": "MiniMax-H3",
 "content": [
   {"type": "text", "text": "提示词"},
   {"type": "video_url", "video_url": {"url": ...}, "role": "reference_video"},
   {"type": "image_url", "image_url": {"url": ...}, "role": "reference_image"},
   {"type": "audio_url", "audio_url": {"url": ...}, "role": "reference_audio"}],
 "resolution": "768P",     # 480p / 512p / 768P / 2K
 "duration": 6,            # 4-15 秒
 "ratio": "adaptive",      # adaptive / 9:16 / 16:9 / 1:1
 "aigc_watermark": false}
→ {"task_id": "..."}

GET {base}/query/video_generation/{task_id}
→ {"task": {"status": "succeeded", "content": {"url": "https://..."}, "usage": {...}}}
```

- `url` 接受 http(s) 或 `data:` base64 URI（本地文件自动转 data URI 提交）
- 计费约 ¥0.09/秒(输入+输出时长)，单次几毛钱级

## 线路二: 官方站 (TTS / 声音克隆)

- `MINIMAX_API_KEY_OFFICIAL` (sk- key) + `MINIMAX_BASE_URL_OFFICIAL=https://api.minimax.cn/v2`
- **所有请求必须带 `GroupId` 查询参数（空值也可以）**——实测不传会返回"余额不足"误报
- TTS: `POST /v1/t2a_v2`（注意是 v1 路径），`output_format:"hex"` 返回音频 hex
- 声音克隆: `/v1/files/upload` (purpose=voice_clone) + `/v1/voice_clone`

```python
from orchestrator.app.minimax import Minimax
mm = Minimax()            # 秘塔: 视频生成
mm2 = Minimax.official()  # 官方站: TTS/克隆

mm.video_generate([mm.part_text("..."), mm.part_image("assets/images/x.jpg")])
mm.video_wait_download(tid, Path("out.mp4"))
mm2.tts("文案", voice_id="female-shaonv", out_path=Path("a.mp3"), emotion="happy")
mm2.clone_voice(Path("assets/voices/my_voice.wav"), voice_id="zfh_main")
```

## 配额注意

- TTS: 按字符计费，同步接口单次 ≤10000 字
- H3 视频: 按条/秒计费，成片 4-15s
- 声音克隆: 免费额度有限次/日; 克隆出的 voice_id 7 天不用会被清
