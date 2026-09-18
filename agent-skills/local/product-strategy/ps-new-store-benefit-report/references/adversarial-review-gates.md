# 对抗性审查清单与质量门禁 (Adversarial Review Gates)

本文件定义新店效益与考核分析的对抗性审查门禁（Adversarial Review Gates），任何输出、交付或代码变更必须通过下列自动化断言。

---

## 一、审查攻击向量与防卫契约 (Attack Vectors & Defense Contracts)

### Gate 1: 动态基准日与传参安全 (Dynamic Event Date & Partition Pruning)
- **攻击风险**：代码硬编码特定历史日期（如 `20260907` 或 `20260910`），导致未来定时调度跑出陈旧数据；或未做日期格式清洗导致 SQL 注入或分区未命中。
- **审查断言**：
  1. `event_date` 参数化；未传参时必须动态默认为“昨天”（即 `(datetime.now() - timedelta(days=1)).strftime("%Y%m%d")`）。
  2. 支持 `YYYYMMDD` 和 `YYYY-MM-DD` 两种常见格式输入，自动清洗为整数型分区 `YYYYMMDD`。
  3. 分区裁剪断言：对 `dsl_ads.ads_sale_store_metrics_sum_di` 等分区日表，必须有上界与下界裁剪，严禁扫描超过 365 天或无界扫描。

### Gate 2: 除零与极端值防卫 (Zero-Division & Edge Defensiveness)
- **攻击风险**：
  - 新开门店或异常门店 `item_num_ct == 0`（目录尚未铺货），导致 `item_num_yxs_ct / item_num_ct` 触发 `ZeroDivisionError`。
  - `sale_amt_all == 0`（开业暂停营运或 0 销售），导致销售占比计算崩溃。
  - `assess_target_total == 0`（预算底表漏填或保本额为 0），导致达成率溢出为 `Inf` 或抛出异常。
- **审查断言**：
  1. 所有除法必须使用安全除法包裹（`safe_divide(num, den, default=0.0)`）。
  2. 分母为 0 时，比例指标安全回退为 `0.00%`，并在日志中输出 WARNING，绝不允许未捕获崩溃。

### Gate 3: 数据守恒与数学不变式 (Mathematical Invariants)
- **攻击风险**：数据由于多表关联笛卡尔积或字段错位，导致目录内指标大于全店指标。
- **审查断言**：
  1. **品项单调性**：对任意门店，$\text{item\_num\_yxs\_ct} \le \text{item\_num\_ct} \le \text{item\_num\_all}$。
  2. **动销单调性**：$\text{item\_num\_yxs\_all} \le \text{item\_num\_all}$。
  3. **销售包含性**：$\text{sale\_amt\_ct} \le \text{sale\_amt\_all} + 1.0$（允许 $1$ 元浮点误差）。
  4. **库存包含性**：$\text{lt90\_inv\_av\_cost\_amt\_ct} \le \text{lt90\_inv\_av\_cost\_amt\_all} + 1.0$。
  5. **时间进度上界**：跟进中门店 $0 < \text{time\_progress} \le 1.0$；已结束门店严格 $\text{time\_progress} = 1.0$。

### Gate 4: 考核状态与达标判定准确性 (Assessment Status Integrity)
- **攻击风险**：
  - 已超过 90 天考核期的门店被误放入“跟进中”工作表。
  - 达成率超过 100% 的门店被错标为“否”，或未达标被错标为“是”。
- **审查断言**：
  1. 开业活动结束日超过 90 天的门店必须归属“已结束”分类。
  2. “是否达标”严格判定：`cumulative_completion_rate >= 1.0` 对应达标，且 11 家已结束试点店中至少有 4 家核验为达标。

### Gate 5: Excel 呈现与单元格溢出审查 (Workbook Visual & Formatting Audits)
- **攻击风险**：大额金额未设列宽导致显示为 `###`；数值以字符串格式存储导致无法在 Excel 中求和；Sheet 命名超过 31 字符。
- **审查断言**：
  1. 所有工作表名称长度 $\le 31$ 字符。
  2. 所有金额字段保留 2 位小数并具备千分位格式。
  3. 所有比率字段以百分比标准显示（`XX.XX%`）。
  4. 列宽自适应设置（根据中文字符宽度自动设置最小 15 字符宽），杜绝 `###` 遮挡。
  5. 必须具备 32 个标准中文字段，排列顺序与中文字典完全一致。

---

## 二、执行与自动化门禁脚本

审查脚本位于 `scripts/audit_new_store_adversarial.py`。
在每次生成宽表后，必须执行下列门禁命令：
```bash
uv run python .agents/skills/ps-new-store-benefit-report/scripts/audit_new_store_adversarial.py --excel <路径>
```
输出必须包含 `[ADVERSARIAL AUDIT GATE] ALL GATES PASSED`，方可向用户交付或确认完成。
