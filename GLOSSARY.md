# mac-bootstrap

The reusable, public-safe foundation and private overlay system for configuring and maintaining macOS development environments idempotently.

## Language

**Template**:
The public, reusable submodule repository containing machine-agnostic bootstrap scripts, configuration baselines, manifests, and tooling defaults.
_Avoid_: Submodule, upstream base, public repo

**Parent**:
The private repository hosting the template submodule and machine-specific configuration for a physical workstation.
_Avoid_: Host repo, wrapper repo, root repo

**Private Overlay**:
The machine-specific file tree under `private/` in the parent repository that injects real secrets, network identities, and workstation overrides into template defaults at runtime.
_Avoid_: Local overrides, secret patch, private config

**Profile**:
A named target configuration (such as `work` or `home`) defining environment-specific package sets, configurations, and service overlays without mutating shared base manifests.
_Avoid_: Environment, flavor, preset

**Single Source of Truth**:
An authoritative declarative manifest or file designating the exact desired state for a system component, from which runtime configurations and check suites derive.
_Avoid_: Master config, canonical source, ground truth

**Reconciliation**:
The idempotent process of aligning current system runtime state with authoritative declarations, halting on conflicting ownership rather than performing silent mutations.
_Avoid_: Sync, apply, update

**DevSpace**:
A local browser-accessible workspace management service whose definitions reside in the private overlay, accessed via HTTP rather than configured as an agent MCP server.
_Avoid_: Workspace manager, DevSpace MCP, web portal

**Zerobrew**:
A fast, secondary package manager managing standalone pre-built bottle binaries under a user-owned prefix alongside Homebrew as declared in package ownership manifests.
_Avoid_: Alternative brew, secondary package manager, zb

**Skill Supply Chain**:
The automated registry and distribution mechanism that sources agent skills and materializes symlinks to target agent discovery paths.
_Avoid_: Skill installer, prompt distributor, skill sync

**Doctor**:
A non-destructive diagnostic validation suite verifying workstation health, symlinks, permissions, and tool runtimes against declared manifests.
_Avoid_: Healthcheck, lint, audit

**Child-First Release**:
A release and versioning invariant requiring commits, verification, and tags to succeed in the public template submodule before updating the parent repository pointer.
_Avoid_: Bottom-up commit, submodule-first publish
