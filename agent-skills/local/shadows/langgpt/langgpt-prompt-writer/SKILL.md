---
name: langgpt-prompt-writer
description: "Create, rewrite, and review structured prompts using the LangGPT framework. Use when the user asks for LangGPT, structured prompt writing, prompt optimization, converting an ordinary prompt into Role/Profile/Skills/Rules/Workflow form, designing reusable AI roles/personas, or making prompts portable across Claude, Codex, ChatGPT, DeepSeek, Gemini, Kimi, Doubao, Qwen, and similar LLMs."
---

# LangGPT Prompt Writer

Create reusable structured prompts in the LangGPT style. Prefer a compact
prompt that another model can run directly over a long explanation of the
method.

## Output Contract

Return the finished prompt first. Add short notes only when they help the user
adapt or test it.

Default structure:

```markdown
# Role: <Role_Name>

## Profile
- Author: <author or team>
- Version: 1.0
- Language: <output language>
- Description: <role purpose and core capability>

## Goal
- <concrete outcome>

## Skills
### Skill-1: <capability>
1. <observable behavior>
2. <quality bar>

## Rules
1. <hard constraint>
2. <anti-hallucination / boundary rule>

## Workflow
1. <first step>
2. <middle step>
3. <delivery step>

## OutputFormat
- <format requirements>

## Initialization
As <Role>, follow <Rules>, use <Language>, then begin with <Workflow>.
```

## Workflow

1. Extract the user's target user, model, task, input variables, output format,
   quality bar, constraints, and failure modes.
2. Choose the smallest LangGPT structure that satisfies the task. Do not add
   sections that will not change model behavior.
3. Write concrete skills and rules. Avoid vague claims like "be professional";
   state observable behavior.
4. Add variables with `<Variable>` syntax only for values the end user should
   fill in.
5. Include `OutputFormat` for machine-readable, repeated, or high-stakes use.
6. If optimizing an existing prompt, preserve the user's intent and name the
   main changes after the prompt.

## Reference Routing

- Read `references/templates.md` when the user asks for a specific template
  style, weaker-model compatibility, tool-using prompts, or a prompt-generator
  meta-prompt.
- Read `references/examples.md` when the user asks for examples or the task
  resembles health planning, Chinese poetry, Xiaohongshu content, naming,
  decision support, coding assistants, or data analysis prompts.

## Guardrails

- Do not claim `/langgpt` works outside Claude Code. In Codex and other agents,
  invoke this as `$langgpt-prompt-writer` or by natural-language trigger.
- Do not copy unsafe role-play rules from examples when making production
  prompts. Replace jailbreak-like "stay in character" or "ignore failure"
  clauses with clear boundaries and validation steps.
- Keep prompts inspectable. Prefer markdown unless the user asks for JSON/YAML
  or a system-message format.
