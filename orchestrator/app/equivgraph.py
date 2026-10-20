"""管线任务 ↔ 等效节点图 + 输入素材清单。

工作台三张卡背后仍是一条节点链; 这里按 config 生成等效图,
存进 job.params.graph 供任务详情「查看对应图」只读回放,
同时产出 inputs 清单(源视频/参考图/文案等)给任务与审核页做前后对照。
"""
from __future__ import annotations

from pathlib import Path

from . import config as C


def _rel(p) -> str:
    """绝对/项目相对路径 → 项目相对路径 (前端 /api/file 用)"""
    if not p:
        return ""
    p = Path(p)
    if not p.is_absolute():
        p = C.ROOT / p
    try:
        return str(p.resolve().relative_to(C.ROOT.resolve()))
    except ValueError:
        return str(p)


def _text(label, text):
    return {"label": label, "kind": "text", "text": text or ""}


def _file(label, kind, path):
    return {"label": label, "kind": kind, "path": _rel(path)}


# ---------------- 各管线的等效图 ----------------

def digital_human(text: str, character: str, look_path: str | None,
                  voice_id: str | None, emotion: str | None,
                  title: str | None) -> tuple[dict, list]:
    """文案→TTS→形象口播(H3)→(字幕/响度)→审核, 与 digital_human 管线同构"""
    post = C.section("digital_human").get("post", {})
    nodes = [
        {"id": "txt", "type": "material/text", "pos": [40, 300],
         "params": {"内容": text}},
        {"id": "role", "type": "material/character", "pos": [40, 60],
         "params": {"角色": character, "形象版本": look_path or ""}},
        {"id": "tts", "type": "model/tts_minimax", "pos": [400, 300],
         "params": {"音色ID": voice_id or "", "情绪": emotion or "neutral"}},
        {"id": "avatar", "type": "model/h3_avatar", "pos": [740, 120],
         "params": {}},
    ]
    links = [
        {"src": "txt", "src_slot": 0, "dst": "tts", "dst_slot": 0},
        {"src": "role", "src_slot": 0, "dst": "avatar", "dst_slot": 0},
        {"src": "tts", "src_slot": 0, "dst": "avatar", "dst_slot": 1},
    ]
    last, y = "avatar", 120
    if post.get("burn_subtitles"):
        nodes.append({"id": "sub", "type": "proc/subtitles",
                      "pos": [1060, 60], "params": {}})
        links += [{"src": last, "src_slot": 0, "dst": "sub", "dst_slot": 0},
                  {"src": "txt", "src_slot": 0, "dst": "sub", "dst_slot": 1}]
        last = "sub"
    if post.get("loudnorm"):
        nodes.append({"id": "ln", "type": "proc/loudnorm",
                      "pos": [1060 if last == "avatar" else 1360, 200],
                      "params": {}})
        links.append({"src": last, "src_slot": 0, "dst": "ln", "dst_slot": 0})
        last = "ln"
    nodes.append({"id": "out", "type": "output/review",
                  "pos": [1060 if last == "avatar" else 1700, 120],
                  "params": {"标题": title or ""}})
    links.append({"src": last, "src_slot": 0, "dst": "out", "dst_slot": 0})

    inputs = [_text("口播文案", text),
              _file("角色形象", "image", look_path),
              _text("音色", f"{character} · {voice_id or '默认音色'}")]
    return {"nodes": nodes, "links": links}, inputs


def video_transform(source, face=None, prompt: str = "",
                    title: str | None = None, body=None, cloth=None,
                    body_back=None, body_side=None,
                    refs=()) -> tuple[dict, list]:
    tip = prompt or ("把参考视频中的人物替换为参考图片中的人物，"
                     "保持动作、表情、场景和运镜一致")
    g = {"nodes": [
        {"id": "src", "type": "material/video", "pos": [40, 60],
         "params": {"文件": _rel(source)}},
        {"id": "face", "type": "material/image", "pos": [40, 330],
         "params": {"文件": _rel(face)}},
        {"id": "tip", "type": "material/text", "pos": [40, 590],
         "params": {"内容": tip}},
        {"id": "swap", "type": "model/h3_faceswap", "pos": [430, 180],
         "params": {}},
        {"id": "out", "type": "output/review", "pos": [780, 180],
         "params": {"标题": title or ""}},
    ], "links": [
        {"src": "src", "src_slot": 0, "dst": "swap", "dst_slot": 0},
        {"src": "face", "src_slot": 0, "dst": "swap", "dst_slot": 1},
        {"src": "tip", "src_slot": 0, "dst": "swap", "dst_slot": 2},
        {"src": "swap", "src_slot": 0, "dst": "out", "dst_slot": 0},
    ]}
    inputs = [_file("对标视频", "video", source),
              _file("目标人脸", "image", face or body),
              _file("身体参考(正面)", "image", body if face else None),
              _file("身体参考(背面)", "image", body_back),
              _file("身体参考(侧面)", "image", body_side),
              _file("服饰参考", "image", cloth)]
    inputs += [_file(f"追加参考{i + 1}", "image", r) for i, r in enumerate(refs or [])]
    inputs.append(_text("提示词", tip))
    return g, [i for i in inputs if i.get("path") or i.get("text")]


def auto_content(subject: str, script: str = "",
                 title: str | None = None) -> tuple[dict, list]:
    """主题→DeepSeek文案→TTS→DeepSeek画面词→H3→合成→审核"""
    g = {"nodes": [
        {"id": "topic", "type": "material/text", "pos": [40, 120],
         "params": {"内容": "主题: " + (subject or "")}},
        {"id": "llm", "type": "model/llm_deepseek", "pos": [400, 60],
         "params": {"任务": "script"}},
        {"id": "tts", "type": "model/tts_minimax", "pos": [760, 40],
         "params": {}},
        {"id": "llm2", "type": "model/llm_deepseek", "pos": [760, 260],
         "params": {"任务": "prompt"}},
        {"id": "h3", "type": "model/minimax_h3", "pos": [1120, 260],
         "params": {}},
        {"id": "mux", "type": "proc/mux_audio", "pos": [1460, 140],
         "params": {}},
        {"id": "out", "type": "output/review", "pos": [1790, 140],
         "params": {"标题": title or ""}},
    ], "links": [
        {"src": "topic", "src_slot": 0, "dst": "llm", "dst_slot": 0},
        {"src": "llm", "src_slot": 0, "dst": "tts", "dst_slot": 0},
        {"src": "llm", "src_slot": 0, "dst": "llm2", "dst_slot": 0},
        {"src": "llm2", "src_slot": 0, "dst": "h3", "dst_slot": 0},
        {"src": "h3", "src_slot": 0, "dst": "mux", "dst_slot": 0},
        {"src": "tts", "src_slot": 0, "dst": "mux", "dst_slot": 1},
        {"src": "mux", "src_slot": 0, "dst": "out", "dst_slot": 0},
    ]}
    inputs = [_text("主题", subject)]
    if script:
        inputs.append(_text("自定义文案", script))
    else:
        inputs.append(_text("文案", "由 DeepSeek 自动生成"))
    return g, inputs
