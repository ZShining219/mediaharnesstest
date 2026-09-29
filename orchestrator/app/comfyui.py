"""ComfyUI HTTP API 客户端 + 工作流模板参数注入。

用法:
    client = ComfyUI()
    prompt = load_workflow("digital_human_infinitetalk")
    prompt = apply_patches(prompt, [
        {"match": {"title": "加载参考图"}, "inputs": {"image": "portrait.png"}},
        {"match": {"id": "12"},           "inputs": {"value": 480}},
    ])
    pid = client.submit(prompt)
    files = client.wait_and_collect(pid)
"""
import json
import time
import uuid
from pathlib import Path

import httpx
import yaml

from . import config as C


class ComfyUIError(RuntimeError):
    pass


class ComfyUI:
    def __init__(self, base_url: str | None = None, timeout: float = 60):
        self.base = (base_url or C.COMFYUI_BASE_URL).rstrip("/")
        auth = None
        if C.COMFYUI_AUTH and ":" in C.COMFYUI_AUTH:
            user, pw = C.COMFYUI_AUTH.split(":", 1)
            auth = httpx.BasicAuth(user, pw)
        self.http = httpx.Client(base_url=self.base, timeout=timeout, auth=auth,
                                 headers={"Authorization": f"Bearer {C.COMFYUI_AUTH}"}
                                 if C.COMFYUI_AUTH and ":" not in C.COMFYUI_AUTH else {})

    def health(self) -> bool:
        try:
            return self.http.get("/system_stats").status_code == 200
        except httpx.HTTPError:
            return False

    def upload(self, path: Path, overwrite: bool = True) -> str:
        """上传素材到 ComfyUI input 目录, 返回服务端文件名。
        图片/视频/音频统一走 /upload/image 端点(ComfyUI 内部并不校验格式)。"""
        with open(path, "rb") as f:
            r = self.http.post("/upload/image",
                               files={"image": (path.name, f)},
                               data={"overwrite": str(overwrite).lower()})
        r.raise_for_status()
        name = r.json().get("name", path.name)
        sub = r.json().get("subfolder")
        return f"{sub}/{name}" if sub else name

    def submit(self, prompt: dict) -> str:
        r = self.http.post("/prompt", json={
            "prompt": prompt,
            "client_id": uuid.uuid4().hex,
        })
        if r.status_code != 200:
            raise ComfyUIError(f"submit failed {r.status_code}: {r.text[:500]}")
        data = r.json()
        if "error" in data:
            raise ComfyUIError(json.dumps(data["error"], ensure_ascii=False))
        return data["prompt_id"]

    def history(self, prompt_id: str) -> dict:
        return self.http.get(f"/history/{prompt_id}").json().get(prompt_id, {})

    def wait_and_collect(self, prompt_id: str, timeout: float = 3600,
                         poll: float = 3.0) -> list[dict]:
        """轮询直到完成, 返回输出文件描述列表 [{filename,subfolder,type,node}]"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            h = self.history(prompt_id)
            if h:
                status = h.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIError(
                        json.dumps(status.get("messages", h), ensure_ascii=False)[:800])
                if status.get("completed") or status.get("status_str") == "success" or h.get("outputs"):
                    return self._outputs(h)
            time.sleep(poll)
        raise ComfyUIError(f"prompt {prompt_id} timeout after {timeout}s")

    def _outputs(self, history_entry: dict) -> list[dict]:
        out = []
        for node_id, node_out in (history_entry.get("outputs") or {}).items():
            for key in ("images", "gifs", "videos", "audio"):
                for f in node_out.get(key, []) or []:
                    out.append({**f, "node": node_id})
        return out

    def download(self, fdesc: dict, dst: Path) -> Path:
        r = self.http.get("/view", params={
            "filename": fdesc["filename"],
            "subfolder": fdesc.get("subfolder", ""),
            "type": fdesc.get("type", "output"),
        })
        r.raise_for_status()
        dst.write_bytes(r.content)
        return dst


# ---------------- workflow templates ----------------

def load_workflow(name: str) -> dict:
    """加载 orchestrator/workflows/<name>.json (ComfyUI 'Save (API Format)' 导出)"""
    p = C.WORKFLOWS_DIR / f"{name}.json"
    if not p.exists():
        raise ComfyUIError(
            f"workflow 模板不存在: {p}\n"
            f"请先在 ComfyUI 界面搭好流程并用 '导出(API格式)' 保存到该目录, "
            f"详见 orchestrator/workflows/README.md")
    return json.loads(p.read_text(encoding="utf-8"))


def load_patch_map(name: str) -> list[dict]:
    """加载 orchestrator/workflows/<name>.map.yaml 补丁规则"""
    p = C.WORKFLOWS_DIR / f"{name}.map.yaml"
    if not p.exists():
        return []
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("patches", [])


def apply_patches(prompt: dict, patches: list[dict],
                  variables: dict[str, str] | None = None) -> dict:
    """按 match(id/title/class_type) 定位节点并覆盖 inputs。
    inputs 值中 "$VAR" 会被 variables[VAR] 替换。"""
    variables = variables or {}
    for patch in patches:
        match = patch.get("match", {})
        node = _find_node(prompt, match)
        if node is None:
            raise ComfyUIError(f"patch 未匹配到节点: {match}")
        for k, v in (patch.get("inputs") or {}).items():
            if isinstance(v, str) and v.startswith("$"):
                v = variables.get(v[1:], v)
            node["inputs"][k] = v
    return prompt


def _find_node(prompt: dict, match: dict):
    by_class = []
    for nid, node in prompt.items():
        meta = node.get("_meta", {})
        if match.get("id") and str(nid) == str(match["id"]):
            return node
        if match.get("title") and meta.get("title") == match["title"]:
            return node
        if match.get("class_type") and node.get("class_type") == match["class_type"]:
            by_class.append(node)
    if match.get("class_type") and len(by_class) == 1:
        return by_class[0]
    return None


def inspect_workflow(name: str) -> list[dict]:
    """列出模板中所有节点, 便于编写 map.yaml"""
    prompt = load_workflow(name)
    return [{"id": nid, "title": n.get("_meta", {}).get("title"),
             "class_type": n.get("class_type"), "inputs": n.get("inputs")}
            for nid, n in prompt.items()]
