# decrypt-materialize Skill 优化总结

## 优化完成情况

### ✅ 1. Skill 文件精简（符合 writing-great-skills 原则）

**优化前**: 原 SKILL.md 包含大量详细步骤和示例
**优化后**: SKILL.md 精简到 58 行

- 使用 **progressive disclosure**：详细内容移到 references/
- 保持清晰的**两分支结构**
- 明确的**完成标准**（completion criterion）
- 使用中文编写

### ✅ 2. 命名规范统一

**核心改进**：
- 旧格式: `workbook__sheet__20260713.csv` （双下划线 `__`）
- 新格式: `workbook_sheet_20260713.csv` （单下划线 `_`）

**命名模式**: `{工作簿名}_{工作表名}_{日期标签}.csv`

示例：
- `Q2_Sales.numbers` 的 `Summary` 工作表 → `Q2_Sales_Summary_20260713.csv`
- `产品数据.xlsx` 的 `商品信息` 工作表 → `产品数据_商品信息_20260713.csv`

### ✅ 3. 统一脚本 materialize.py

**核心功能**：
- 自动检测格式（.numbers / .xlsx / .xls）
- **先尝试打开，再检测加密**（而不是先假设加密）
- 统一的命名规范
- JSON 格式输出

**使用示例**：
```bash
# 简单导出
python3 scripts/materialize.py ~/Downloads/数据.xlsx

# 完整参数
python3 scripts/materialize.py ~/Downloads/产品数据.xlsx \
  --output-dir ~/staging/ \
  --date-tag 20260713 \
  --sheet-map '{"商品信息":"product_info"}'
```

### ✅ 4. Smudged 文本扩展

**优化策略**：不枚举文件类型，使用**识别模式**

**识别模式**：
- Read 工具返回乱码/二进制
- 文件扩展名表明是文本格式
- 自动支持：.yaml, .yml, .toml, .json, .ini, .conf, .env, .properties 等

**处理方式**：
- 绕过 Read 工具，直接访问磁盘文件
- 编辑时修改明文，git-clean 自动重新加密

## 新增文档（Progressive Disclosure）

| 文件 | 行数 | 用途 |
|------|------|------|
| `SKILL.md` | 58 | 主入口，精简流程 |
| `references/WORKBOOK_PROCESS.md` | 192 | 工作簿物化详细步骤（5 步） |
| `references/SMUDGED_TEXT.md` | 168 | Smudged 文本处理指南 |
| `references/EXAMPLES.md` | 272 | 8 个完整使用示例 |
| `references/TESTING.md` | 231 | 测试指南和回归清单 |
| `references/OUTPUT_CONTRACT.md` | 52 | 输出规范（已更新） |
| `scripts/materialize.py` | 304 | 统一脚本 |
| `scripts/test_materialize.py` | 233 | 自动化测试 |

## 符合的 writing-great-skills 原则

### ✅ Progressive Disclosure
- 核心流程在 SKILL.md（58 行）
- 详细步骤在 WORKBOOK_PROCESS.md（192 行）
- 示例在 EXAMPLES.md（272 行）
- 测试在 TESTING.md（231 行）

### ✅ Single Source of Truth
- 命名规范：OUTPUT_CONTRACT.md
- 工作流程：WORKBOOK_PROCESS.md
- 不重复定义

### ✅ Leading Words
- **物化**（materialization）：核心概念
- **Smudged**：git-smudge 加密模式
- **暂存 CSV**（staging CSV）：输出类型

### ✅ Completion Criterion
每个步骤都有明确的完成标准：
- "工作簿可以无错误加载，或明确报告阻塞原因"
- "每个目标工作表都有一个写入的 CSV 文件在预期路径"
- "每个 CSV 通过验证，或报告具体失败原因"

### ✅ 避免 Duplication
- 合并 Branch 1（numbers→csv）和 Branch 3（workbook→csv）
- 统一为一个"工作簿物化"流程
- 单一脚本 `materialize.py` 处理所有格式

### ✅ 避免 No-op
- 移除"treat as source of truth"等默认行为的重述
- 聚焦于**识别模式**而非枚举

### ✅ Positive Instructions
- "绕过 Read 工具，直接访问磁盘文件"（而不是"不要用 Read 工具"）
- "先尝试直接打开"（而不是"不要假设加密"）

## 测试覆盖

自动化测试（`test_materialize.py`）：
- ✅ 基本导出（全部工作表）
- ✅ 工作表映射（选择性导出 + 英文命名）
- ✅ 命名规范验证（单下划线 `_`）
- ✅ CSV 验证（行数、列数、禁止值）
- ✅ 加密检测（错误处理）

手动测试场景（`TESTING.md`）：
- Excel 文件导出
- Numbers 文件导出
- 工作表映射
- 加密检测
- Smudged 文本读取/编辑
- 批量处理
- 性能测试

## 兼容性

保留旧脚本以确保向后兼容：
- `scripts/numbers_to_csv.py` — 保留
- `scripts/workbook_to_staging_csv.py` — 保留

新脚本为推荐使用：
- `scripts/materialize.py` — 统一入口

## 使用建议

### 日常使用
```bash
# 推荐：使用统一脚本
python3 scripts/materialize.py <source> --date-tag YYYYMMDD
```

### 工作表映射
```bash
# 选择性导出并使用英文名
python3 scripts/materialize.py source.xlsx \
  --sheet-map '{"中文名":"english_name"}'
```

### Smudged 文本
```bash
# 直接读取（绕过 Read 工具）
cat private/secrets.yaml
python3 -c "import yaml; print(yaml.safe_load(open('private/secrets.yaml')))"
```

## 后续改进建议

1. **添加 .ods 支持**（目前 materialize.py 已声明但未实现）
2. **密码解密支持**（通过 --password 参数）
3. **增量导出**（只导出变更的工作表）
4. **并行处理**（多工作表并行导出）
5. **进度条**（大文件导出时显示进度）

## 文件清单

```
decrypt-materialize/
├── SKILL.md                          # 主入口（58 行）
├── DEMO.sh                           # 演示脚本
├── scripts/
│   ├── materialize.py               # 🆕 统一脚本（304 行）
│   ├── test_materialize.py          # 🆕 测试脚本（233 行）
│   ├── numbers_to_csv.py            # 保留（兼容性，93 行）
│   └── workbook_to_staging_csv.py   # 保留（兼容性，93 行）
└── references/
    ├── WORKBOOK_PROCESS.md          # 🆕 详细流程（192 行）
    ├── SMUDGED_TEXT.md              # 🆕 文本处理（168 行）
    ├── EXAMPLES.md                  # 🆕 使用示例（272 行）
    ├── TESTING.md                   # 🆕 测试指南（231 行）
    ├── OUTPUT_CONTRACT.md           # ✏️ 更新（52 行）
    └── NUMBERS_NOTES.md             # 保留（25 行）
```

总计：1,721 行代码和文档

---

**优化完成时间**: 2026-07-13
**符合标准**: writing-great-skills 全部原则
**测试状态**: 测试脚本已创建，待依赖安装后执行
