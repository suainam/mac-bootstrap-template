# Analytics skill 规范验证

2026-11-04；范围：五阶段入口、共享契约、旧 ps-analytics 迁移。

## 离线场景走查

方式：人工按任务逐步读取入口和引用，检查分支、产物及完成条件。
这是文档路径走查，不是独立模型评测或生产业务回放。

| 输入场景 | 路径与预期 | 结果 |
|---|---|---|
| 临时查询区域仓库数量 | intake 摸底 → analysis 锁定仓库粒度 → execution 按锁定粒度 → delivery MD+HTML；不要求店品明细 | 正文支持；锁定卡原有新店章节已标条件适用 |
| 对比历史月份 | analysis 查证快照 → profiling reference → solution 参数化日期 | 发现参考默认 MAX_PT、NULL 补零冲突，已改为实测快照和待核验语义 |
| 季节性目录剔除 | analysis 掩盖排查 → solution 质量契约 → execution 原因互斥/保护/抽样 → delivery | 路径可达；旧季节性 SQL 只作结构样例，运行前替换快照及缺失语义 |
| 新增区域配置 | intake 范围/日期 → analysis 快照 → solution 差异/恢复 → execution 开发库预演、授权写入与回读 → delivery 证据链 | 五阶段均有分支；未执行实际写入 |
| 仅本地报告、无需外部回写 | delivery MD+HTML → 回读/索引 → 外部动作标未执行 | 默认双交付保留；外部回写不成为无条件前置 |
| 跨年月份展示 | delivery 月份参考 → format_circular_months → 迁入测试 | 迁入工具测试 5 项通过（由生命周期测试子进程执行） |

## 自动验证

- `template/.venv/bin/python -m pytest template/tests/test_analytics_lifecycle.py template/tests/test_audit_execution_sanity.py -q`：29 passed。
- `make -C template skill-check`：通过，141 skills。
- `git -C template diff --check`：通过。

首轮 24 passed / 4 failed：旧结构断言、动词枚举、中文标点链接解析及专题入口覆盖。
保留阶段编号、补回专题交接指针；测试改验逐步完成条件及真实 Markdown/代码路径。
增加历史快照、NULL、新店模板条件、分支明细和默认双交付回归断言。

## 限制与经验

未连接数仓、未生成真实报告、未执行生产调度或外部回写；静态断言不证明模型遵循率。
规范入口时同时追踪模板和参考：正文正确不能抵消下游参考的旧默认值。
脚本中的项目依赖与真实凭据仍需在业务项目环境验收。
