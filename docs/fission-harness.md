# 裂变 Harness：链路、模块与移植边界

> 目标：把已经跑通的 P0.2 裂变链路收成一个稳定 harness，行为不依赖 FastAPI、SQLite、前端或固定项目目录；后续可以移植到其他项目。

## 1. 一句话

```text
HarnessRequest
  -> materials（可选素材解读）
  -> ProductAnchor
  -> StyleAtlas -> DiversityPlanner
  -> CreativeWorld（proposer / critic / semantic selector）
  -> Composer（contract + H3 prompt）
  -> Audit（anchor/style/copy/semantic）
  -> VideoBackend（可选）
  -> HarnessResult
```

核心原则：

- **商品事实在 anchor**：任何风格/世界/文案不能新增 claims、功效、价格；
- **风格在 style/planner**：人物、声音、机位、场景、文案 tone 独立采样；
- **创意在 concept**：world 只描述装置/动作/转折，商品通过 proof_rituals 进入；
- **契约是稳定中间产物**：contract 可审计、可重放、可由不同 backend 消费；
- **harness 不绑定运行环境**：API job、CLI、其他项目都调用同一输入/输出。

## 2. 当前链路

```text
ProductProfile
  └─ anchor.build_anchor()            商品事实/多视角参考/claim atoms
Reference facets
  └─ style_atlas.build_style_atlas()  视觉/文案风格签名
        └─ planner.plan_styles()      seeded max-min + coverage
CreativeWorld
  ├─ concept.proposer.propose_worlds()   LLM 生成 15+ 候选
  ├─ concept.critic.critique()           字段/claim/proof/批内去重
  ├─ concept.selector.select_worlds()    单批 semantic max-min
  └─ concept.semantic.semantic_audit()   semantic 距离审计
        ↓
composer.compose_batch()              anchor × style × world -> contract/prompt
        ↓
audit.audit_contracts()               anchor/style/copy/world/contract semantic
        ↓
VideoBackend.generate()               H3 / 其他视频实现（可选）
        ↓
HarnessResult
```

`run_p0()` 是当前本地实现；`FissionHarness` 是稳定 facade。

## 3. 稳定输入 / 输出

### HarnessRequest

```python
HarnessRequest(
    profile_id="panty-cotton-lace",
    n=5,
    seed=42,
    text=None,
    person=None,
    product_image=None,
    prepare_materials=True,
    refresh_materials=False,
    generate=False,
    out_root=None,
)
```

| 字段 | 含义 |
|---|---|
| `profile_id` | 商品 Profile（商品事实的入口） |
| `n` | 本批契约/视频数量 |
| `seed` | 风格采样可复现种子；不传则随机 |
| `text` | 可选补充要求；当前前端不暴露 |
| `person` | 覆盖 Profile 人物图 |
| `product_image` | 覆盖 Profile 正面商品图 |
| `prepare_materials` | 增量补齐 descriptions/facets/alignments |
| `refresh_materials` | 强制重读素材 |
| `generate` | false 只到契约；true 调 VideoBackend |
| `out_root` | 指定 run 目录；不传则自动生成 |

### HarnessResult

```python
HarnessResult(
    run_id="p0-...",
    run_dir=Path("data/runs/p0-..."),
    status="contracts_done|done|partial|audit_failed|error",
    manifest={...},
    contracts=[Path(...)],
    videos=[Path(...)],
    audit={...},
    inputs={...},
)
```

契约目录：

```text
<run_dir>/
  run.json
  anchor.json
  style_atlas.json
  style_plan.json
  worlds.json
  audit.json
  summary.json
  v01/
    contract.json
    prompt_h3.txt
    prompt_audit.md
    subtitles.srt
    voiceover.txt       # 有口播时
    variant_01.mp4      # generate=True 且 backend 成功
```

## 4. 模块划分

### 4.1 领域核心（目标：可移植）

| 模块 | 职责 | 当前依赖 |
|---|---|---|
| `anchor.py` | ProductAnchor | 仅 profile + 文件路径 |
| `style_atlas.py` | facet -> 风格签名 | `data/reference_facets/` |
| `planner.py` | seeded max-min / coverage | 纯函数 |
| `concept/schema.py` | World 规范化/校验 | 纯函数 |
| `concept/semantic.py` | semantic 距离/审计 | jieba |
| `concept/selector.py` | 单批 semantic max-min / style 配对 | 纯函数 |
| `concept/critic.py` | world 校验/批内去重 | 纯函数 |
| `audit.py` | anchor/style/copy/semantic 审计 | 纯函数 |
| `composer.py` | contract/prompt 编译 | `ComposerDeps`（llm/facets/codec） |

### 4.2 Harness

`pipelines/fission/harness/`

