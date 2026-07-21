# mac-bootstrap 模板规则

- 模板必须保持公开、可复用、可迁移。
- 先读 `CONTEXT.md`；专题操作见 `docs/`。
- 真实机器差异由父仓 overlay 提供，不在模板复制。
- 不直接修改运行态、缓存或生成文件。
- 修改后先运行最小相关验证；跨模块变更运行 `make check`。
- 公共发布前运行 `make privacy-audit`。
- `README.md` 是人类入口；本文件仅保留执行约束。

## Agent skills

### Issue tracker

GitHub Issues in `suainam/mac-bootstrap-template` are the source for specs and
tickets. See `docs/agents/issue-tracker.md`.

### Domain docs

This is a single-context repository; read `CONTEXT.md` and relevant `docs/`
guidance before implementation. See `docs/agents/domain.md`.

For Hammerspoon configuration or runtime work, read
`desktop/hammerspoon/README.md` before editing or reloading the app.
