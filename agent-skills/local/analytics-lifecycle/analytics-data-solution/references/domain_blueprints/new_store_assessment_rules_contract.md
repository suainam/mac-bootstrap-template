# 新店 90 天营运考核规则契约 (New Store Assessment Rules Contract)

本文档规范新店开业后 90 天营运考核指标体系的计算逻辑、阶段判定、基数折算与奖励系数规则。

---

## 一、考核周期与状态划分

1. **考核阶段定义**：
   - **开业前/开业期**：`start_dt` 至 `end_dt`（通常为开业前 1 天至开业后数天大促活动）。
   - **考核期起点 (`s_kh`)**：开业大促结束次日，即 `cast(end_dt as date) + 1 day`。
   - **考核期终点 (`e_kh`)**：`cast(end_dt as date) + (1 + 89 + reject_cnt) days`。
   - **剔除天数 (`reject_cnt`)**：门店因不可抗力或外部整修经审批剔除的非营业天数。
2. **考核状态流转**：
   - **跟进中 (Ongoing)**：评估基准日 `event_date < e_kh`，时间进度 `time_progress = days / 90.0`。
   - **已结束 (Finished)**：评估基准日 `event_date >= e_kh`，时间进度严格为 `100.0%`。

---

## 二、指标分解与达标系数算法

### 1. 达标标准系数 (`std_target`) 确定规则
门店的达标标准系数依据门店性质及基础系数 (`base_coefficient`) 确定：
```python
if is_strategic_store == 1:
    std_target = 0.70          # 战略店标准：70%
elif base_coefficient > 3500:
    std_target = 0.75          # 高基数标准（基础系数 > 3500）：75%
else:
    std_target = 0.80          # 常规标准（基础系数 <= 3500）：80%
```

### 2. 90 天总指标 (`assess_target_total`)
```text
月保本销售额 (break_even) 取自 dsl_dwd.dwd_fin_ti_store_breakeven_df (预决算底表)
assess_target_total = break_even * 3 * std_target
daily_assess_target = assess_target_total / 90.0
```

### 3. 考核销售额 (`assess_pay_amt`)
为平衡线上履约成本，O2O 渠道销售额按 $\frac{1}{3}$ 折算计入考核销售额：
$$\text{assess\_pay\_amt} = \text{non\_o2o\_pay\_amt} + \frac{\text{o2o\_pay\_amt}}{3.0}$$

### 4. 累计达成率 (`cumulative_completion_rate`)
$$\text{cumulative\_completion\_rate} = \frac{\text{assess\_pay\_amt}}{\text{assess\_target\_total}}$$
- 达标判定：`cumulative_completion_rate >= 1.0`（即 $\ge 100\%$）为达标。

### 5. 营运奖惩系数与实际系数
- 实际系数 `coefficient_actual`:
  - 若 `cumulative_completion_rate < 0.6`: 系数为 `0.0`；
  - 线性区间与上限约束受营运考核文件具体规则管控。
- 奖励系数 `reward_coefficient`:
  - 若达成达标标准且基础系数较高，在基准系数上乘以 $1.2$ 超额激励。

---

## 三、跨表口径映射

| 业务概念 | ODPS 表名 | 关键字段/过滤条件 |
|---|---|---|
| 门店基础信息与开业时间 | `dsl_dim.dim_store` | `stat_date = MAX_PT('dsl_dim.dim_store')` |
| 预算月保本销售额 | `dsl_dwd.dwd_fin_ti_store_breakeven_df` | `stat_date = MAX_PT(...) and is_tg = 1` |
| 实体销售额与毛利 | `dsl_ads.ads_sale_store_metrics_sum_di` | `stat_date between s_dt and e_dt` |
| O2O销售额 (美团/饿了么等) | `dsl_ads.ads_ec_platform_store_class_sum_d` | `platform_id in ('311','312','317','318','321','322','341','901','1187','3411')` |
| 效益分析指标宽表 | `dsl_tmp.tmp_ads_item_content_store_summary_df` | `gap_level = 'STORE' and event_date = ${event_date}` |
