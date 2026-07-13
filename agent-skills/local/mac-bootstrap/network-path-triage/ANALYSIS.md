# network-path-triage 技能分析

---

## 当前状态

### 结构
```
network-path-triage/
├── SKILL.md              (116 行) - 主流程
├── REFERENCE.md          (144 行) - 命令和解释
├── README.md             (43 行) - 概述
├── references/
│   └── platform-mapping.md  (68 行) - 平台映射表
├── scripts/
│   └── check-routes.sh      (工具脚本)
└── examples/
    └── company-hosts.sample.txt
```

### 技能类型
- **步骤驱动**（5 个步骤）
- **跨平台**（macOS / Windows / WSL）
- **企业环境特定**（CorpLink, Clash, PAC, TUN）

---

## 优点分析 ✓

### 1. 符合 writing-great-skills 原则

**✓ Leading Word**:
- "Path-first" 贯穿整个技能
- 清晰表达核心方法论

**✓ 外部引用分层**:
- SKILL.md: 流程和步骤
- REFERENCE.md: 命令和解释清单
- references/: 平台映射

**✓ 完成标准明确**:
- 每个步骤都有可验证的 completion criterion
- 最终交付固定 schema（7 个字段）

**✓ 单一真身**:
- 命令在 REFERENCE.md
- 平台差异在 platform-mapping.md

**✓ 正向指导为主**:
- "Prove which layer" 而非 "不要猜测"
- 虽有 6 条 "Do not" 规则，但都是关键约束

### 2. 结构清晰

- 步骤有清晰的输入/输出
- 固定交付 schema
- 平台分支明确

### 3. 工具支持

- `check-routes.sh` 提供自动化路由检查
- 示例文件提供参考输入

---

## 改进机会 △

### 1. 缺少故障排查手册（中优先级）

**当前**: 描述了诊断流程，但缺少常见问题快速查找

**建议**: 添加 `references/TROUBLESHOOTING.md`

**内容**:
```markdown
# 常见网络问题故障排查

## 症状索引
- 浏览器无法访问内网，但 curl 可以 → PAC 配置问题
- 所有工具都无法访问内网 → TUN 路由问题
- WSL 无法访问，macOS 可以 → 防火墙/子网排除问题
- 间歇性连接失败 → DNS/代理池问题

## 问题模式
### 浏览器 vs CLI 差异
### 内网 vs 外网差异  
### Host vs WSL 差异
### 公司域名解析异常

## 快速诊断命令
```

**价值**: 
- 快速定位问题类型
- 减少完整流程时间（症状 → 直接跳到可能的层）

### 2. 缺少实战案例（低优先级）

**当前**: 方法论完整，但缺少端到端示例

**建议**: 添加 `references/CASE_STUDIES.md`

**内容**:
```markdown
# 实战案例

## 案例 1: 浏览器访问内网失败，curl 正常
- 症状描述
- 诊断过程（按 5 步）
- 发现: PAC 返回 DIRECT，但应该走 proxy
- 修复: 更新 PAC 规则
- 验证

## 案例 2: WSL 无法访问公司服务，Windows 正常
...

## 案例 3: CN 域名意外走了代理
...
```

**价值**:
- 学习完整诊断流程
- 理解"path-first"方法论的应用

### 3. 命令参考可以增强（中低优先级）

**当前**: REFERENCE.md 有命令列表，但缺少解释

**建议**: 为每个命令添加：
- **用途**: 检查什么层
- **预期输出**: 正常/异常的样子
- **常见陷阱**: 误解释

**示例改进**:
```markdown
## 系统代理检查

### 命令
```bash
networksetup -getautoproxyurl Wi-Fi
```

### 用途
检查当前网络接口是否配置了 PAC

### 预期输出
```
# 配置了 PAC
Enabled: Yes
URL: http://pac.example.com/proxy.pac
# 或
Enabled: No
```

### 解释
- `Enabled: Yes` 表示浏览器会使用 PAC
- PAC URL 应该是公司提供的地址
- 如果是 `Enabled: No` 但内网可访问，说明走的是其他层（TUN/Mihomo）

### 常见陷阱
- PAC 启用不代表所有流量都走 PAC（可能有 TUN 劫持）
- 需要配合 browser devtools 查看实际使用的代理
```

