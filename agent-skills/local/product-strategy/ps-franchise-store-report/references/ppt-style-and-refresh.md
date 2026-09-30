# 加盟效益单页 PPT：风格与换期规范

适用：复用现有“智能组货-加盟店效益”单页模板，按新的 `project_et` 更新汇报。**范例路径**：`topics/franchise_store/04_outputs/franchise_store_assortment_report_20260927.pptx`（从项目根目录定位；文件可能受 TSD 包装，无法直接打开时先按下文解密）。数据源分别是同日期的 `topics/franchise_store/04_outputs/tables/franchise_store_sale_profit_yoy_<project_et>.xlsx`（全国）与 `franchise_store_area_summary_<project_et>.xlsx`（六大区）。口径以本 Skill 的 [参数契约](parameter-contract.md) 为准；PPT 不是计算源。

## 版式：保留模板，更新数据

- **一页四块**：上方“目标／策略”两行；下方左上“结果呈现”KPI，右上“目录内占比差异”双年横条；左下“目标·策略·规划”，右下“六大区同比差异”表。页底单独放日期及发货窗口注释。保留浅底、绿色标题带与卡片、深灰文字、红色增量；历史静态模板是风格参考，不是本期数值参考。
- **层级**：标题黑色微软雅黑加粗约 24 pt；区块标题深绿 Arial/微软雅黑约 12 pt；主增量红色加粗约 20 pt；表格与横条标签约 8–9 pt。保持原 PPT 字体、间距、对齐、Logo 与分组，不因换数重画整页。
- **语义**：占比“差异”是**百分点**，标签统一 `%`（例如 2025 年 23.8%、2026 年 46.1%，差异 +22.3%）；周转天数为数值相减并用“−… 天”显示下降；公司发货同比为本年/去年 `-1`。六大区顺序与原表一致：华南、西南、北方、西北、华中、华东；负号用 `−`，保留一位小数。
- **横条**：同指标两年等比例，颜色沿用模板浅绿/深绿。六个可见百分比、六根条的长度与标签位置必须一起更新；只改文字会留下与数值矛盾的旧图。
- **静态业务文字**：“99 个营运区”“26Q4 全国推广”等属于当时的策略描述。新期若无已核实的业务依据，保持原文并明确未重新核实，不把店品结果表的“区域行数”冒充推广营运区数。

## 换期数据映射

| PPT 区域 | 同期报表来源 | 检查 |
| --- | --- | --- |
| 结果呈现三项占比提升 | 主报表 `结论-组货口径-结果汇报版本`：`D21` 商品、`E21` 销售、`F21` 毛利 | 与 `D/E/F22 - D/E/F23` 一致，显示一位小数 |
| 发货毛利同比、周转天数 | 主报表 `Y21`、`S21` | 页底发货窗口必须来自 `X19`／日期参数，不用版本日代替发货日 |
| 目录内占比双年横条 | 主报表 `D/E/F23`（去年）、`D/E/F22`（本年） | 两年销售窗口均为含截止日严格 90 天；文字、条宽与末端标注一致 |
| 六大区同比差异 | 大区表 `大区明细` 每区“差异”行的 `D/E/F/M`（商品/销售/毛利占比、周转天数） | 六大区加总与全国总盘门店数、销售额、毛利额、客流通过对账工作表 |

**0927 已验证的示例**：全国商品、销售、毛利占比差异分别 `+22.3% / +25.5% / +24.5%`；双年商品数占比 `23.8% → 46.1%`；公司发货 `+8.3%`，窗口 `5.31–8.28`；华南四列 `25.4% / 26.9% / 25.8% / −8.8`。数字仅作该期对照；下期从新工作簿读取，勿复制示例常量。

## 工具与示例

1. 运行本 Skill 的 Branch B；若有六大区，另运行 Branch C 并确认 `大盘对账与一致性门禁` 全部 PASS。`officecli load_skill pptx` 加载 PPTX 编辑规范；用 `officecli view ... outline`、`annotated` 确认一页结构及嵌套组，`officecli query ... 'shape:contains("旧文案")'` 查目标，再以 `@id=` 路径编辑。
2. 只有 `xxd -l 16 源.pptx` 显示 `%TSD-Header-###%` 时，按 `tsd-binary-preserve-decrypt` 的二进制保真流程或用户调用的 `decrypt-materialize` Skill 用 `decrypt_tsd_binary.py` **另存为 PPTX**，保留原文件；不透明文件不可直接交给 OfficeCLI。解密输出应为 `PK` 头且 `unzip -t` 通过。如果以后被 DLP 重新包装，须重新生成新的明文工作副本验证，不把受包装的文件当成可直接交付的 PowerPoint。
3. 最小文本更新示例（数字来自新期报表，ID 只适用于对应的模板；实际请先 `query`）：
   ```bash
   officecli set 新期.pptx '/slide[1]/group[@id=24]/group[@id=143]/shape[@id=16]' --prop text='+22.3%'
   officecli set 新期.pptx '/slide[1]/group[@id=55]/shape[@id=36]' --prop text='23.8%'
   ```
   再更新对应的横条 `width`、标签 `x`，以及区域 24 个数值、期间和页脚；多处改动优先用 `officecli batch` 原子执行。不要用对全页的通用数字替换：不同区可能有相同百分比。
4. `officecli save 新期.pptx` → `officecli validate 新期.pptx` → `officecli view 新期.pptx issues` → `officecli view 新期.pptx text` → `officecli view 新期.pptx screenshot --page 1 -o /tmp/franchise-ppt-check.png`。逐项复核**横条长度与标注、无重叠/裁切、期间及发货说明、六大区**，与两份 Excel 对照；检查 PPT 包的 `unzip -t`、源文件原始头和哈希。OfficeCLI 对模板布局/母版的未计算日期/页码字段可能仍报缓存提示，须明确报告，不能当作已渲染字段通过。

可调用 Skills：`ps-franchise-store-report`（日期及 ODPS 汇总）、`officecli` + `officecli load_skill pptx`（PPT 检查／修改／截图）、`tsd-binary-preserve-decrypt`（必要时保真解密）；用户主动调用 `decrypt-materialize` 时按该 Skill 分支执行。技术说明与执行示例集中在本页；不新建一套独立 PPT 制作 Skill 或固定日期生成器。
