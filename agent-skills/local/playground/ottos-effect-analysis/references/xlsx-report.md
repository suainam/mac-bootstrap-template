# xlsx 效果分析报告生成（按需查阅）

报告用 `scripts/build_report.py` 生成，不要手写 openpyxl 样板。你只准备一个描述报告内容的
JSON 配置，脚本负责出统一样式的多 sheet xlsx（标题合并单元格、表头蓝底白字、正向绿字/负向红字、
结论区浅黄底、列宽自适应）。

## 用法

```bash
python3 scripts/build_report.py config.json [输出文件.xlsx]
python3 scripts/build_report.py                 # 不带参数会打印完整配置示例
```

## 配置结构

```json
{
  "strategy_name": "门店自动陈列",
  "date_range": "2026-03 ~ 2026-05",
  "version": "v0.x 草稿",
  "summary": {
    "one_line": "一句话结论",
    "key_metrics": [["动销率净效果", "+4pp"], ["米效净效果", "+5.9%"]],
    "confidence": "中",
    "confidence_basis": "可信度依据",
    "next_step": "下一步建议",
    "risks": "风险/代价"
  },
  "sheets": [
    {
      "name": "同比趋势",
      "headers": ["指标", "去年同期", "今年", "同比变化"],
      "rows": [
        ["动销率", 0.42, 0.46, "=C2-B2"],
        ["米效(元/米/天)", 85, 90, "=C3-B3"]
      ],
      "pct_cols": [2, 3],
      "signed_cols": [4],
      "note": "底部小字备注，可选"
    }
  ]
}
```

- **summary** 渲染成 Sheet1「总览与结论」；省略的字段留空。
- **sheets** 每个生成一个数据 sheet，顺序即 sheet 顺序。
- **列索引**（`pct_cols` / `signed_cols` / `num_cols`）一律 1 起列号（A=1, B=2 …）。
  - `pct_cols`：按百分比 `0.0%` 显示（值要填小数，如 0.46 显示 46.0%）。
  - `num_cols`：千分位整数 `#,##0`。
  - `signed_cols`：按正负上色（正绿负红）。用条件格式按单元格**实际值**染色，所以公式列（如 `=C2-B2`）也能正确区分正负。
- **公式**：`rows` 里以 `=` 开头的单元格原样写入，由 Excel/LibreOffice 打开时计算，符合"用公式不硬编码"。

## 建议的 sheet 组成

按场景选，不是每个都要：

| Sheet | 路径 A（有 AB） | 路径 B（无 AB） |
|-------|----------------|----------------|
| 总览与结论 | 必出 | 必出 |
| 核心对比 | 实验组 vs 对照组（含 p 值、是否显著） | 同比趋势（今年/去年同期/同比变化） |
| 区域明细 | 按区域拆解的实验效果 | 试点区域 vs 上层整体 + DID 净效果 |
| 匹配对照门店 | — | 配对列表 + 平行趋势 + DID（可由 did_analysis.py 结果填充） |
| 细分维度 | 按品类/门店特征/时间拆解，标注最好/最差细分 | 同左 |

## 公式校验（可选）

含公式时，如需在交付前确认无 `#REF!`/`#DIV/0!`，用 xlsx skill 的 recalc.py：

```bash
python3 <xlsx-skill>/scripts/recalc.py 输出文件.xlsx
```
