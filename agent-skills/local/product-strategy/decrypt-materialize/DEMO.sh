#!/bin/bash
# 快速演示脚本（不需要实际安装依赖）

cat << 'EOF'
=================================================================
decrypt-materialize Skill 优化完成
=================================================================

✅ 完成的改动：

1. SKILL.md 精简
   - 从 150+ 行精简到 50 行
   - 使用 progressive disclosure 将详细内容移到 references/
   - 保持清晰的两分支结构

2. 新增参考文档（references/）
   - WORKBOOK_PROCESS.md — 工作簿物化详细流程（5 步）
   - SMUDGED_TEXT.md — Smudged 文本处理指南
   - EXAMPLES.md — 8 个完整使用示例
   - TESTING.md — 测试指南和回归清单
   - OUTPUT_CONTRACT.md — 更新为中文，单下划线命名

3. 统一脚本 materialize.py
   - 自动检测格式（.numbers / .xlsx / .xls）
   - 自动检测加密状态
   - 统一的命名规范：{workbook}_{sheet}_{date}.csv
   - 单下划线分隔（不使用双下划线）
   - JSON 格式输出

4. 测试脚本 test_materialize.py
   - 基本导出测试
   - 工作表映射测试
   - 命名规范验证
   - 加密检测测试

=================================================================
使用示例
=================================================================

# 快速导出（所有工作表）
python3 scripts/materialize.py ~/Downloads/数据.xlsx

# 指定输出目录和日期
python3 scripts/materialize.py ~/Downloads/数据.xlsx \
  --output-dir ~/staging/ \
  --date-tag 20260713

# 选择性导出（工作表映射）
python3 scripts/materialize.py ~/Downloads/产品数据.xlsx \
  --output-dir ~/staging/ \
  --date-tag 20260713 \
  --sheet-map '{"商品信息":"product_info","销售数据":"sales_data"}'

# 输出格式示例
{
  "source": "/path/to/workbook.xlsx",
  "workbook_name": "workbook",
  "encrypted": false,
  "date_tag": "20260713",
  "sheets": [
    {
      "sheet": "Sheet1",
      "file": "/path/to/workbook_Sheet1_20260713.csv",
      "rows": 100,
      "cols": 5,
      "verified": true
    }
  ]
}

=================================================================
文件结构
=================================================================

decrypt-materialize/
├── SKILL.md                          # 精简的主入口（50 行）
├── scripts/
│   ├── materialize.py               # 🆕 统一脚本
│   ├── test_materialize.py          # 🆕 测试脚本
│   ├── numbers_to_csv.py            # 保留（兼容性）
│   └── workbook_to_staging_csv.py   # 保留（兼容性）
└── references/
    ├── WORKBOOK_PROCESS.md          # 🆕 工作簿流程详解
    ├── SMUDGED_TEXT.md              # 🆕 Smudged 文本指南
    ├── EXAMPLES.md                  # 🆕 8 个完整示例
    ├── TESTING.md                   # 🆕 测试指南
    ├── OUTPUT_CONTRACT.md           # ✏️ 更新为中文+单下划线
    └── NUMBERS_NOTES.md             # 保留

=================================================================
关键改进
=================================================================

✅ 命名规范统一
   旧: workbook__sheet__20260713.csv  (双下划线)
   新: workbook_sheet_20260713.csv    (单下划线)

✅ 加密检测优先
   先尝试打开 → 失败时报告原因（密码/损坏/其他）

✅ 格式自动识别
   不需要用户区分 .numbers vs .xlsx，统一入口

✅ 工作簿名称保留
   输出文件名包含源工作簿名称和工作表名称

✅ Smudged 文本扩展
   不枚举类型，用识别模式自动支持所有文本格式
   (.yaml .yml .toml .json .ini .conf .env .properties 等)

=================================================================
下一步
=================================================================

1. 安装依赖（如需测试）：
   pip3 install openpyxl numbers-parser==4.18.5

2. 运行测试：
   python3 scripts/test_materialize.py

3. 查看示例：
   cat references/EXAMPLES.md

4. 查看测试指南：
   cat references/TESTING.md

=================================================================
EOF
