"""DirectorPlan -> 单镜视觉提示词 + 参考图顺序。

参考图编号必须与实际提交顺序一致：生成管线按 shot["refs"] 的顺序提交图片，
因此这里收集的 refs 顺序就是提示词里的图例顺序。

提示词本身由 director.render_shot 按“四块结构 + beat 粒度”渲染；
本文件只负责收集参考图、维护图例，不做创作。
"""
from . import director


def _collect_refs(plan: dict) -> tuple[list[str], str]:
    assets = plan.get("assets") or {}
    refs: list[str] = []
    legend: list[str] = []

    def add(paths, label: str, limit: int):
        for i, p in enumerate((paths or [])[:limit]):
            if not p:
                continue
            refs.append(p)
            legend.append(f"参考图{len(refs)}={label}{i + 1}")

    add(assets.get("person_photos"), "固定人物照片", 2)
    add(assets.get("product_images"), "商品图", 2)
    add(assets.get("background_images"), "背景图", 1)
    return refs, "，".join(legend)


def compile_shot(plan: dict, shot: dict) -> tuple[str, list[str]]:
    refs, legend = _collect_refs(plan)
    prompt = director.render_shot(plan, shot, legend)
    return prompt, refs


def compile_video(plan: dict) -> tuple[str, list[str]]:
    """整条视频一次生成的 prompt + 参考图顺序。"""
    refs, legend = _collect_refs(plan)
    prompt = director.render_video(plan, legend)
    return prompt, refs
