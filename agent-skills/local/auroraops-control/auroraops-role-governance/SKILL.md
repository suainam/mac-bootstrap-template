---
name: auroraops-role-governance
description: Permanent role governance and anti-drift gate for AuroraOps. Enforces the 9-stage lifecycle contracts, universal service/timer task libraries, fail-closed assertions, and sub-repository domain invariants across all active roles.
---

Permanent architecture governance standard for authoring, maintaining, and certifying AuroraOps Ansible roles across all submodules (`auroraops-base`, `auroraops-services`, `auroraops-ops`).

## The 4 Immutable Role Invariants

1. **Strict 9-Stage Contract**: Every role must implement explicit, non-overlapping stage boundaries:
   - `tasks/main.yml` (orchestrator with mode dispatch)
   - `tasks/verify.yml` (pure read-only health & port assertions)
   - `tasks/rollback.yml` (controlled shutdown preserving persistent keys and certs)
2. **Infrastructure Purity & Idempotence**:
   - `check` phase must strictly achieve `changed=0` on converged systems.
   - Core infrastructure roles must never generate, mutate, or dump dynamic client subscription profiles into static web directories.
3. **Cross-Init Universal Library Adoption**:
   - Background daemons and periodic jobs must invoke `vps.common.tasks.managed_service` and `vps.common.tasks.managed_timer` instead of hardcoding raw systemd units or cron scripts.
4. **Zero Bare `rm` Policy**:
   - Task implementations and agent scripts are strictly prohibited from using raw `rm` for asset cleanup. Use `git rm`, explicit hash verification, or temporary directory scoping.

## Automated Verification Gates

Run the local governance gate before opening any PR or pinning releases:

```bash
make role-lint
```

The script statically audits all active roles declared in `catalog/roles.yml` against directory topology, missing lifecycle entrypoints, and prohibited command patterns.
