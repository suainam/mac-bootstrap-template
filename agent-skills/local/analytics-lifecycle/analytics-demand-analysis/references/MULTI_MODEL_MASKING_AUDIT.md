# 业务多模型优先级掩盖排查与防误伤指南 (Multi-Model Masking Audit)

在多模型组合下发、复合打标的数仓生产链路中，普遍存在**高优先级规则短路掩盖低优先级属性**的业务现象。本指南规定了排查与剔除异常数据时保持正当入选品完整的操作标准。

---

## 1. 核心业务场景：优先级短路现象 (Priority Masking)

### 典型场景
在 3合1 组货目录或品类规划中，同一商品在同一门店往往同时满足多种业务规则：
- 规则 A（如：`门店季节性商品`，优先级 3）；
- 规则 B（如：`补充新品`，优先级 6）；
- 规则 C（如：`补充自有品牌`，优先级 7）；
- 规则 D（如：`销售预测商品`，优先级 18）。

### 生产判定逻辑
在生产打标节点中，通常使用单列 `CASE WHEN` 确定综合原因分类 `reason_zfl`：
```sql
CASE 
    WHEN is_store_cxsp=1 THEN '门店畅销品'
    WHEN is_store_long_sale_item=1 THEN '门店长销商品'
    WHEN is_store_season_sale_item=1 THEN '门店季节性商品' -- 命中直接返回，后续分支全部短路
    ...
    WHEN is_new_product_add_or_delete_code=1 THEN '补充新品'
    WHEN is_zypp_item_action_code=1 THEN '补充自有品牌商品'
    WHEN is_xsbd_item=1 THEN '销售预测商品'
    ELSE '未知' END as is_3he1_fl
```

### 完整性风险与对策
当业务要求对“部分季节性商品执行专项剔除或质量核验”时，直接按 `reason_zfl = '门店季节性商品'` 过滤会将兼具“新品”、“自有品牌”、“销售预测”等正当属性的记录一并移除。因此必须穿透到底层明细标志位独立判断。

---

## 2. 标准排查步骤 (Three-Gate Screening)

### Step 1: 追溯生产源头优先级清单 (Source Lineage)
查阅生产节点的源头 SQL 脚本，完整列出目标原因分类（Target Reason）以及所有排在其后面的低优先级候选原因（Lower-Priority Reasons）。

### Step 2: 提取底层模型独立标志位 (Full Flags Probe)
穿透到明细打标底表，提取所有独立模型标志位字段：
- `is_new_product_add_or_delete_code`（补充新品）
- `is_zypp_item_action_code`（补充自有品牌）
- `is_xsbd_item`（销售预测商品）
- `is_brand_item`（品牌商品）
- `is_add_push_class_item`（补充主推）
- `is_add_top_varieties`（补充品种齐全）
- `is_o2o_store_item` / `is_o2o_key_item`（O2O渠道品）
- `is_bp` / `is_cjzzy` / `is_xshch` / `is_zdsp` / `is_bsml`（策略必选系列）
- `is_shougong_add`（业务手工增加）

### Step 3: 两阶段纯净集合隔离 (Pure Set Isolation)
运用两阶段集合运算，精确分离单一规则记录与复合属性记录：

```sql
-- 阶段一：识别命中目标原因但兼具其他合法资格的记录（保护集）
WITH protected_items AS (
    SELECT 
        store_code,
        item_code,
        1 as has_legitimate_backup
    FROM dwd_store_item_detail
    WHERE pt = MAX_PT('dwd_store_item_detail')
      AND (
          COALESCE(is_new_product_add_or_delete_code, 0) = 1 OR
          COALESCE(is_zypp_item_action_code, 0) = 1 OR
          COALESCE(is_xsbd_item, 0) = 1 OR
          COALESCE(is_brand_item, 0) = 1 OR
          COALESCE(is_shougong_add, 0) = 1
      )
)
-- 阶段二：仅提取纯粹因目标规则入选、无任何备用正当理由的纯净集合
SELECT 
    base.*
FROM dwd_store_item_marked base
LEFT JOIN protected_items p
  ON base.store_code = p.store_code 
 AND base.item_code = p.item_code
WHERE base.pt = MAX_PT('dwd_store_item_marked')
  AND base.reason_zfl = '门店季节性商品'
  AND p.has_legitimate_backup IS NULL; -- 严格仅针对纯净集合操作
```

---

## 3. 分析报告交付标准 (Delivery Standards)
在交付需求分析与画像结论时，明确包含以下量化说明：
1. 涉及原因短路的上下游 SQL 节点 ID 与血缘层级；
2. 目标分类的总行数、保护集行数与纯净集行数分布；
3. 兼具多种属性的重叠构成明细（如新品、自有品牌、预测品的重叠比例）。
