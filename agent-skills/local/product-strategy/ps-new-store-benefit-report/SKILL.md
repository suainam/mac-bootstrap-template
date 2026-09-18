---
name: ps-new-store-benefit-report
description: 新店效益分析与90天考核宽表直算：涵盖32项标准中文字段融合、月保本指标折算、O2O线上折算、对抗性审查门禁及模板化Excel导出。当用户需要分析新店效益、计算新店90天考核达成率、导出新店效益宽表时使用。
---

# 新店效益与考核分析汇报 (New Store Benefit & Assessment Report)

用于 `topics/new_store/` 的新店 90 天效益分析与营运考核宽表计算。集成 ODPS 直算、保本销售额折算、32 项标准中文字段融合、对抗性审查门禁及自适应美化 Excel / Markdown 双格式交付。

## 业务契约 (Business Contract)

- **动态基准推导**：`event_date` 默认昨天（`YYYYMMDD` 格式）；支持任意历史或自定义评估日，严禁将具体日期写死为业务常量。
- **状态严格分层**：
  - **跟进中 (Ongoing)**：开业大促结束次日 (`s_kh`) 至基准日仍处于 90 天周期内，时间进度 $0 < \text{time\_progress} \le 1.0$。
  - **已结束 (Finished)**：开业大促结束已超过 90 天，时间进度锁定为严格 $100.0\%$，完整核定 90 天终局达成率与达标判定。
- **32 项标准中文字段规范**：严禁随意重命名。严格执行“试点营运区”（非“是否测试营运区”）、“近 90 天日均库存成本”（非“平均库存成本”）、“近 90 天日均销售成本”。
- **考核折算核心公式**：
  - 90 天总指标：$\text{assess\_target\_total} = \text{月保本销售额} \times 3 \times \text{达标标准系数}$（战略店 70%，基数 > 3500 为 75%，其余 80%）。
  - 考核销售额：$\text{assess\_pay\_amt} = \text{线下实体销售} + \frac{\text{O2O线上销售}}{3.0}$。
  - 累计达成率：$\text{cumulative\_completion\_rate} = \frac{\text{assess\_pay\_amt}}{\text{assess\_target\_total}}$。
- **对抗性审查门禁**：严禁在未通过自动化断言门禁的情况下直接交付数据。交付前必须执行数学不变式与视觉溢出审查。

---

## 执行分支 (Branches)

### Branch A: 周期性新店宽表直算与一键导出 (默认)
当用户需要生成最新或指定基准日的新店效益与考核交付件时触发：
1. **确定基准日与门店范围**：
   - 若用户未指定 `event_date`，默认推导为昨天：
     ```bash
     uv run python .agents/skills/ps-new-store-benefit-report/scripts/run_new_store_benefit_report.py
     ```
   - 若用户指定评估日（如 `20260907`）或限定门店列表：
     ```bash
     uv run python .agents/skills/ps-new-store-benefit-report/scripts/run_new_store_benefit_report.py \
       --event-date 20260907 \
       --stores 2000017165,2000017155,2000017160,2000017175,2000016600,2000017116
     ```
2. **自动化产出交付物**：
   - 目标 Excel: `topics/new_store/04_outputs/tables/新店90天效益与考核分析宽表.xlsx`
     - Sheet 1: `跟进中新店效益与考核(6家)`
     - Sheet 2: `已结束新店效益与考核(11家)`
     - Sheet 3: `中文字段对照与口径说明`
   - 目标 Markdown: `topics/new_store/04_outputs/tables/新店90天效益与考核分析宽表.md`
3. **完成标准**：
   - 脚本自动调用并通过 `audit_new_store_adversarial.py` 对抗性审查门禁。
   - Excel 三张工作表均完整生成，中文表头深蓝底白字居中，列宽根据文字自动展开无 `###` 遮挡。
   - 深入参考：[references/benefit-metrics-contract.md](references/benefit-metrics-contract.md)、[references/assessment-rules-contract.md](references/assessment-rules-contract.md)。

---

### Branch B: 对抗性审查与质量门禁审计 (Audit Gate)
当需要对现有或外部提交的新店分析数据做严格的数学一致性、除零防卫与排版质检时触发：
1. **运行对抗性门禁脚本**：
   ```bash
   uv run python .agents/skills/ps-new-store-benefit-report/scripts/audit_new_store_adversarial.py \
     --excel topics/new_store/04_outputs/tables/新店90天效益与考核分析宽表.xlsx
   ```
2. **核查五大硬性断言**：
   - **包含性断言**：$\text{目录品项} \le \text{全店品项}$、$\text{动销品项} \le \text{目录品项}$、$\text{目录销售} \le \text{全店销售}$、$\text{目录库存} \le \text{全店库存}$。
   - **除零防卫**：零品项或零销售门店比例指标优雅回退 $0.00\%$，绝无 `#DIV/0!` 或 `NaN`。
   - **周期断言**：已结束门店进度严格等于 $1.0$；跟进中门店进度在 $0.0 \sim 1.05$。
   - **字符限制**：工作表名 $\le 31$ 字符。
   - **字段契约**：32 个标准字段全量存在且顺序对齐。
3. **完成标准**：控制台输出 `[ADVERSARIAL AUDIT GATE] ALL GATES PASSED`，退出代码为 0。
4. 深入参考：[references/adversarial-review-gates.md](references/adversarial-review-gates.md)。

---

### Branch C: 单店营运诊断与考核试算
当需要深入某家门店分析其为何未达标、测算剩余日均销售缺口或试算奖惩激励系数时触发：
1. 读取样本结构：[examples/store_assessment_sample.json](examples/store_assessment_sample.json)。
2. 计算剩余指标缺口：
   $$\text{remaining\_daily\_target} = \frac{\max(0, \text{assess\_target\_total} - \text{assess\_pay\_amt})}{\max(1, 90 - \text{days})}$$
3. 输出包含“当前进度”、“考核达成率”、“日均缺口”和“奖励系数预测”的单店诊断卡片。
4. **完成标准**：产出带明确业务归因的单店诊断建议。

---

## 质量与工程门禁

- **严禁数据明细落地**：遵守安全红线，所有计算在 ODPS 侧先聚合后下载，单次导出严格受限在 1,000,000 行内。
- **自动化测试保障**：在提交任何脚本改动前，必须运行全套单元测试：
  ```bash
  uv run pytest .agents/skills/ps-new-store-benefit-report/scripts/test_skill.py
  ```

---

## 支持资产索引

- `references/benefit-metrics-contract.md`：32 项中文字段标准字典、ODPS 表映射与极限值防卫契约。
- `references/assessment-rules-contract.md`：90 天营运考核算法体系（保本销、达标系数、O2O折算）。
- `references/adversarial-review-gates.md`：对抗性审查五大门禁契约与攻击向量说明。
- `examples/new_store_benefit_query.sql`：动态参数化、带除零防卫的 ODPS SQL 直算模版。
- `examples/store_assessment_sample.json`：跟进中与已结束典型门店标准数据样本。
- `scripts/run_new_store_benefit_report.py`：动态传参一键直算、美化导出与门禁串联执行器。
- `scripts/audit_new_store_adversarial.py`：可独立执行的对抗性审查门禁工具。
- `scripts/test_skill.py`：针对 Skill 算法、动态传参及门禁的自动化测试套件。
