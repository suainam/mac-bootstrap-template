---
name: daily-claude-battle-boost
description: Runs a daily Claude battle-power improvement drill focused on diligence, output, curiosity, control, and efficiency. Use when the user asks for daily Claude practice, battle radar improvement, prompt coaching, conversation SOPs, or a repeatable routine to raise Claude usage quality.
---

# Daily Claude Battle Boost

Builds one focused daily Claude session that improves five dimensions:

- `勤奋度` -> show up daily with one meaningful round
- `产出力` -> ask for a larger deliverable, not a short answer
- `探索欲` -> provide richer context and request comparison or deeper analysis
- `驾驭力` -> reuse one thread, fixed background, fixed output format
- `效率感` -> reduce wandering and force direct delivery

## Quick start

When invoked, run one daily drill with this output:

1. Today's target dimension
2. One concrete work task to practice on
3. One ready-to-send Claude prompt
4. One follow-up prompt to deepen the round
5. One reflection prompt to capture lessons

## Workflow

### 1. Pick today's focus

Choose exactly one primary dimension:

- Monday -> `驾驭力`
- Tuesday -> `效率感`
- Wednesday -> `产出力`
- Thursday -> `探索欲`
- Friday -> `综合实战`
- Weekend -> `复盘+补短板`

If the user names a weak dimension, override the default and prioritize that.

### 2. Turn real work into training

Use the user's actual task when possible. Prefer:

- code debugging
- report writing
- scheme design
- data analysis
- document polishing

Avoid fake practice unless no real task exists.

### 3. Generate the daily prompt

The main prompt must include:

- clear goal
- background/context
- constraints
- required output format
- instruction to avoid stopping at analysis

Default output format:

```text
- 结论
- 依据
- 直接可用结果
- 验证方法
- 风险
```

### 4. Force a second round

Always add one follow-up prompt that does one of:

- critique and strengthen the first answer
- compress a long answer into an executable version
- turn output into a reusable template
- ask for risks, edge cases, or validation

### 5. Close with reflection

End with a short reflection prompt:

- what made this round strong
- what wasted tokens
- how to ask better next time

## Rules

- Prefer one deep round over many shallow prompts.
- Reuse the same Claude thread for related work.
- Ask for deliverables, not brainstorming, by default.
- If the first prompt is vague, rewrite it before using it.
- If the user already has metrics, explain which dimension the drill targets.

## See also

- [EXAMPLES.md](EXAMPLES.md) for copy-paste daily drills
