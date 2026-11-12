# 案例：Story-295628 缩铺效期调整（76.1 → 89.3）

范围：数据智能 / 策略分析；纯后端规则 + 数据重跑，无 UI。耗时约 26 分钟，2 轮保存。

## 分数轨迹

| 轮次 | 动作 | final_score | d1/d2/d3/d4/d5 | issues |
|---|---|---|---|---|
| 基线 | `snapshot` | 76.1 | 59/92/75/75/92 | 7（3 major） |
| 1 | 单源化边界、固定基准、已确认口径；保存+回读+45s+重算 | 85.8 | 84/100/75/84/92 | 6（1 major） |
| 2 | 去「即时生效」、AC-01 补基础准入、AC-04 只判状态；保存+回读+45s+重算 | 89.3 | 92/100/75/92/92 | 5（1 major） |

d3（一致性与依据，权重 25%）两轮都停在 75：评分器每次换一个角度找长期规则/短期配置的时序冲突。

## 问题 → 修订对照

| 评分器问题（root_cause_key） | 原句 | 替换 |
|---|---|---|
| long_term_rule_vs_short_term_config_conflict | 「确保长期生效」与配置窗口并存 | 拆开：门槛规则长期；五省区配置仅 20261110-20261114；「配置到期不回退门槛」写在目标、前提、业务规则 2、状态规则 4 处引用同一结论 |
| buffer_scope_unconfirmed | 待确认事项 1：是否仅适用二次上架 | 原始 Story 已写明「基础准入与二次上架同步调整」→ 改为「已确认口径」，范围写死「不涉及首次上架」 |
| acceptance_criteria_unverifiable | AC-05「波动在合理范围内」、「如±10%」 | 业务规则 3 / AC-05 / 量化目标 4 / 依据表统一：四项数值逐项相等，偏差 0 |
| config_effective_time_conflict（第 2 轮新出） | 「设定生效业务日 20261110-20261114，确保配置即时生效」 | 「…并于 20261110 开始生效」 |
| acceptance_criteria_incomplete / duplicate | AC-01 只验二次上架；AC-04 与 AC-05 同验四项数值 | AC-01 加基础准入两个阈值；AC-04 只验「重跑任务状态为成功」 |

## 未改的建议（缺事实，交用户）

- rule_id 82-86 ↔ 省区一一映射：原始 Story 只给范围与省区编码，未给配对关系。
- ALL_PREFIX 配置字段清单、配置到期后已产出分区的留存策略、重跑执行时点：原始需求无事实。
- 若用户补充上述事实，再各用一轮 `save`/`rescore` 纳入，不要预先捏造。

## 复现命令

```bash
S=~/.agents/skills/prd-score-optimization/scripts/prd_iterate.mjs
node $S snapshot Story-295628        # 基线+回退点+原始需求落盘到 /tmp/prd-score/Story-295628
# 在 latest.prd.md 副本上定点修订 → candidate.md
node $S save Story-295628 --file /tmp/prd-score/Story-295628/candidate.md
node $S rescore Story-295628  # 等 45s → 重算 → create_time 变新才输出
```
