# 业务多模型优先级掩盖排查与防误伤 SOP (Multi-Model Masking Audit)

在多模型组合下发、复合打标的数仓生产链路中，经常出现**高优先级规则短路掩盖低优先级属性**的业务陷阱。本 SOP 规定了排查与剔除异常数据时避免误伤正当入选品的操作标准。

---

## 1. 核心业务痛点：优先级掩盖陷阱 (Priority Masking)

### 典型场景
在 3合1 组货目录或品类规划中，同一商品在同一门店可能同时满足：
- 规则 A（如：`门店季节性商品`，假设优先级为 3）；
- 规则 B（如：`补充新品`，假设优先级为 6）；
- 规则 C（如：`补充自有品牌`，假设优先级为 7）；
- 规则 D（如：`销售预测商品`，假设优先级为 18）。

### 生产判定逻辑
在生产打标节点（如 DataWorks `10002161979`）中，通常使用单列 `CASE WHEN` 确定综合原因分类 `reason_zfl`：
```sql
CASE 
    WHEN is_store_cxsp=1 THEN '门店畅销品'
    WHEN is_store_long_sale_item=1 THEN '门店长销商品'
    WHEN is_store_season_sale_item=1 THEN '门店季节性商品' -- 命中直接返回，后面分支全部短路！
    ...
    WHEN is_new_product_add_or_delete_code=1 THEN '补充新品'
    WHEN is_zypp_item_action_code=1 THEN '补充自有品牌商品'
    WHEN is_xsbd_item=1 THEN '销售预测商品'
    ELSE '未知' END as is_3he1_fl
```

### 误伤风险
如果业务发现“部分季节性商品不合规需要拦截剔除”，**若仅凭 `reason_zfl = '门店季节性商品'` 粗暴过滤，就会将原本享有“新品”、“自有品牌”、“销售预测”等正当入选资格的商品一同错误下架！**

---

## 2. 标准排查 SOP (Three-Gate Screening)

### Step 1: 追溯生产源头优先级清单
严禁仅凭表结构注释推测；必须拉取生产节点的源头 SQL，完整列出目标原因（Target Reason）以及所有排在其后面的低优先级候选原因（Lower-Priority Reasons）。

### Step 2: 关联底层模型标志位全集 (Full Flags Probe)
穿透到底层明细打标表（如 `list_df`），提取所有独立模型标志位列：
- `is_new_product_add_or_delete_code`（补充新品）
- `is_zypp_item_action_code`（补充自有品牌）
- `is_xsbd_item`（销售预测商品）
- `is_brand_item`（品牌商品）
- `is_add_push_class_item`（补充主推）
- `is_add_top_varieties`（补充品种齐全）
- `is_o2o_store_item` / `is_o2o_key_item`（O2O渠道品）
- `is_bp` / `is_cjzzy` / `is_xshch` / `is_zdsp` / `is_bsml`（策略必上系列）
- `is_shougong_add`（业务手工增加）

### Step 3: 两阶段真集过滤 (Pure Set Isolation)

1. **圈定粗集**：
   ```sql
   WHERE x.is_3he1_list = 1 AND x.reason_zfl RLIKE '季节'
   ```
2. **剔除所有低优先级重叠属性，锁定绝对纯真集**：
   ```sql
   WHERE NOT (
       COALESCE(x.is_shougong_add, 0) = 1
       OR COALESCE(x.is_bp, 0) = 1
       OR COALESCE(x.is_cjzzy, 0) = 1
       OR COALESCE(x.is_xshch, 0) = 1
       OR COALESCE(x.is_zdsp, 0) = 1
       OR COALESCE(x.is_bsml, 0) = 1
       OR COALESCE(l.is_brand_item, 0) = 1
       OR COALESCE(l.is_add_push_class_item, 0) = 1
       OR COALESCE(l.is_add_top_varieties, 0) = 1
       OR COALESCE(l.is_xsbd_item, 0) = 1
       OR COALESCE(l.is_ky_djp_item, 0) = 1
       OR COALESCE(l.is_rxkp_item, 0) = 1
       OR COALESCE(l.is_new_product_add_or_delete_code, 0) = 1
       OR COALESCE(l.is_zypp_item_action_code, 0) = 1
       OR COALESCE(l.is_zlcjp, 0) = 1
       OR COALESCE(l.is_qlp, 0) = 1
       OR COALESCE(l.is_o2o_store_item, 0) = 1
       OR COALESCE(l.is_o2o_key_item, 0) = 1
   )
   ```

---

## 3. 验收标准
- 过滤后产出的每一条店品记录，必须满足：**在整个组货算法链路中，除了目标模型外，绝对没有第二重入选依据**。
- 对过滤前后的行数与剔除的重叠构成进行量化说明（例如：18.7 万跨期数据中，精确识别出 3.0 万条属于新品/预测/自有品牌重叠，最终锁定 15.7 万条纯粹违规商品）。
