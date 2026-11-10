# PRD 评分优化 — 已验证踩坑记录

每次优化循环遇到下列问题，按此结论处理，勿重复发现。

## 迭代闭环（必须先跑通）
- 目标：保存 → 等缓存（约 35s）→ 重算 → 读全量 `issues` → 定点修订 → 再循环，直至用户约定分数。
- **评分器极严格且每次重算会触发新一轮问题**：修完当前一轮 issues 后重算可能冒出新问题（引用新文本）。一次通过不成立；必须循环到达标。
- 首个重算结果常返回旧分（OSS 缓存）。保存后务必等 ~35s 再重算，不以首次结果为准。
- 记录每轮 `final_score`、维度与 `issues` 严重级别/问题/建议/证据位置；对比分数与问题数，别只看其一。

## 保存（POST /api/product-agent/prd/save）
- `created_by` 用 `localStorage["Operator-Name"]`；`localStorage["username"]` 常为空。
- 保存不回显新版本号，更新的仍是当前槽；`module_id` 取返回 `file_path` 中的 `module_<id>`。
- 保存后仍需取读实际持久化 md（GET `file_path`）核对关键修复标记，勿只看编辑器 DOM。

## 工具脚本（prd_workbench.mjs）
- `save`/`dump` 依赖 React fiber 定位 `prd_id`；页面 reload 进只读后，先点「编辑」恢复 fiber，否则 `save` 报「未找到 PRD 实体 ID」。
- `audit` 的 32 标准字段检查与本平台真实评分无关，勿据此改文档结构。
- huashu-chrome `act` 单动作接口可能报 `steps 不能为空`，改用 `eval`/顶层 fetch。

## 思想（单源统一）
- 同一规则只在一处定义，其余引用；评分器会对任何残留表述（兜底优先级、阈值、容差）重新触发 blocker/major。
- 评分建议不证明业务规则存在；缺影响行为的事定时先与用户确认或标注待确认，不为提分虚构。
