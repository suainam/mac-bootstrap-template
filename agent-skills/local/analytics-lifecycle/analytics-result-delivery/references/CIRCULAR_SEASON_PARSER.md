# 环形跨年时间区间解析规约 (Circular Season Range Parser)

在零售季节性分析、商品生命周期管理中，季节往往跨越自然年度（例如秋冬季：10月持续至次年2月）。机械地将月份列出或按年内数字切分会导致业务理解混淆。本规约确立了跨年时间的环形闭环解析与展示标准。

---

## 1. 业务展示对比

| 原始输入（月份集合） | 错误/生硬格式化 | 标准业务呈现（规约要求） |
| :--- | :--- | :--- |
| `[1, 9, 10, 11, 12]` | `1月, 9月-12月` | **`9月-次年1月`** |
| `[1, 2, 10, 11, 12]` | `1月-2月, 10月-12月` | **`10月-次年2月`** |
| `[1, 2, 3, 10, 11, 12]` | `1月-3月, 10月-12月` | **`10月-次年3月`** |
| `[10, 11, 12]` | `10月, 11月, 12月` | **`10月-12月`** |
| `[1..12] (全量)` | `1月-12月` | **`全年`** |

---

## 2. 核心环形钟表算法 (Clockwise Range Algorithm)

将 12 个月抽象为表盘上的 1~12 环形闭环：
- 节点前驱：1 的前驱是 12，2 的前驱是 1...
- 节点后继：12 的后继是 1，1 的后继是 2...

### 算法逻辑
1. 若月份集合包含全部 12 个月，直接输出 `全年`。
2. 寻找**环形区间起点**：遍历所有有效月份 $m$，若其前驱 $(m-1 \text{ if } m>1 \text{ else } 12)$ 不在有效月份集合中，则 $m$ 为一个连续区间的起点。
3. 从每个起点顺时针延展遍历，直到遇到非在季月份停止，记录该区间的 `(start, end, length)`。
4. 格式化输出：
   - 若 $length == 1$：输出 `s月`；
   - 若 $start > end$（跨越了 12 $\rightarrow$ 1 的年份分界）：输出 **`s月-次年e月`**；
   - 若 $start \le end$（年内连续）：输出 **`s月-e月`**。
5. 多个不连续区间用英文逗号 `, ` 拼接。

---

## 3. 可复用 Python 实现

```python
def format_season_months(mons: list[int] | set[int]) -> str:
    if not mons:
        return "未配置"
    mons_sorted = sorted(list(set(int(m) for m in mons)))
    month_set = set(mons_sorted)
    if len(month_set) == 12:
        return "全年"

    # 寻找环形起点
    starts = [m for m in mons_sorted if (12 if m == 1 else m - 1) not in month_set]
    if not starts:
        starts = [mons_sorted[0]]

    intervals = []
    for s in starts:
        curr = s
        length = 0
        while curr in month_set:
            length += 1
            curr = 1 if curr == 12 else curr + 1
            if length > 12:
                break
        end = 12 if curr == 1 else curr - 1
        intervals.append((s, end, length))

    parts = []
    for s, e, length in intervals:
        if length == 1:
            parts.append(f"{s}月")
        else:
            if s > e:
                parts.append(f"{s}月-次年{e}月")
            else:
                parts.append(f"{s}月-{e}月")
    return ", ".join(parts)
```
