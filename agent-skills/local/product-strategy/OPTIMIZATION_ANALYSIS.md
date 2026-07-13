# 本地技能优化建议

基于 writing-great-skills 原则分析 product-strategy 本地技能。

---

## 技能概览

| 技能 | 大小 | 结构 | 状态 |
|------|------|------|------|
| decrypt-materialize | 4 分支 + 9 参考文档 | ✓ 完整 | 刚优化完成 |
| python-data-analysis | 31 行单文件 | △ 简洁 | 可增强 |
| sql-analysis | 31 行单文件 | △ 简洁 | 可增强 |
| web-video-presentation-delivery | 136 行 + 1 参考 | ○ 中等 | 有改进空间 |

---

## 1. python-data-analysis

### 当前状态
- **类型**: 全参考（无步骤）
- **长度**: 31 行
- **结构**: 单文件 SKILL.md
- **风格**: 清晰、简洁、可执行

### 优点 ✓
1. **紧凑**: 符合 "不为了拆分而拆分" 原则
2. **可检查的完成标准**: "validate row counts", "report assumptions"
3. **正向指导**: "Prefer X" 而非 "Don't Y"
4. **Leading words**: "reproducible", "grain", "schema"

### 改进机会 △

#### 1.1 外部引用机会
**当前**: 所有内容在一个文件
**问题**: 如果添加示例、故障排查、常见数据质量问题，会导致 sprawl
**建议**:
```
python-data-analysis/
├── SKILL.md              # 保持当前简洁核心
└── references/
    ├── EXAMPLES.md       # 常见分析模式（探索性 vs 报告）
    ├── DATA_QUALITY.md   # 数据质量检查清单
    └── STACK_CHOICES.md  # pandas vs polars vs duckdb 选择指南
```

#### 1.2 完成标准可测性
**当前**: "Report assumptions, data-quality caveats"
**改进**: 
```markdown
完成标准：
- [ ] 数据源、时间范围已记录
- [ ] 每个 join 后行数已验证
- [ ] 解析失败率 < 5% 或已说明
- [ ] 最终结果包含行数、列数、时间戳
```

#### 1.3 跨平台考虑
**当前**: 假设 Unix 环境（`uv` 命令）
**建议**: 添加 Windows 路径和命令示例

**优先级**: 低 - 技能已经很好，只在扩展时优化

---

## 2. sql-analysis

### 当前状态
- **类型**: 全参考（无步骤）
- **长度**: 31 行
- **结构**: 单文件 SKILL.md
- **风格**: 清晰、实用

### 优点 ✓
1. **检查清单式**: "Confirm grain", "Inspect nulls", "Verify row counts"
2. **具体建议**: "Use CTEs for logical stages"
3. **避免陷阱**: "Before a join, test key uniqueness"

### 改进机会 △

#### 2.1 外部引用（中优先级）
**建议结构**:
```
sql-analysis/
├── SKILL.md
└── references/
    ├── PROFILING_CHECKLIST.md    # 表分析清单模板
    ├── JOIN_PATTERNS.md           # 常见 join 问题和验证 SQL
    ├── DUCKDB_RECIPES.md          # CSV/Parquet 本地分析示例
    └── NAMING_CONVENTIONS.md     # 指标命名规范
```

**理由**: 
- 当前技能完美简洁
- 但缺少"可复用的 SQL 片段"
- profiling query 模板会很有用

#### 2.2 验证 SQL 示例
**当前**: 描述式（"test key uniqueness"）
**改进**: 添加可执行 SQL 模板
```sql
-- references/JOIN_PATTERNS.md
-- 验证左表键唯一性
SELECT key, COUNT(*) as n
FROM left_table
GROUP BY key
HAVING n > 1;

-- 验证 join 覆盖率
SELECT 
  COUNT(*) as left_rows,
  COUNT(r.key) as matched_rows,
  COUNT(*) - COUNT(r.key) as unmatched_rows
FROM left_table l
LEFT JOIN right_table r ON l.key = r.key;
```

**优先级**: 中 - 会显著提升实用性

---

## 3. web-video-presentation-delivery

### 当前状态
- **类型**: 步骤 + 参考
- **长度**: 136 行 + 64 行参考
- **结构**: SKILL.md + REFERENCE.md
- **风格**: 详细、防御性强

### 优点 ✓
1. **单一路径强制**: "Do not add a second recording path"
2. **验证顺序**: "browser playback works" before "OBS capture"
3. **外部参考**: REFERENCE.md 分离命令和非目标
4. **完成标准**: "Deliverables" 部分清晰

### 问题识别 ✗

#### 3.1 Sprawl（轻微）
**症状**: SKILL.md 136 行，包含大量"不要做X"
**问题**: 
- 第 86-92 行：4 个 "Do not reintroduce" 项
- 第 57-64 行：重复强调 "reuse existing"
- 历史包袱多（防止回退到旧方案）

