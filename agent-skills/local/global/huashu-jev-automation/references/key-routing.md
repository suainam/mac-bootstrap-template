# 主备 Key 调用详情（仿 OMP judge 路由）

直连 `api.typesafe.ai/v1/systemone` 时，用 `scripts/typesafe_jev.py` 实现主备双 key + 失败回退。

- 主 key：`TYPESAFE_JEV_TOKEN`（= `TYPESAFE_API_KEY`，108 字符）。
- 备用 key：`TYPESAFE_JEV_TOKEN1`（107 字符）。
- 顺序：先主后备；前一候选失败（HTTP/网络/解析）才用下一候选，非轮换。
- 可选第三跳：`openrouter_fallback=True` 落到 `OPENROUTER_API_KEY`（对应 OMP `openrouter-judge/~typesafe/jev-latest`）。

```python
from typesafe_jev import send_jev
resp, key = send_jev(
    questions={"grid_visible": {"type": "noul", "instructions": "…"}},
    state={"shot": "S1"},
    model="jev-latest",
    images={"S1": ("shot.png", png_bytes, "image/png")},
)
# key == "primary" | "fallback" | "openrouter"
```

返回 `key` 标签供记录；任何 key 都返回 `jev-1.14.0`（`jev-latest` 别名）。两把 key 均已实测可用（2026-10-27）。
