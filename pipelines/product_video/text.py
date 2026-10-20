"""文案节奏清洗：把 LLM 的慢动作措辞改成快节奏，但保留否定句。

例如：
- "镜头缓慢推近" -> "镜头快速推近"
- "禁止慢速推拉" -> 保持不变（不能改成"禁止快速推拉"）
"""
import re

_MAP = {
    "轻微推进": "快速推进",
    "轻微推拉": "快速推拉",
    "慢动作": "正常速度",
    "慢速": "快速",
    "缓慢": "快速",
    "缓缓": "快速",
    "慢慢": "快速",
}

# 否定词 + 最多 10 个非标点字符，视为否定语境，保留原词
_NEG = re.compile(
    r"(禁止|不要|避免|杜绝|别|无需|不出现|不含|不能|不得|无)"
    r"[^，。；,.;]{0,10}$")
_RE = re.compile("|".join(map(re.escape, _MAP)))


def fast_text(s) -> str:
    text = str(s or "")
    # 修复旧版本可能产生的语义反转
    text = text.replace("禁止正常速度", "禁止慢速")
    text = text.replace("不要正常速度", "不要慢速")

    def repl(m):
        prefix = text[max(0, m.start() - 18):m.start()]
        if _NEG.search(prefix):
            return m.group(0)
        return _MAP[m.group(0)]

    return _RE.sub(repl, text)
