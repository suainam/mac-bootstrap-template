---
name: role-lifecycle-assurance
description: Run the nine semantic lifecycle stages and four checkpoints for AuroraOps Ansible roles on non-pristine hosts. Use when deploying, releasing, auditing rollback, or proving recovery of a role through the parent Make adapter.
---

Standardized lifecycle assurance methodology for operating and releasing Ansible roles on non-pristine production servers. The parent repository owns inventory, Vault, target selection, lifecycle commands, and evidence; the child collection owns role tasks.

## Core Rules

1. **Never Assume Pristine State**: Target machines carry existing configurations and live workloads. Never blind-overwrite without recording pre-existing state.
2. **Checkpoint Precedes Mutation**: Capture a read-only `before` baseline and persist its artifact before writing any file or adjusting parameters. Do not silently replace it on retry.
3. **Evidence Over Chat**: Every stage gate must yield programmatic pass evidence (`ok > 0, failed=0`) from an adapter-declared command.
4. **Make Owns Target Selection**: Run `make switch_remote.<host>` and `make env_show`; do not override `ANSIBLE_PLAYBOOK`, `INVENTORY`, or `ANSIBLE_LIMIT` on lifecycle commands.
5. **Idempotence is Strict**: Repeat the canonical dry-run check and require `changed=0, failed=0`.
6. **Reversibility is Mandatory**: A role cannot be certified without passing real rollback and rollback-verification.
7. **Evidence Is Sanitized**: Never write tokens, passwords, private keys, Authorization headers, provider URLs, or response bodies to artifacts.

---

## Semantic evidence triage

For semantic evidence classification, use the `typesafe-ai` skill; do not
reimplement TypeSafe provider/API integration in this lifecycle skill. This
skill remains authoritative for stage order, checkpoints, permissions,
mutation, thresholds, and side effects. Pass only normalized, redacted
evidence to TypeSafe. Treat provider failure or uncertain judgment as
fail-closed human review; TypeSafe never authorizes mutation.

## 9-Stage Execution Workflow

Follow these steps in strict sequence for each role undergoing certification:

### Stage 1: Preflight (Read-Only)
- **Goal**: Verify host suitability, module availability, and baseline syntax without changing anything.
- **Command**:
  ```bash
  rtk make preflight-<domain>.<role>
  ```
- **Completion Criterion**: Parameter support probed, no unreachable or syntax failures, `changed=0`.

### Stage 2: Baseline Checkpoint
- **Goal**: Lock current machine state before any modification occurs.
- **Target Fact**: the role-declared baseline fact or a parent-owned lifecycle artifact.
- **Completion Criterion**: The artifact records `auroraops_managed: true` or an equivalent ownership marker, the observed pre-deploy state, protected assets, and the observation command. Secret values are excluded.

### Stage 3: Check (Dry-Run Preview)
- **Goal**: Dry-run full deployment to inspect planned diffs.
- **Command**:
  ```bash
  rtk make check-<domain>.<role>
  ```
- **Completion Criterion**: Execution succeeds under `--check --diff` with zero unhandled exceptions.

### Stage 4: Deploy (Mutation)
- **Goal**: Apply planned state, persist managed configuration files, reload runtime services or kernel tables.
- **Command**:
  ```bash
  rtk make deploy-<domain>.<role>
  ```
- **Completion Criterion**: Target files created/updated, reload commands succeed (`failed=0`).

### Stage 5: Verify (Active Assertions)
- **Goal**: Run automated assertions against the live machine.
- **Command**:
  ```bash
  rtk make verify-<domain>.<role>
  ```
- **Completion Criterion**: 100% of defined `assert` tasks pass (`failed=0, ok > 0`).

### Stage 6: Idempotence Gate
- **Goal**: Repeat the canonical dry-run check on the finalized host to detect unwanted drift or non-idempotent tasks.
- **Command**:
  ```bash
  rtk make check-<domain>.<role>
  ```
- **Completion Criterion**: Execution finishes with strictly `changed=0, failed=0`.

### Stage 7: Rollback (Fault Simulation & Reversal)
- **Goal**: Read `/etc/ansible/facts.d/<role>.fact` and restore host to exact pre-deployment state.
- **Command**:
  ```bash
  rtk make rollback-<domain>.<role>
  ```
- **Completion Criterion**: Original files restored, newly generated configs deleted, runtime values set back.

### Stage 8: Rollback Verify (Old-State Audit)
- **Goal**: Indepedently assert that the machine has reverted to its pre-deployment baseline.
- **Command**:
  ```bash
  rtk make rollback_verify-<domain>.<role>
  ```
