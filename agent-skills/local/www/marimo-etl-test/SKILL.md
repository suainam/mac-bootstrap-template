---
name: marimo-etl-test
description: Writes and runs Docker-authoritative pytest regression tests for `www/marimo/merchandise` ETL, lib, notebook data flows, deploy workflows, and raw/agg/serve contracts. Use when changing ETL tasks, SQL, schemas, serve outputs, triggers, tests, Docker runtime behavior, or when the user requests Marimo pytest or container validation.
---

# Marimo ETL Test

## Authority

Treat the `marimo/` repository as the code boundary and Docker as the test authority.
Read `marimo/README.md`, `merchandise/AGENTS.md`, `merchandise/CONTEXT.md`, and
`merchandise/docs/dashboard-development-contract.md` before changing tests.

The production-proven dependency chain is authoritative, in this order:

1. `marimo_base/Dockerfile.marimo-base` and `marimo_base/requirements-marimo.txt`
2. `marimo_odps/Dockerfile`
3. `merchandise/Dockerfile` and `merchandise/requirements-seasonal.txt`

Do not treat a host `pyproject.toml`, `uv.lock`, or `.venv` as equivalent runtime proof.
Host uv may provide fast feedback only after the repository supplies an adapter derived from
the Docker authority files. Never share a host `.venv` with a container.

## Isolation

- If the current checkout is `main`, dirty, or shared with unrelated work, create a dedicated
  Marimo worktree before editing.
- Preserve unrelated dirty files. Commit and push the child repository before updating the
  parent `www` submodule pointer.
- Verify the container or bind mount points at the intended worktree and commit. Do not infer
  this from the container name alone.

## Run Pytest

For code-only changes, use the existing Merchandise image with the current worktree mounted
read-only:

```bash
mkdir -p <marimo-worktree>/merchandise/tests/_test_data_tmp
docker run --rm \
  --tmpfs /repo/merchandise/tests/_test_data_tmp:rw \
  -v <marimo-worktree>:/repo:ro \
  -w /repo/merchandise \
  --entrypoint python merchandise:dev \
  -m pytest tests/<target>.py --no-cov -q -p no:cacheprovider
```

Use `-p no:cacheprovider` for read-only mounts. If Dockerfiles or requirements changed, build
the repository images through the current Makefile/Compose flow before testing; a stale image
is not proof.

The ignored `_test_data_tmp` directory is only a mountpoint. Its tmpfs keeps fixture writes
inside the container and leaves the worktree read-only.

An existing development or preview container is acceptable only after checking its mounts,
image revision, and port/branch identity:

```bash
docker inspect <container> --format '{{json .Mounts}}'
docker inspect <container> --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
docker exec <container> python -m pytest tests/<target>.py --no-cov -q
```

Read `EXAMPLES.md` when assertion or container-selection examples are needed.

## Workflow

1. Add the smallest regression that fails for the intended reason.
2. Run the focused Docker test, implement the fix, then rerun it.
3. Expand coverage with blast radius:
   - ETL task or allowlist: `test_fetch_data.py` and workflow tests.
   - Producer/schema/serve change: topic ETL and data-consumer tests.
   - Deploy/release change: `test_gitea_deploy.py` plus relevant shell behavior.
   - Shared theme or cross-page contract: `test_theme.py` and
     `test_dashboard_contract.py`.
4. Run `make check` from the Marimo root when page registry, route, navigation, smoke, ETL,
   serve, README, theme debt, or baseline may change.
5. Run the full Docker suite for cross-module or shared-contract changes:

```bash
docker run --rm \
  --tmpfs /repo/merchandise/tests/_test_data_tmp:rw \
  -v <marimo-worktree>:/repo:ro \
  -w /repo/merchandise \
  --entrypoint python merchandise:dev \
  -m pytest tests/ --no-cov -q -p no:cacheprovider
```

`--no-cov` proves regression behavior only. It does not prove the repository's 80% complete
quality gate; report that distinction.

## Contract Rules

- Use a real `tmp_path` when patching `DATA_DIR`; do not replace filesystem behavior with a
  `MagicMock`.
- Producer tests must create every registered serve output and assert required columns,
  granularity, snapshot behavior, and empty-input behavior.
- Consumer tests must load producer-shaped fixtures and fail on removed or renamed required
  columns.
- Register serve `name`, `granularity`, `unique_key`, `required_columns`, `snapshot`, and
  `empty_behavior`, plus real producer/consumer pytest node IDs.
- Compute ratios from summed numerators and denominators; never average an existing ratio.
- Align invalid shared keys across every source before building filters.
- Test ETL task registration, one-task execution, `all` ordering, workflow allowlists, and
  producer argument wiring.

## Runtime Diagnosis

When pytest passes but the page is empty:

1. Identify the real preview/runtime container by branch slug, port, and revision.
2. Inspect `/workspace/data/raw`, `agg`, and `serve` inside that container.
3. Confirm the notebook reads the produced serve path.
4. Run the task inside that same container when live data validation is authorized.

Code deployment and data refresh are separate facts.

## Closeout

- Run Ruff/format checks for changed Python files and `git diff --check`.
- Remember that `git diff --check` ignores untracked files. Stage intended new files first and
  run `git diff --cached --check`, or add them with intent-to-add before checking.
- Run the repository secret scan after staging.
- Report the resolved worktree path, branch/SHA, exact bind argument, Docker image ID/revision,
  Python version, pytest scope, pass count, skipped coverage, and any hosted CI/runtime failure
  separately. A linked worktree's `.git` metadata may live outside the bind, so record Git SHA
  from the host rather than claiming an in-container Git check.

## Known Traps

- Do not install missing host packages ad hoc to imitate Docker.
- Do not use root `www` uv state as Marimo test authority.
- Do not `docker cp` tests until mounts are inspected; the wrong container can yield false
  results.
- Do not classify image-build success as deploy success. Network creation, container health,
  smoke, and revision checks are separate gates.
