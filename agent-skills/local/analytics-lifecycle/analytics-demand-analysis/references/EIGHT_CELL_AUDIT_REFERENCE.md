# 八格审计详细参考 (Eight-Cell Audit Reference)

> 权威位置：`analytics-demand-analysis/references/EIGHT_CELL_AUDIT_REFERENCE.md`  
> 跨技能相对链接：`../analytics-demand-analysis/references/EIGHT_CELL_AUDIT_REFERENCE.md`  
> **按条件引用**：仅阶段二/三/四在涉及版本/来源/预测分解时引用；阶段一与阶段五不直接引用。  
> 实现真源：`analytics-data-execution/scripts/audit_execution_sanity.py`（code agent 拥有）。

---

## 0. 字段契约 (Field Contract)

输入为长表，一行 = 一个 `(version, store_code, item_code)`：

| 列 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `version` | int/str | 是 | 版本标识（`old`/`new`；`forecast` 可选且独立审计） |
| `store_code` | str/int | 是 | 门店编码 |
| `item_code` | str/int | 是 | 商品编码 |
| `amount` | float | 是 | 有符号历史金额；允许负值（退货/退款）；禁止 NaN/Inf |
| `in_catalog` | 0/1 | 是 | 是否在有效目录内 |
| `fixed_active` | 0/1 | 是 | 是否固定在营；**与 `in_catalog` 相互独立** |
| `group_code` | str | 是 | 外层分组标签（如门店组群）；每个实体跨版本不可变 |
| `pure_target` | 0/1 | 是 | 旧版本行：是否纯目标来源（不含其他来源） |
| `new_target_hit` | 0/1 | 是 | 新版本行：是否命中新目标来源；old/forecast 行填 0 |
| `source` | 字符串 | 否 | 多来源集合，token 为 `target` / `non_target`，以 `;` 或 `,` 分隔；仅用于非目标来源保留核验 |

关键约定：
- `fixed_active=1` **不**蕴含 `in_catalog=1`。目录外固定在营（`in_catalog=0, fixed_active=1`）合法且必须支持。
- `amount` 独立于状态标记；目录外允许非零/负值，金额按固定实体历史金额跨版本保持。
- 来源不是互斥枚举。混合来源行因 `new_target_hit` 进入目录是合法的。

CLI：
```
audit_execution_sanity.py \
  --data x.parquet \
  --id-cols version,store_code,item_code \
  --amount-col amount --state-col in_catalog --fixed-active-col fixed_active \
  --group-col group_code --pure-target-col pure_target --new-target-hit-col new_target_hit \
  [--source-col source] \
  --old-version old --new-version new [--forecast-version forecast] [--strict-cells] [--json]
```
缺失任一必填列、非法 0/1、未知 source token、NaN 金额、复合键重复、店品全集缺口均以退出码 1 明确失败。空格默认报告为 0 行，`--strict-cells` 才升级为失败。

---

## 1. 三维八格 (3 Binary Dimensions × 8 Cells)

三个二元维度（group 外层）：
1. **版本**：`old` / `new`（或 `forecast` 单独审计）
2. **目录内/外**：`in_catalog=1` / `in_catalog=0`
3. **固定在营**：`fixed_active=1` / `fixed_active=0`

完整 8 格键 `(version, in_catalog, fixed_active)`。**结构零组合**：无（fixed_active 与 in_catalog 独立，8 格全部可出现）。  
> 早期 "fixed_active=1 ⇒ in_catalog=1" 假设已作废；目录外固定在营是合法且必需的单元。

报告按外层分组列出全部 8 格，缺少数据的格报告行数与金额为 0；不向输入伪造实体行。仅 `--strict-cells` 将空格判为失败。

---

## 2. 核心守恒与身份 (Core Conservation & Identity)

### 2.1 复合键唯一性
每个 version 内 `(store_code, item_code)` 唯一：`COUNT(1)-COUNT(DISTINCT store_code,item_code)==0`。

### 2.2 店品全集守恒
old 的 `(store,item)` 集合 == new 的集合（全集不变，仅状态/来源变化）。

### 2.3 金额固定实体历史金额保持
对每个 `(store,item)`，`old.amount == new.amount`（含目录外非零/负值）；`fixed_active` 与 `group_code` 跨 old/new 保持一致。按分组检查有符号金额守恒。forecast 金额独立，不参与历史守恒。

### 2.4 八格分解穷尽与互斥
对每个 version：`sum(amount over 8 cells) == version total`，且 8 格按 `(in_catalog, fixed_active)` 划分穷尽互斥（由 enum 校验保证）。

### 2.5 来源只替换目标
- 若 old 目录内行的来源集合含 `non_target`，该实体在 new 中必须仍在目录内，金额与固定在营标记保持。
- 来源集合可以变化，混合来源不强制互斥；目标替换按 §3 三布尔公式判断。

### 2.6 增删迁移身份
```
count_new - count_old == added - removed
```
其中 count、added、removed 仅基于 `in_catalog=1` 的店品集合计算；`fixed_active` 不参与目录增删计数。

### 2.7 old 目录实体不得丢失
old 目录内的实体必须仍存在于 new 全集；允许按 §3 规则迁移为目录外。

### 2.8 预测 vs 历史分列
- forecast version **单独审计**，不混入 old/new 比较。
- forecast 的每个 `(store,item)` 必须存在于 new。
- forecast 可覆盖 new 的子集；不得反向要求 new ⊆ forecast。

---

## 3. 旧→新推导公式 (Old→New Derivation)

不使用单一互斥 `reason`。定义三布尔：
- `old_in_catalog`：old 中该 (store,item) 是否 in_catalog=1
- `pure_target`：该行来源是否纯目标（source=target 且无其他来源多重命中）
- `new_target_hit`：new 中目标来源是否命中该 (store,item)

```
expected_new = (old_in_catalog AND NOT pure_target) OR new_target_hit
```
其他来源可多重命中；纯目标来源才参与替换。此公式替代 reason 互斥短路。

---

## 4. 空组与负值处理 (Empty Groups & Negative Values)

- **空格**：某格无实体合法；报告行数与金额为 0，不伪造实体。严格模式将空格判为失败。
- **负值**：`amount` 允许负（退款/退货）；守恒校验使用有符号求和，禁止取绝对值。
- **NaN**：amount 含 NaN => 直接 fail。
- **fixed_active 与 in_catalog 独立**：`in_catalog=0, fixed_active=1` 合法（目录外固定在营）。

---

## 5. 样本与生产复现 (Sample & Production Reproduction)

- **样本阶段**：用抽样数据（≥ 1000 行或覆盖全部 8 格）先跑八格门禁，确认公式与守恒。
- **生产阶段**：全量数据跑八格门禁；样本与生产结果差异 > 1% 需业务归因。
- **复现要求**：记录 seed/分区/版本号，确保可复现；门禁脚本输出落盘为 `04_outputs/reports/...-04-eight-cell-report.md`。

---

## 6. 完成标准 (Completion Criteria)

- [ ] 每个外层分组的 8 格全部报告，空格显式显示 0。
- [ ] 复合键唯一性通过。
- [ ] 店品全集 old==new 通过。
- [ ] 金额固定实体历史保持通过（含目录外非零/负值）。
- [ ] 来源 non_target 保留通过。
- [ ] 增删迁移身份公式通过。
- [ ] old in_catalog 命中保留通过。
- [ ] 预测 version 单独审计通过，其 store,item ⊆ new。
- [ ] 旧→新推导公式 `expected_new` 与实际 new 一致。
- [ ] NaN/空组处理符合 §4。

---