- **Completion Criterion**: Assertions verify that old values are active and AuroraOps managed artifacts are cleaned up.

### Stage 9: Redeploy & Recovery Verify
- **Goal**: Return node to certified production state.
- **Command**:
  ```bash
  rtk make redeploy-<domain>.<role>
  rtk make recovery_verify-<domain>.<role>
  ```
- **Completion Criterion**: Production verify returns all green (`failed=0, changed=0`).

---

## Parent adapter protocol

For a role ID such as `vps.services.mihomo_native`, the parent adapter exposes
`<stage>-services.mihomo_native`. Run lifecycle commands serially because a
concurrent `worktree-init` can replace the collection overlay. Before each
stage, select the host and inspect the generated command:

```bash
rtk make switch_remote.<host>
rtk make env_show
rtk make -n <stage>-services.<role>
rtk make <stage>-services.<role>
```

The `--limit` shown by `make -n` and by the real Ansible command must match the
selected host. A command that succeeds against the wrong host is a failed
stage. Raw SSH or ad-hoc Ansible is useful for diagnosis, but it is not stage
evidence. `recovery_verify` must have its own adapter surface even when it
reuses ordinary verify assertions.

## Runtime acceptance beyond Ansible

Port checks and `/v1/models` prove process reachability, not upstream success.
For proxy-backed AI services, add redacted real requests:

- probe a stable external endpoint through the exact loopback proxy;
- call one supported Gemini model and one supported GPT text model;
- record only model ID, HTTP status, and response byte count;
- interpret a provider or website `403` separately from a local connection
  failure: a response from the upstream proves the request crossed the proxy.

Keep adjacent services separate. `cf-probe` may consume Mihomo through its
loopback proxy; `mosdns` can remain on a loopback DNS port for ad filtering;
neither fact proves that system DNS or transparent routing was changed.

## Edge proxy lessons from the Rasp migration

- A target proxy cannot bootstrap its own first profile. Download and validate
  the complete profile on the controller, then atomically install it before
  starting the proxy.
- Prefer a fixed native systemd binary, pinned checksum, loopback binding, and
  an explicit provider cache on a low-memory ARM host. Preserve the last-known-
  good profile on refresh and rollback.
- Do not treat an inactive legacy service as proof that its ports are free.
  Check systemd, listeners, transparent firewall state, and one real request.
- `service_facts` can retain deleted systemd units as `not-found` entries.
  Rollback verification must assert the manager's `LoadState=not-found` (or an
  equivalent explicit absent state), not only key absence.
- On macOS, Mitogen can hit Objective-C fork safety failures. Keep the project
  fork setting enabled and fall back to the repository's linear strategy only
  for diagnosis; do not replace Make lifecycle evidence with an ad-hoc probe.
- Keep DNS cleanup separate from proxy cutover. Retaining mosdns on loopback
  does not mean it owns system DNS or port 53.

## Environment Compatibility & Lessons Learned (实战经验与踩坑教训)

在多架构与非纯净主机（如 Debian 裸机/KVM vs Alpine Podman NAT 容器）推行 9 阶段保证时，必须遵循以下经验法则：

### 1. 容器只读挂载与内核命名空间陷阱 (`/proc/sys`)
- **现象**：在无特权 Podman/LXC NAT 容器中，`test -w /proc/sys` 或 `test -w /proc/sys/net/ipv4/ip_forward` 仍可能返回 `0`（权限位表面显示 root 可写），但实际写入会遭遇 `Read-only file system` 报错导致部署中断。
- **正解**：通过 `/proc/mounts` 精准检测挂载属性：
  ```yaml
  - name: Probe whether /proc/sys is read-only mount on target
    check_mode: false
    ansible.builtin.command: "grep -E '\\s/proc/sys(\\s|$).*\\bro\\b' /proc/mounts"
    register: sysctl_proc_sys_ro_check
    changed_when: false
    failed_when: false

  - name: Set /proc/sys writability fact
    ansible.builtin.set_fact:
      sysctl_proc_sys_writable: "{{ sysctl_proc_sys_ro_check.rc != 0 }}"
  ```
- **原则**：只读环境下只固化受管配置文件（`/etc/sysctl.d/`）与 Baseline Fact，自动跳过运行期内核写操作（`sysctl -w`）与动态断言。

