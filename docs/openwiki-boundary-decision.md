# 为什么不在模板仓长期使用 OpenWiki

## 结论

`mac-bootstrap/template` 不再接入 OpenWiki，也不再向其他仓库分发 OpenWiki workflow。

原因不是 OpenWiki 生成能力差，而是它和当前仓库的文档治理模型冲突：本仓已经有稳定的权威文档分层，OpenWiki 更容易生成第二套入口和第二套解释，而不是补上缺失的知识层。

## 当前仓库的权威分层

- `README.md`：首次接手入口、初始化与最短操作路径。
- `CONTEXT.md`：架构边界、权威来源与判断框架。
- `CLAUDE.md` / `AGENTS.md`：执行约束、修改边界、验证要求。
- `docs/`：runbook、机制说明、经验与专题文档。

这些文件已经覆盖了“人类入口 + agent 规则 + 架构边界 + 操作细节”四层职责。维护方式是人工编辑、明确同源、长期收敛。

## OpenWiki 带来的实际问题

### 1. 侵入规则层

OpenWiki `init` 会向 `CLAUDE.md` 注入“先读 /openwiki”的导航段，且在一次实际运行里把 `AGENTS.md` 从软链替换成了独立文件。

这会破坏仓库的规则同源约束：`AGENTS.md` 应与 `CLAUDE.md` 同源，而不是由工具生成另一份提示文本。

### 2. 生成第二套解释层

OpenWiki 会生成 `quickstart.md`、`overview.md`、`operations.md`、`workflow/*.md` 这类页面。

但模板仓已经有：

- `README.md`
- `CONTEXT.md`
- `docs/README.md`
- `agent/README.md`
- 各专题 `docs/*.md`

结果不是“补空白”，而是把已有内容再表达一遍，形成平行入口。短期看只是重复，长期就会变成漂移。

### 3. 父仓 / 子仓边界容易模糊

这套工程里存在父仓、模板子仓、以及其他业务仓库。OpenWiki workflow 一旦从模板向多个仓库分发，后续很容易出现：

- 父仓和子仓同时维护 OpenWiki
- 同一块代码或规则被两边重复解释
- agent 不清楚该信根文档还是 `openwiki/`

这类边界问题比“缺一个 repo map”更贵。

## 仓库适配判断

OpenWiki 更适合下面这类仓库：

- 现有文档弱，缺少 repo 导航
- `CLAUDE.md` / `AGENTS.md` 不是强约束核心
- 仓库结构稳定，且没有复杂的父子仓边界

模板仓不满足这些条件，因此不采用。

## 后续约定

1. 不在模板仓重新执行 `openwiki --init`。
2. 不在模板仓维护 `openwiki/` 目录。
3. 不从模板向其他仓库分发 `openwiki-update.yml`。
4. 若未来评估类似工具，必须先回答：
   - 它是否会修改 `CLAUDE.md` / `AGENTS.md`？
   - 它是否会生成与 `README.md` / `CONTEXT.md` / `docs/` 重叠的入口？
   - 它是否会模糊父仓 / 子仓边界？

只要其中任一答案为“会”，默认拒绝接入。
