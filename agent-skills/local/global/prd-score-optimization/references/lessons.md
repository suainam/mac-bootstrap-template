# PRD 评分优化 — 已验证经验与教训

按「流程 → 事实源 → 修订手法 → 工具坑」组织；每条给结论与证据来源。案例全貌见 `case-Story-295628.md`。

## 迭代闭环

- 目标：保存 → 等缓存 → 重算 → 读全量 `issues` → 定点修订 → 循环，直至用户约定分数。
- 评分器每次重算可能引用新文本提出新问题；一次通过不成立，以 `create_time` 变新为准判定拿到新分。
- 首个重算结果可能返回旧分（OSS 缓存）。保存后等约 45s 再点「重新评分」，再看 `score.create_time` 是否晚于保存时刻。
- Story-295628 实测：2 轮保存、2 次有效重算，76.1 → 85.8 → 89.3；第 1 轮解决 7 项里的 3 项 major，第 2 轮解决 AC 与表述冲突。

## 事实源（grounded）

- 原始需求 = `currentStory.description`（HTML，评分按钮 fiber 向上取）。每条数值、阈值、范围的判据只能来自它或用户。
- 评分建议不证明业务事实。建议要求补「rule_id↔省区一一映射」「配置字段清单」「数据留存策略」而原始需求没有这些事实时，不虚构；留在汇报中交用户决定。Story-295628 最终剩 5 条此类/时序类建议，分数仍 89.3。
- 同一个「待确认事项」若原始需求已有答案（如「基础准入与二次上架判断同步调整」），改写成「已确认口径」并引用原始 Story，评分器会撤销「边界未定」major；原始需求没有答案才保留待确认。

## 修订手法

- **单源定义**：同一规则只在一处定义（如业务规则 N），其余章节写「按业务规则 N」。评分器对重复表述里的任一残留矛盾重新提 major（d3 一致性最严）。
- **模糊口径换固定值**：「合理范围」「如±10%」「无异常波动」触发 d4 major + d2 minor。换成原始需求中的固定基准与偏差（本案：四项数值逐项相等，允许偏差 0）；原始需求里的模糊结论只留作背景，不再作判定口径。
- **一个词一个冲突**：「长期生效」vs 配置日期窗口、「确保配置即时生效」vs 20261110 起生效、「窗口内完成重跑」vs 分区日期。把「规则」与「配置」拆成两个独立对象，各自写生效期，并写明互不影响。
- **验收项单一职责**：AC-04 只判任务状态，AC-05 判数值；同一组数值只在一个 AC 出现。基础准入、二次上架、中参每个阈值组各有一条 AC 覆盖。
- **保存前 grep 旧句**：对旧模糊词（`合理范围|±10%|历史单省区|待确认事项`）整文检索；本案第一轮检出 3 处残留（业务规则、风险、依据表）。
- **平台标题格式**：`### 量化目标（baseline→target）` 全角括号；`## 5.` 小节名改成「已确认口径与风险」后评分器仍识别。
- **符号一致**：同一指标在不同判断项里 `>` 与 `≥` 并存会被提 d2 minor；若原始需求就是两种符号，在文中点明两者属不同判断项。

## 数据定位（React fiber）

- 正文：`.vditor` 向上 fiber 的 `prdMdContent`；持久化 md：`backendPrd.filePath`（OSS，`fetch` 即可）。
- 评分：评分按钮向上 fiber 的 `props.score`（framework v2.0.0，含完整 `issues[]`，不必点「展开其余 N 条」）。`v13ScoreState.score.final_score`（60）、`scoreData.overall_score`（85）与页面显示不一致，是干扰项。
- 绑定对账：`backendPrd.{prdId, storyCode, moduleId}`；首次读到的 `filePath` 是 `module_28667`，而 `moduleId` 是 `28668`，保存后 `filePath` 变 `module_28668`。以保存返回的 `file_path` 与 `moduleId` 对账。
- `dumpPrdStatus` 在只读视图返回 `prdId=null`；视图态数据读 fiber，编辑态才用 `dump/save`。

## 工具坑

- `eval` 返回必须是 JSON **对象**。返回裸数组/布尔会报 `eval 返回中未找到 JSON：false`；`prd_workbench.mjs` 的 `triggerAndPollScore` 在轮询处踩过（点击已生效，分数照常产出）：用 `prd_iterate.mjs rescore`。
- `eval` 表达式内的字面量正则 `/a\.b/i` 报 `Invalid regular expression flags`；全部改 `new RegExp('字符串')`。
- 进入「编辑」后「取消编辑」会弹确认，标题显示 `● 未保存`，评分按钮消失；依次点「取消编辑」→「放弃修改」（正文已由接口落库，放弃的只是编辑器草稿）→ reload，视图恢复才可评分。`prd_iterate.mjs save` 已内置。
- `created_by` 用 `localStorage["Operator-Name"]`；保存不回显新版本号，仍写当前槽。
- huashu-chrome `act` 可能报 `steps 不能为空`，改用 `eval`/顶层 fetch。
- 目标标签页在 `tabs list` 里按 `#/prototype/Story-XXXX` 找；用 `getHuashuClient` 连已登录 Chrome，不另开实例。

## 汇报

- 汇报前后分、`module_id`、回读精确一致、剩余 issues 与「为何不改」（缺事实）。已达目标且用户确认后停止追分。
