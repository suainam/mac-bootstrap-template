# Role Lifecycle Assurance Reference (契约与状态流转规范)

## 1. 契约原则 (Core Principles)
- **非纯净机器假设**：受控机器已存在既有配置与运行服务，严禁盲目覆盖。
- **只读基线先行**：变更前必须完成 `before` Checkpoint 固化，作为后续回滚与审计的事实依据。
- **可逆性保证**：任何受管资源（文件、内核参数、Systemd 服务、包）必须具备确定性回滚能力。
- **可复现审计**：全生命周期的每一个阶段产出必须留下机器可读的状态事实（facts / json）。

---

## 2. 状态阶段流转矩阵 (9-Stage Flow)

`before` is a required checkpoint before mutation; it is not an extra semantic
stage. The four checkpoints are `before`, `after_deploy_verify`,
`after_rollback_verify`, and `after_redeploy_recovery_verify`.

| 阶段 # | 阶段名称 | 核心操作 (Ansible / Makefile) | 判定准则 (Completion Criterion) | 状态变更要求 |
|---|---|---|---|---|
| **Stage 1** | **Preflight** | `tasks_from: preflight.yml` | 模块存在性探测完成、受管参数/资源有效性通过校验 | `changed=0, failed=0` (只读) |
| **Stage 2** | **Check (Dry-run)** | `make check-<domain>.<role>` (`--check --diff`) | 预览变更内容，无未捕获语法/依赖错误 | 演练成功，不落盘 |
| **Stage 3** | **Deploy** | `make deploy-<domain>.<role>` | 资源正式写入，服务/配置重载 | `changed >= 0, failed=0` |
| **Stage 4** | **Verify** | `make verify-<domain>.<role>` | 全量断言运行时状态、文件权限、内核键值与预期一致 | `ok > 0, changed=0, failed=0` |
| **Stage 5** | **Idempotence** | 二次执行 `make check-<domain>.<role>` | 再次 dry-run 不产生额外副作用 | 严格要求 `changed=0, failed=0` |
| **Stage 6** | **Rollback** | `make rollback-<domain>.<role>` | 从 Checkpoint 提取旧内容恢复，清理新增附带文件 | `changed >= 1, failed=0` |
| **Stage 7** | **Rollback Verify** | `make rollback_verify-<domain>.<role>` | 独立断言环境已 100% 恢复至修改前旧值 | `ok > 0, changed=0, failed=0` |
| **Stage 8** | **Redeploy** | `make redeploy-<domain>.<role>` | 回滚后重新应用期望状态 | `changed >= 0, failed=0` |
| **Stage 9** | **Recovery Verify** | `make recovery_verify-<domain>.<role>` | 独立断言恢复至预期终态生产配置 | `ok > 0, changed=0, failed=0` |

---

## 3. 三套调度流程 (Execution Workflows)

1. **日常收敛流程 (`converge`)**：
   - 顺序：`preflight` → `before` → `check` → `deploy` → `verify` → `idempotence`
   - 适用场景：已全量验证过的成熟 Role 的版本升级或配置刷新。
2. **回滚演练流程 (`rollback-test`)**：
   - 顺序：`verify` → `rollback` → `rollback_verify` → `redeploy` → `recovery_verify`
   - 适用场景：灾备演练、验证 Role 卸载与还原安全性。
3. **完整保证流程 (`full-assurance`)**：
   - 顺序：完整执行 1 ~ 9 阶段。
   - 适用场景：新 Role 首次上线、接管新非纯净生产机器、架构重大重构。

## 4. Parent adapter and evidence rules

- Select a host with `make switch_remote.<host>` and confirm `make env_show`.
  Do not override Make authority variables on a lifecycle command.
- Run stages serially. A shared collection overlay or active selector can drift
  when two lifecycle commands run together.
- Only adapter-declared commands count as lifecycle evidence. A missing
  `before` artifact or a successful command against the wrong host blocks the
  run.
- `rollback_verify` must check an explicit absent state. For systemd, use
  `LoadState=not-found`; `service_facts` key absence alone is not sufficient.

## 5. Runtime evidence for proxy-backed services

Record loopback listener ownership, service/timer state, provider/cache state,
and an authenticated local endpoint. Add one real upstream request for each
critical provider and store only model ID, HTTP status, and response byte count.
An upstream `403` is evidence that the request reached the upstream; it is not
the same as a local proxy connection failure. Keep DNS, transparent routing,
and adjacent probes as separate ownership decisions.
