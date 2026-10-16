# 分析口径假设日志规约 (Analysis Assumptions Log Standard)

借鉴于行业开源规范（`nimrodfisher/data-analytics-skills`），在数据分析的“需求分析（Stage 2）”与“方案设计（Stage 3）”过程中，任何关键业务假设与技术裁剪必须显式记入日志，防止指标在执行阶段产生静默口径漂移。

---

## 1. 假设分类体系 (Assumption Taxonomy)

每个关键口径决策必须归属于以下四类之一：
1. **样本代表性假设 (Representativeness)**：
   - 样本时间窗口（如考核期 90 天是否剔除开业首周大促异动）；
   - 对照组同质性（老店与新店在商圈、店型、面积上的可比性）。
2. **完整性与排除边界假设 (Completeness & Exclusion)**：
   - 仓缺与供应链断货是否剔除出执行率分母；
   - 极短周转（在架天数 < 15 天）品类是否参与动销考核。
3. **缺失值与默认值处理假设 (Imputation & Defaulting)**：
   - 销售额/毛利额 `NULL` 值是否默认填补 `0`；
   - 未匹配到门店主档的脏数据处理规则（丢弃 vs 归入其他）。
4. **多模型优先级与分类短路假设 (Priority & Masking)**：
   - 复合属性（既是新品又是季节性）在目标规则中的分配归属；
   - 是否采用纯净集（Pure Set）隔离策略。

---

## 2. 假设条目结构 (Entry Specification)

每条假设必须包含以下 6 个核心要素：
- **`ID`**：唯一编号（如 `ASM-01`, `ASM-02`）；
- **`Category`**：上述分类之一；
- **`Statement`**：简明清晰的正面陈述；
- **`Rationale`**：做出该假设的业务或统计学依据；
- **`Confidence`**：置信度等级（`High` / `Medium` / `Low`）；
- **`Impact if False`**：若假设不成立对分析结论或业务决策的潜在影响。

---

## 3. 标准 Markdown 模板

```markdown
### ASM-[编号]: [简述]
- **分类**: [Representativeness | Completeness | Imputation | Priority]
- **假设描述**: [正面阐述假设内容]
- **依据与支撑**: [为什么采用该假设]
- **置信度**: High | Medium | Low
- **失效影响与备选**: [若被业务否决或事实偏差，结论如何修正]
```
