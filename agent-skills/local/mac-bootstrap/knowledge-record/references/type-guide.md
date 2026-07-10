# Type Selection Guide

## `adr` (Architecture Decision Record)

Use when the artifact is a **binding decision** that affects future
development or technology choice.

**Signals:**
- "我们决定用 X 替代 Y"
- "这个方案会影响后续所有模块"
- "这是一个架构或技术选型决策"
- "团队需要统一认知此方案"

**Examples:**
> 将 authentication 模块从 Python 迁移到 Rust，理由：性能需求 + 类型安全。
> 迁移期间保持两边兼容，评估时间 2 周。

> API 网关统一使用 Envoy，不再维护 Nginx 分支。

## `card` (Knowledge Card)

Use as the **default** when unsure.  Cards are reusable knowledge chunks.

**Signals:**
- "发现了一个可复用的模式"
- "这是一个踩坑记录"
- "这个配置技巧以后可能还会用到"
- "某功能的实现原理和注意事项"

**Examples:**
> macOS 上 Homebrew 安装的 Python 与 pyenv 管理的 Python 共存时，
> pip install 可能安装到错误的 site-packages。解决：先 `pyenv which pip` 确认。

> 当 Mac 连接 CorpLink VPN 时，Clash TUN 模式的 DNS 解析会走
> CorpLink 的 DNS，导致 .dev 域名无法解析。解决：TUN bypass 或 PAC 模式。

## `daily` (Daily Note Entry)

Use for **notable events, outcomes, or decisions** tied to a specific day.

**Signals:**
- "今天决定..."
- "验证了某个方案不可行"
- "与团队达成了一个重要共识"
- "发现了一个今天需要记录的关键信息"

**Examples:**
> 今天与后端团队确认：API 分页从 offset/limit 改为 cursor-based。
> 主要原因是 offset 在大量数据下性能退化严重。

> 今天验证了存算分离方案在 100 万 QPS 下不可行，
> 延迟比预期高 3 倍。后续改为存算一体 + 读写分离。

## Borderline Cases

| Case | Pick | Why |
|------|------|-----|
| 技术选型决策 | `adr` | 影响后续开发 |
| 踩坑记录但团队需遵循 | `adr` | 相当于规范 |
| 踩坑记录仅个人参考 | `card` | 知识卡片即可 |
| 会议重要结论 | `daily` | 按日期归纳 |
| 今日行动项 | `daily` | 明日计划的输入 |
