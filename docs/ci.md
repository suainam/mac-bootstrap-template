# Public CI

The public template has two validation boundaries:

- `make ci` is deterministic and portable. It is the contract used by GitHub
  Actions for pull requests and pushes to `main`.
- `make check`, `make doctor`, and `make doctor-agent` are local macOS checks.
  They inspect installed applications, GUI state, agent configuration, and
  runtime directories that do not exist on a clean hosted runner.

## Reproduce CI locally

From a clean checkout, install the locked development dependencies and run:

```bash
uv sync --locked --group dev
make ci
```

The CI contract runs, in order:

1. Shell, Python, and Lua syntax checks.
2. The portable pytest suite (`machine`-marked tests are reserved for local checks,
   including macOS shell, SSH, desktop, and archived runtime checks).
3. The public privacy audit.
4. The skill registry check.
5. The neat-freak changed-path documentation gate.

To compare a local branch with a known base revision:

```bash
NEAT_FREAK_BASE_REF=origin/main make neat-freak-ci
```

When no base revision is supplied, `make neat-freak-ci` checks only working-tree
and staged changes; an unchanged clean checkout passes this gate. GitHub Actions
always supplies the event base revision. An empty change set is a valid pass.

Operational changes must have a corresponding current public documentation change;
archived documentation does not satisfy this gate. The gate includes nested build
and dependency manifests such as Makefiles, lockfiles, and requirements files.
Documentation, credentials, private parent configuration, external skill
fetches, and machine-specific runtime state are not part of the CI contract.

## GitHub Actions boundary

The workflow uses read-only repository permissions and provisions only the
tools required by `make ci`. It does not run external skill intake or skill
distribution, and it does not print or upload local machine state. Branch
protection may make the check required after the workflow has proved stable;
that repository policy is separate from the workflow implementation.