| 文件 | 职责 |
|---|---|
| `models.py` | `HarnessRequest` / `HarnessResult` |
| `ports.py`（上移到 `pipelines/fission/ports.py`） | LLM / facets / codec / material / profile / video / progress 协议 |
| `context.py`（上移到 `pipelines/fission/context.py`） | `HarnessContext` 依赖容器 |
| `service.py` | `FissionHarness.run()` / `.resume()` |
| `local.py` | 当前项目的 LLM / facets / codec / materials / profile / video 适配器 |
| `README.md` | 使用示例 |

### 4.3 本地适配器（移植时替换）

| 模块 | 职责 |
|---|---|
| `materials.py` | descriptions/facets/alignments 子进程 |
| `profiles.py` | 读取 `configs/products/*.json` |
| `run_contract.py` | H3 提交、TTS/字幕、审核队列 |
| `orchestrator/app/reference_analysis.py` | LLM/视觉/ASR |
| `orchestrator/app/reference_contract.py` | H3 prompt 渲染 |
| `orchestrator/app/main.py` | FastAPI job / run API |
| `web/src/views/Fission.vue` | 产品 UI |

## 5. 端口

### 已有

```python
class VideoBackend(Protocol):
    def generate(contract: Path, prompt: Path, out_dir: Path,
                 name: str, force: bool = False) -> dict: ...

class ProgressSink(Protocol):
    def __call__(self, phase: str, extra: dict | None = None) -> None: ...
```

### 移植前应收紧的端口

已抽出的端口：

```text
LLMProvider        composer / proposer
FacetRepository    composer / style catalog
ContractCodec      validate / render_prompt / render_audit / srt
MaterialProvider   materials stage
ProfileProvider    profile loading
VideoBackend       H3 / 其他视频实现
ProgressSink       job/CLI 进度
```

`HarnessContext` 把这些依赖打包；`p0_runner.run_p0(..., context=...)`
不再直接 import `materials/profiles/composer` 的本地实现。

仍保留的本地耦合：

- `LocalMaterials` 仍调用项目 `pipelines/fission/materials.py`；
- `LocalCodec` 仍调用 `orchestrator.app.reference_contract/media`；
- `RunContractBackend` 仍调用 `scripts/run_contract.py`；
- `ReviewSink` 还没有单独抽协议，审核由 `run_contract` 内部完成。

## 6. 移植 checklist

1. 复制 `pipelines/fission/`（至少 `anchor/style_atlas/planner/concept/composer/audit` + `harness/`）。
2. 提供商品 Profile 或直接构造 `ProductAnchor`；
3. 提供 facet 目录，或实现 `MaterialProvider`；
4. 实现 `LLMProvider`，替换 `reference_analysis._ref_llm`；
5. 实现 `VideoBackend`，例如新项目的 H3/其他视频 API；
6. 决定 run 目录与审核队列的落点；
7. 用 `FissionHarness.run(HarnessRequest(...))` 跑契约；
8. 检查 `HarnessResult.audit` 的 `semantic_world_ok` / `semantic_contract_ok` / `copy` / `perceptual_ok`；
9. 通过后再打开 `generate=True`。

## 7. 当前边界

- `FissionHarness` 仍调用 `p0_runner.run_p0`，但 `p0_runner` 已接受 `HarnessContext`；
- LLM / facets / codec / material / profile / video / progress 均可注入；
- 默认 `local.py` 只负责当前项目的 LLM/H3/素材/审核适配；
- 真正跨项目移植前，最重要的一步是把 `ReviewSink` 从 `run_contract` 拆出，
  以及把 `LocalCodec` 的 H3 prompt 渲染替换成新项目 codec；
- P0.2 不做跨 run 记忆；`data/worlds/registry.jsonl` 是历史遗留，不参与生成。

## 8. 契约测试结果（2026-10-20）

通过 `FissionHarness` 跑契约（不生成视频）：

```text
run: data/runs/p0-harness-contract-v2/
status: contracts_done
contracts: 5
videos: 0
world semantic: unique_core_devices=5, min_distance=1.0
contract semantic: min_distance=0.7704
semantic.ok: true
audit.ok: false（coverage/copy 仍触发旧审计，generation 未被调用）
copy cross-variant duplicates: 1
person_visibility: 2 种
presenter_mode: 4 种
casts: 5 种（partial/direct_speech + 4 个 hands_only 形态）
```

## 9. 使用示例

```python
from pipelines.fission.harness import FissionHarness, HarnessRequest

harness = FissionHarness()
result = harness.run(HarnessRequest(
    profile_id="panty-cotton-lace",
    n=5,
    seed=42,
    generate=False,
))
print(result.status)
print(result.contracts)
print(result.audit["semantic"])
```

续跑：

```python
result = harness.resume("data/runs/p0-...")
```

自定义视频 backend：

```python
class MyBackend:
    def generate(self, contract, prompt, out_dir, name, force=False):
        ...  # 调新项目视频 API
        return {"provider_task": "...", "review_path": "..."}

harness = FissionHarness(video_backend=MyBackend())
```