### 2. Mitogen 协议流中断与高延迟终端丢包排查
- **现象**：执行高输出命令（如列举大量内核模块、复杂 facts）或高并发探测时，Mitogen 偶尔报 `the respondent Context has disconnected` 或 SSH 报 `Connection timed out during banner exchange`。
- **根因**：弱网 NAT 节点单端口端口映射可能发生短暂重传积压，或 Mitogen 与 Python 3.14 内部结构冲突。
- **应对策略**：
  - 临时回退线性策略排查：`ANSIBLE_STRATEGY=linear make <target>`。
  - 控制端必须引入环境变量并锁定 macOS fork 安全开关：`OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`。

### 3. 多环境双向回归门禁
- 任何 Role 一旦修改适配特殊环境（如只读 NAT），必须对主环境（如标准 KVM/裸机生产节点）执行反向回归：
  ```bash
  rtk make switch_remote.<primary-production-host>
  rtk make env_show
  rtk make verify-<domain>.<role>
  ```
- 确保没有因支持低权限环境而意外阉割了高权限标准主机的严格校验断言。

### 4. 依赖联动的 Focused 后置刷新与动态发现防漂移
- **现象**：后端服务（如 Sub-Store 聚合、节点生成）变更后需要 Nginx 发布或反代。若在编排中重新调用完整 Nginx Role，会触发漫长的软件包检查并面临全量站点基线冲突（`baseline stale`），甚至引发入口抖动。
- **正解**：
  1. **Focused Post-Hook**：父仓在完成底层或应用部署（`deploy-services.docker_apps.sub_store`）后，仅通过后置钩子调用 focused target（`deploy-services.nginx.nginx_site_config`），并开启增量对齐：
     ```makefile
     $(MAKE) ANSIBLE_EXTRA_ARGS='-e nginx_refresh_from_sub_store=true -e nginx_site_baseline_allow_additive_reconcile=true' deploy-services.nginx.nginx_site_config
     ```
  2. **Dynamic Discovery 替代静态硬编码**：边缘动态节点（如 NAT）由 Inventory 组及子组（`nat_nodes` / `nat_hk`）定义，Sub-Store resolver 直接根据主机名、端口与 token 动态构造订阅 URL。禁止在 Vault 或 catalog 中硬编码易漂移的动态节点订阅。
  3. **Tracer Bullet First**：优先以“源端订阅 HTTP 200 YAML 探测 -> Sub-Store 单点聚合 -> Nginx 路径映射”打通端到端最小可用闭环（MVP），通过真实的响应状态/字节数取证，避免在全链路稳定前堆砌脆弱的源码字符串匹配测试。

---


### 5. 多驱动存储（PG/S3/文件）切换与权威源隔离
- **现象**：容器由 PostgreSQL 驱动切换为本地文件或 S3 模式后，应用启动仍从数据库拉取旧配置，导致宿主机修改被抹除；或在 S3 模式下仍挂载独立 config/auths，导致双向同步目录分离。
- **正解**：
  1. **条件性剥离环境变量**：切换非数据库存储时，环境变量必须完全剔除 `PGSTORE_DSN`，避免 Go 二进制判定数据库驱动优先于本地文件。
  2. **挂载点对齐**：启用 S3/R2 双向同步时，将宿主机目录定向到容器的 `objectstore` 路径（如 `/opt/dockers/<app>/objectstore:/app/objectstore`），由内部驱动负责监听与自动拉取。
  3. **受控强制覆写**：为配置下发设立显式 `force_overwrite` 开关；日常幂等部署不覆盖在线 WebUI 修改，受控切换时才开启全量覆写。
## Disclosed Reference & Automation

- **Lifecycle Contract & Matrix**: Detailed definitions and stage rules in [references/lifecycle_contract.md](references/lifecycle_contract.md).
- **Task Patterns & File Templates**: Task file structures (`apply.yml`, `verify.yml`, `rollback.yml`) in [examples/role_task_patterns.md](examples/role_task_patterns.md).
- **Automated Test Runner**: Execute the end-to-end 9-stage suite with one command via [scripts/execute_role_lifecycle.py](scripts/execute_role_lifecycle.py):
  ```bash
.venv/bin/python .agents/skills/role-lifecycle-assurance/scripts/execute_role_lifecycle.py \
    --role <domain>.<role> --host <host> \
    --before-artifact artifacts/<profile>-<host>-<target>-lifecycle.json \
    --output artifacts/<profile>-<host>-<target>-runner.json
  ```
  The runner refuses to start without a verified `before` checkpoint and uses
  the parent Make adapter for host selection and every lifecycle stage.
