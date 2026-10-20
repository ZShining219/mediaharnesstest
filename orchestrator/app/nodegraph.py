"""节点图执行引擎 —— ComfyUI 式:

前端提交的图 JSON:
  {"nodes":[{"id","type","pos":[x,y],"params":{...}}],
   "links":[{"id","src","src_slot","dst","dst_slot"}]}
执行: 校验 → 拓扑排序 → 逐节点执行 → 输出节点落产物。
运行期通过 store.job_update 回写 node_status, 前端实时染色。
"""
from __future__ import annotations

import time
from pathlib import Path

from . import config as C
from . import nodedefs, store


class GraphError(RuntimeError):
    pass


def _in_name(n: str) -> str:
    return n.lstrip("?")


def _optional(n: str) -> bool:
    return n.startswith("?")


def topo_order(nodes: dict, links: list[dict]) -> list[str]:
    """Kahn 拓扑排序; 有环则报错"""
    deg = {nid: 0 for nid in nodes}
    adj = {}
    for l in links:
        s, d = l["src"], l["dst"]
        deg[d] = deg.get(d, 0) + 1
        adj.setdefault(s, []).append(d)
    queue = [nid for nid, d in deg.items() if d == 0]
    order = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in adj.get(cur, []):
            deg[nxt] -= 1
            if deg[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(nodes):
        raise GraphError("图中存在循环依赖")
    return order


def graph_inputs(graph: dict) -> list[dict]:
    """从图的素材节点提取「输入素材清单」, 供任务详情/审核页做前后对照"""
    kind_map = {"material/video": "video", "material/image": "image",
                "material/audio": "audio"}
    out = []
    for n in graph.get("nodes", []):
        t = n.get("type")
        if t not in nodedefs.REGISTRY:
            continue
        d = nodedefs.REGISTRY[t]
        if d.category != "material":
            continue
        ps = n.get("params") or {}
        if t == "material/text":
            out.append({"label": d.title, "kind": "text",
                        "text": (ps.get("内容") or "")[:400]})
        elif t == "material/character":
            out.append({"label": f"{d.title}·{ps.get('角色') or ''}",
                        "kind": "image", "path": ps.get("形象版本")})
        elif t in kind_map:
            out.append({"label": d.title, "kind": kind_map[t],
                        "path": ps.get("文件")})
    return [i for i in out if i.get("path") or (i.get("text") or "").strip()]


def validate(graph: dict) -> tuple[dict, list[dict]]:
    nodes = {str(n["id"]): n for n in graph.get("nodes", [])}
    links = graph.get("links", [])
    if not nodes:
        raise GraphError("空图")
    for nid, n in nodes.items():
        if n["type"] not in nodedefs.REGISTRY:
            raise GraphError(f"未知节点类型: {n['type']} (id={nid})")
    for l in links:
        if str(l["src"]) not in nodes or str(l["dst"]) not in nodes:
            raise GraphError(f"无效连线: {l}")
        sdef = nodedefs.REGISTRY[nodes[str(l["src"])]["type"]]
        ddef = nodedefs.REGISTRY[nodes[str(l["dst"])]["type"]]
        try:
            out_t = sdef.outputs[l["src_slot"]][1]
            in_t = ddef.inputs[l["dst_slot"]][1]
        except (IndexError, KeyError):
            raise GraphError(f"连线槽位越界: {l}")
        if out_t != in_t and "*" not in (out_t, in_t):
            raise GraphError(
                f"类型不匹配: {sdef.type}[{out_t}] -> {ddef.type}[{in_t}]")
    # 必填输入必须有连线
    linked = {(str(l["dst"]), l["dst_slot"]) for l in links}
    for nid, n in nodes.items():
        d = nodedefs.REGISTRY[n["type"]]
        for i, (iname, _) in enumerate(d.inputs):
            if not _optional(iname) and (nid, i) not in linked:
                raise GraphError(f"节点「{d.title}」缺少必填输入 [{_in_name(iname)}]")
    return nodes, links


def run(graph: dict, jid: str):
    nodes, links = validate(graph)
    order = topo_order(nodes, links)
    tmpdir = C.TMP_DIR / jid
    tmpdir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    status: dict[str, str] = {}
    logs: list[str] = []
    errors: list[str] = []
    first_exc: Exception | None = None

    def mark(nid, s):
        status[nid] = s
        store.job_update(jid, result={
            "node_status": status, "logs": logs[-30:], "items": ctx.items})

    ctx = nodedefs.NodeCtx(jid=jid, tmpdir=tmpdir,
                           log=lambda m: logs.append(f"[{time.strftime('%H:%M:%S')}] {m}"))
    ctx.inputs = graph_inputs(graph)

    # 每条连线: (dst_node, dst_slot) -> (src_node, src_slot)
    in_map = {(str(l["dst"]), l["dst_slot"]): (str(l["src"]), l["src_slot"])
              for l in links}

    for nid in order:
        n = nodes[nid]
        d = nodedefs.REGISTRY[n["type"]]
        # 上游出错则跳过
        deps = [s for (dn, _), (s, _) in in_map.items() if dn == nid]
        if any(status.get(s) in ("error", "skipped") for s in deps):
            status[nid] = "skipped"
            mark(nid, "skipped")
            continue
        ins = {}
        for i, (iname, _) in enumerate(d.inputs):
            key = (nid, i)
            if key in in_map:
                s, s_slot = in_map[key]
                upstream = results.get(s) or {}
                out_name = nodedefs.REGISTRY[nodes[s]["type"]].outputs[s_slot][0]
                ins[_in_name(iname)] = upstream.get(out_name)
        mark(nid, "running")
        try:
            ctx.log(f"执行 {d.title}")
            results[nid] = d.fn(ctx, ins, n.get("params") or {}) or {}
            mark(nid, "ok")
        except Exception as e:
            if first_exc is None:
                first_exc = e
            errors.append(f"{d.title}: {e}")
            ctx.log(f"❌ {d.title}: {e}")
            mark(nid, "error")

    store.job_update(jid, result={
        "node_status": status, "logs": logs[-50:], "items": ctx.items,
        "error": "; ".join(errors) if errors else None})
    if errors and not ctx.items:
        raise GraphError("; ".join(errors)[:500]) from first_exc
    return {"items": ctx.items, "node_status": status, "errors": errors}