**建议**: 拆分为
```
web-video-presentation-delivery/
├── SKILL.md                  # 核心流程（压缩到 80 行）
└── references/
    ├── REFERENCE.md          # 已有：命令和配置
    ├── PITFALLS.md           # 新增：历史错误和禁区
    └── TROUBLESHOOTING.md    # 新增：常见问题（OBS 无声等）
```

#### 3.2 Duplication
**重复内容**:
- "single-player path" 在多处强调
- OBS 录制步骤在 SKILL.md 和 REFERENCE.md 都有

**建议**: 
- SKILL.md：高层流程和决策点
- REFERENCE.md：具体命令（单一真身）
- 交叉引用而非复制

#### 3.3 Negation 过多
**当前**: 10+ 处 "Do not", "Never", "Avoid"
**问题**: 按 writing-great-skills，negation 使禁止的东西更突出

**改进策略**:
```markdown
# 当前
Do not add a second recording path
Do not reintroduce browser MediaRecorder
Do not use file:// recording workflows

# 改进后（正向描述 + 单一禁区列表）
Recording path: OBS manual capture only
(See references/PITFALLS.md for retired approaches)
```

**优先级**: 中高 - 会提升可读性和维护性

---

## 4. decrypt-materialize（对比参考）

### 已优化特征 ✓
1. **外部引用分层**: 9 个参考文档，SKILL.md 保持 <100 行
2. **单一真身**: 脚本是行为定义，文档引用脚本
3. **可验证完成标准**: "文件头 = `SQLite format 3`"
4. **压缩 sprawl**: CODEX_TSD.md 从 200+ 行压缩到 100 行
5. **跨平台**: 自动检测并适配
6. **正向指导**: 很少使用 "不要"

**可作为其他技能的模板参考**

---

## 优化优先级总结

### 高优先级
1. **web-video-presentation-delivery**
   - 压缩 SKILL.md（移除重复和负面指导）
   - 拆分 PITFALLS.md 和 TROUBLESHOOTING.md
   - 减少 duplication

### 中优先级
2. **sql-analysis**
   - 添加 references/ 目录
   - 创建可复用 SQL 模板（PROFILING_CHECKLIST.md, JOIN_PATTERNS.md）

### 低优先级
3. **python-data-analysis**
   - 当前已很好，只在扩展时添加 references/
   - 考虑跨平台示例

---

## 通用模式建议

### 参考文档命名规范
```
references/
├── EXAMPLES.md           # 使用示例（端到端）
├── PATTERNS.md           # 常见模式和最佳实践
├── TROUBLESHOOTING.md    # 故障排查（症状 → 解决）
├── PITFALLS.md           # 已知陷阱和禁区
├── CHECKLISTS.md         # 可打印的检查清单
└── <DOMAIN>_GUIDE.md     # 特定领域指南
```

### SKILL.md 理想结构
```markdown
# Skill Name

[1-2 句话概述]

## 流程（如有步骤）
1. Step with completion criterion
2. Step with completion criterion

## 原则（如纯参考）
- Principle 1
- Principle 2

## 完成标准
- [ ] Checkable criterion 1
- [ ] Checkable criterion 2

## 引用
- references/XXX.md — 用途描述
```

### 长度指导
- SKILL.md: 30-100 行理想，<150 行可接受
- 单个 reference: <200 行
- 超过 200 行考虑再拆分

---

## 立即可行动项

### web-video-presentation-delivery
```bash
# 1. 创建新参考文档
mkdir -p references/
touch references/PITFALLS.md
touch references/TROUBLESHOOTING.md

# 2. 移动"不要做"内容到 PITFALLS.md
# 3. 移动 OBS 音频问题到 TROUBLESHOOTING.md
# 4. 压缩 SKILL.md 到 80 行以内
```

### sql-analysis
```bash
# 1. 创建参考目录
mkdir -p references/
touch references/PROFILING_CHECKLIST.md
touch references/JOIN_PATTERNS.md
touch references/DUCKDB_RECIPES.md
```

### python-data-analysis
```bash
# 保持现状，或当需要时：
mkdir -p references/
touch references/EXAMPLES.md
```

---

## 结论

**最需要优化**: web-video-presentation-delivery
- 有明显的 sprawl 和 duplication
- 过多 negation
- 拆分后会更清晰

**次要优化**: sql-analysis
- 当前简洁但可扩展
- 添加可复用 SQL 模板会很实用

**保持现状**: python-data-analysis
- 已经符合最佳实践
- 只在需要扩展时添加 references/

**参考标杆**: decrypt-materialize
- 可作为其他技能的结构模板
