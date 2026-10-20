# Fission Harness

`FissionHarness` 是裂变链路的稳定入口，不依赖 FastAPI 或 store：

```python
from pipelines.fission.harness import FissionHarness, HarnessRequest

harness = FissionHarness()
result = harness.run(HarnessRequest(
    profile_id="panty-cotton-lace",
    n=5,
    seed=42,
    generate=False,
))
print(result.status, result.run_dir, result.contracts)
```

- `generate=False` 只出契约；
- `generate=True` 使用 `VideoBackend` 生成视频；
- `resume(run_dir)` 只续跑未完成生成；
- 进度回调通过 `progress(phase, extra)` 注入。

完整端口、目录边界和移植清单见 `docs/fission-harness.md`。
