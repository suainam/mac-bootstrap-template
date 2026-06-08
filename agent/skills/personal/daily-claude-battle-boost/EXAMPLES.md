# Daily Drill Examples

## Example 1: Drive `驾驭力`

Use when you want Claude to reuse context instead of re-explaining everything.

```text
你现在是我的长期项目协作助手。

目标：帮我完成这次任务，并尽量复用前文上下文。
背景：下面是已经确认的信息，后续默认沿用，不要重复向我要。
<粘贴项目背景>

本轮任务：<粘贴今天真实任务>
约束：<时间/技术栈/不能动的部分>

输出格式固定为：
- 结论
- 依据
- 直接可用结果
- 验证方法
- 风险

要求：
1. 先基于已有上下文继续
2. 不要停在分析阶段
3. 信息不够时，只补问最关键的1个问题
```

Follow-up:

```text
基于你刚才的结果，不要重复背景。
请把答案再压缩成“可直接执行版本”，去掉不必要展开。
```

Reflection:

```text
复盘这一轮：
1. 哪些部分真正利用了上下文
2. 哪些内容仍然重复
3. 下次我开场应该怎样说得更好
```

## Example 2: Drive `效率感`

Use when you want more output per cost.

```text
帮我直接产出最终版本，不要先头脑风暴。

目标：<目标>
背景：<背景>
约束：优先给最可能正确、最省成本的方案，不要同时展开太多方向。

输出格式：
- 最终建议
- 可直接使用内容
- 最小执行步骤
- 验证方式
```

Follow-up:

```text
请批判你刚才的答案，指出3个最薄弱点，然后给我更强的终版。
```

## Example 3: Drive `产出力`

Use when you want Claude to create a larger, higher-value deliverable.

```text
我不要简答，我要完整交付物。

目标：<例如：写完一份方案/改完一组代码/产出一版汇报>
背景：<背景>
约束：<约束>

请直接输出成品，至少包含：
- 结论
- 完整正文或完整方案
- 具体执行步骤
- 验证方法
```

## Example 4: Weekly review

```text
请复盘我这周和 Claude 的使用方式。

从五个维度分析：
- 勤奋度
- 产出力
- 探索欲
- 驾驭力
- 效率感

输出：
1. 本周最强项
2. 本周最短板
3. 下周最值得刻意练习的一项
4. 给我3条可以直接复制的下周提示词
```
