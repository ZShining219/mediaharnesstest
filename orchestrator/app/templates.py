"""提示词模板库: data/prompt_templates.json (运行时数据, 不入库 git)"""
import json
import time

from . import config as C

TPL_FILE = C.ROOT / "data" / "prompt_templates.json"

DEFAULT_TEMPLATES = [
    {"name": "换人·保原内容", "text": "把参考视频中的人物替换为参考图中的人物，"
     "保持动作、表情、口型、场景和运镜完全一致，"
     "人物五官、发型、体型、着装与各参考图一致"},
    {"name": "换装·保原人物", "text": "保留原视频人物与动作不变，"
     "仅将服装替换为服饰参考图中的款式，布料质感与版型对齐参考图"},
]


def _load() -> list[dict]:
    if not TPL_FILE.exists():
        return []
    try:
        return json.loads(TPL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict]):
    TPL_FILE.parent.mkdir(parents=True, exist_ok=True)
    TPL_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def list_tpl() -> list[dict]:
    items = _load()
    if not items:
        items = [{**t, "created_at": int(time.time())} for t in DEFAULT_TEMPLATES]
        _save(items)
    return items


def upsert(name: str, text: str) -> list[dict]:
    name, text = name.strip(), text.strip()
    items = _load() or list_tpl()
    for t in items:
        if t.get("name") == name:
            t["text"] = text
            _save(items)
            return items
    items.append({"name": name, "text": text, "created_at": int(time.time())})
    _save(items)
    return items


def delete(name: str) -> list[dict]:
    items = [t for t in _load() if t.get("name") != name]
    _save(items)
    return items