### 4. 跨平台覆盖不均衡（低优先级）

**当前**:
- macOS: 详细命令和示例
- Windows: 仅有概念和注意事项
- WSL: 仅有概念

**建议**: 如果有 Windows 环境，补充：
- `references/WINDOWS_COMMANDS.md` - Windows 等价命令
- `references/WSL_GUIDE.md` - WSL 特定诊断

**但注意**: 如果实际只在 macOS 使用，无需强行扩展

---

## 优化建议总结

### 高优先级
无 - 当前技能已经很好

### 中优先级
1. **添加 TROUBLESHOOTING.md** （症状索引 + 快速诊断）
   - 按症状分类常见问题
   - 提供快速诊断路径
   - ~150-200 行

### 低优先级
2. **添加 CASE_STUDIES.md** （实战案例）
   - 3-5 个完整诊断案例
   - 展示"path-first"方法论应用
   - ~200-300 行

3. **增强命令参考** （REFERENCE.md）
   - 每个命令添加：用途、预期输出、解释、陷阱
   - 当前 144 行 → ~250 行

4. **补充 Windows/WSL 命令**（如有需要）
   - Windows 等价命令指南
   - WSL 特定诊断流程

---

## 与其他技能对比

| 方面 | network-path-triage | decrypt-materialize | sql-analysis |
|------|---------------------|---------------------|--------------|
| **类型** | 步骤 + 诊断 | 步骤 + 工具 | 原则 + 模板 |
| **结构** | 很好 | 优秀 | 优秀（刚优化） |
| **文档** | 完整 | 非常完整 | 非常完整（刚优化） |
| **可执行性** | 命令清晰 | 脚本完整 | 模板完整 |
| **故障排查** | 缺少 | 完整 | 完整（刚添加） |
| **示例** | 缺少端到端 | 完整 | 完整（刚添加） |

---

## 优化优先级评估

### 是否需要立即优化？

**否** - 原因：

1. **技能质量已高**
   - 结构清晰
   - 步骤明确
   - 完成标准可验证
   - 符合 writing-great-skills 原则

2. **改进点是"锦上添花"**
   - TROUBLESHOOTING.md 可以加速诊断，但当前流程已工作
   - CASE_STUDIES.md 有助学习，但方法论已清楚
   - 命令增强会更友好，但当前已可用

3. **ROI 相对较低**
   - network-path-triage 使用频率可能不如 sql/python-analysis
   - 企业环境特定，可能不是通用需求

### 建议时机

**如果出现以下情况再优化**:
1. 实际使用中频繁遇到相同问题 → 添加 TROUBLESHOOTING
2. 新用户难以理解流程 → 添加 CASE_STUDIES
3. 命令输出经常被误解 → 增强 REFERENCE.md
4. 需要支持 Windows 团队 → 补充 Windows 命令

---

## 立即行动建议

### 选项 A: 保持现状（推荐）
- 技能已经很好
- 专注其他更高优先级工作

### 选项 B: 快速增强（如需要）
```bash
# 1. 添加症状索引（最高价值/成本比）
touch references/TROUBLESHOOTING.md

# 内容：
# - 5-10 个常见症状模式
# - 每个症状的快速诊断命令
# - 指向 SKILL.md 对应步骤
# 工作量: ~1 小时
```

### 选项 C: 全面优化
- 添加 TROUBLESHOOTING.md (~1 小时)
- 添加 CASE_STUDIES.md (~1.5 小时)
- 增强 REFERENCE.md (~1 小时)
- 总计: ~3.5 小时

---

## 结论

**network-path-triage 是一个高质量的技能**，符合最佳实践：
- ✓ Leading word 清晰
- ✓ 外部引用分层
- ✓ 完成标准可验证
- ✓ 跨平台支持
- ✓ 工具脚本配套

**改进空间存在但非紧急**：
- △ 可添加故障排查索引（加速诊断）
- △ 可添加实战案例（辅助学习）
- △ 可增强命令解释（减少误解）

**建议**：
- 如果当前使用顺畅 → 保持现状
- 如果实际遇到重复问题 → 添加 TROUBLESHOOTING.md
- 如果时间充裕 → 可以全面优化

与刚优化的 sql/python-analysis 不同，这个技能**不需要大规模重构**，只需要按需补充参考文档。
