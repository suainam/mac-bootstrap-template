---
name: auroraops-service-role-refactor
description: End-to-end discipline for refactoring and extracting unified Ansible roles in AuroraOps (such as singbox and cliproxyapi). Orchestrates specification, ticket slicing, TypeSafe semantic architecture decisions, worktree isolation, dual-rail migration, and nine-stage lifecycle assurance.
---

Standardized engineering methodology for decoupling, extracting, and consolidating dual-mode (Docker container + Native OpenRC/systemd) service roles in AuroraOps. Mirrors the battle-tested refactoring playbook proven across `cliproxyapi` and `singbox`.

## Core Invariants

1. **Clean Worktree Isolation**: Never refactor in the primary branch or across dirty directories. Work within `.worktrees/<feature-branch>` and execute `make worktree-ready` before touching files.
2. **Single Source of Truth (DRY)**: Centralize all shared routing, protocol templates, keypair/short-ID generation, and certificate handling into shared tasks/templates. Never maintain duplicate parallel templates across runner modes.
3. **Decoupled Platform Runners**: Branch execution into dedicated `docker.yml` and `native.yml` tasks, with isolated `verify_docker.yml` and `verify_native.yml`.
4. **Explicit Profile Contract**: The role must declare its deployment mode explicitly via `singbox_deploy_mode: 'docker' | 'native'` with fail-closed auto-detection.
5. **Fail-Closed TypeSafe Assistance**: Use `typesafe-ai` (`typesafe_question`) for architectural shape selection, DRY boundary decisions, and risk scoring. Never allow probabilistic models to execute mutations or bypass lifecycle gates.
6. **Strict Nine-Stage Assurance**: After refactoring, execute the full 9-stage lifecycle via `role-lifecycle-assurance` on target hosts before declaring done.
7. **Clean Cutover & Zero Residue**: Once the unified role is established, completely remove deprecated tasks and templates from legacy host roles (e.g. `docker_apps`).

---

## The 4-Phase Delivery Flow

```text
Phase 1: Specification (to-spec)
  -> TypeSafe Architectural Decisions (typesafe_question)
  -> Phase 2: Vertical Ticket Slicing (to-tickets)
  -> Phase 3: Worktree Implementation & Local Verification (implement)
  -> Phase 4: Nine-Stage Live Lifecycle Assurance (role-lifecycle-assurance) & Clean Cutover
```

### Phase 1 — Specification & Architecture Design (`/skill:to-spec`)
1. Identify coupling boundaries: find where native logic is embedded inside container roles (e.g., singbox in `docker_apps`).
2. Consult TypeSafe via `typesafe_question`:
   - Evaluate directory pattern against reference models (`cliproxyapi_mirror`).
   - Determine common config extraction points.
   - Establish fail-closed variable contracts.
3. Consult `codebase-memory-mcp` knowledge graph for caller/callee analysis and template dependencies.
4. Output structured specification following the `to-spec` standard format to `.scratch/<slug>/specs/`.

### Phase 2 — Vertical Slicing (`/skill:to-tickets`)
1. Slicing discipline: tracer-bullet tickets each cutting through schema, template, playbook, and test.
2. Structure tickets in dependency order:
   - Ticket 01: Core shared config extraction & template unification.
   - Ticket 02: Platform runners (`docker` & `native`) and verification tasks.
   - Ticket 03: Profile contract, parent catalog registration, and playbook generation.
   - Ticket 04: Legacy task deprecation, cleanup, and 9-stage lifecycle certification.
3. Save to `.scratch/<slug>/issues/<NN>-<title>.md`.

### Phase 3 — Worktree Implementation (`/skill:implement`)
1. **Worktree Setup**:
   ```bash
   rtk git worktree add .worktrees/<slug> -b feat/<slug>
   cd .worktrees/<slug> && rtk make worktree-ready
   ```
2. **Execute Slices**:
   - Create unified role directory under `collections/ansible_collections/vps/services/roles/<role>/`.
   - Implement `tasks/resolve.yml`, `tasks/common_prep.yml`, `tasks/configure_common.yml`.
   - Implement `tasks/docker.yml` and `tasks/native.yml`.
   - Add unit contract tests in `tests/unit/test_<role>_unified_contract.py`.
3. **Run Test Gates**:
   ```bash
   rtk pytest tests/unit/test_<role>*
   ```

### Phase 4 — Nine-Stage Lifecycle Assurance & Residue Cleanup
1. Use `role-lifecycle-assurance` script against live non-pristine targets:
   - Container target (`qqg1299` or `cc15`):
     ```bash
     python3 artifacts/loop/execute_role_lifecycle.py --role vps.services.<role> --host qqg1299 ...
     ```
   - Native target (`nat-hk216` or `rasp`):
     ```bash
     python3 artifacts/loop/execute_role_lifecycle.py --role vps.services.<role> --host nat-hk216 ...
     ```
2. **Zero Residue Verification**:
   - Check and delete legacy task files from `docker_apps/tasks/<role>*.yml`.
   - Remove legacy template directory `docker_apps/templates/<role>/`.
   - Audit references with `grep` to ensure zero stale callsites.
