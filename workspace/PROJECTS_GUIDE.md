# Workspace Guide

`~/work` is the umbrella workspace.

Active software projects live under `~/work/projects/<project-name>`, and each
project should be its own git repository.

## Directory roles

- `~/work/config`
  - machine/bootstrap/config repos
- `~/work/projects`
  - active code projects, one subdirectory = one repo
- `~/work/libs`
  - shared reusable libraries, templates, prompts, snippets, starter kits
- `~/work/knowledge`
  - long-lived notes, Obsidian vaults, research knowledge bases
- `~/work/archive`
  - retired projects, old exports, zip bundles, historical snapshots
- `~/work/data`
  - shared datasets, important downloaded materials, large raw files
- `~/work/notebooks`
  - cross-project or scratch notebooks
- `~/work/scripts`
  - shared helper scripts
- `~/work/tmp`
  - temporary files, browser/software downloads, disposable outputs

## Classification rule

When deciding where something belongs, prefer intent over file type.

- `projects/`
  - still being developed, runnable, or actively maintained
- `libs/`
  - meant to be reused by multiple projects
- `knowledge/`
  - note systems, vaults, curated references
- `archive/`
  - no longer active, kept only for lookup, rollback, or record
- `scripts/`
  - standalone automation used across projects
- `tmp/`
  - disposable files; safe to delete later

Practical examples:

- active repo -> `~/work/projects/customer-dashboard`
- shared shell helper -> `~/work/scripts/sync-downloads.sh`
- shared starter repo/template -> `~/work/libs/project-template`
- Obsidian vault -> `~/work/knowledge/obsidian/<vault-name>`
- old zip export -> `~/work/archive/files/<name>.zip`
- retired repo -> `~/work/archive/projects/<project-name>`

## Recommended workflow

1. Preferred: run from `~/work` directly:

```bash
cd $HOME/work
make new-project
```

Non-interactive form:

```bash
cd $HOME/work
make new-project NAME=my-project DESC="Short description"
```

2. Equivalent manual entrypoint:

```bash
cd $HOME/work/config/mac-bootstrap
```

3. Run the scaffold:

```bash
./scripts/new-project.sh
```

4. Enter the new project:

```bash
cd $HOME/work/projects/<project-name>
direnv allow
```

`direnv allow` is also run automatically at project creation time when
`direnv` is installed.

5. Start working:

```bash
git status
docker compose up --build
```

Analysis program example:

```bash
cd $HOME/work
make new-analysis-subproject \
  PROJECT_ROOT=$HOME/work/projects/analysis-program \
  CONTAINER=sales \
  NAME=demand_forecast
```

After generation:

```bash
cd $HOME/work/projects/analysis-program/sales/demand_forecast
make export
```

Then edit `odps_export_config.py` with project-specific SQL, output file names,
and optional rename mappings.

## What the scaffold creates

For each new project under `~/work/projects/<project-name>`:

- separate git repo initialized on `main`
- `.envrc` for project-local environment activation
- `.env` and `.env.example`
- `.gitignore` with large-data and cache exclusions
- `src/`, `data/`, `notebooks/`
- `pyproject.toml`, `Dockerfile`, `compose.yaml`
- compose mounts `./data/` as project‑local writable, `~/work/data` as global read‑only

## Repo boundaries

Use one git repo per active project:

- good: `~/work/projects/customer-segmentation`
- good: `~/work/projects/internal-dashboard`
- good: move retired repos to `~/work/archive/projects/`
- avoid: one giant repo for all of `~/work`

Each project should own:

- its source code
- its tests
- its project-specific config
- its lightweight examples

Do not commit:

- downloaded raw data
- Office documents unless they are intentional source artifacts
- images generated during analysis unless intentionally part of the repo
- caches, temp files, local databases, virtualenvs

## Analysis program repos

Some repos are not a single app. They are a program of analysis subprojects,
for example a strategy repo with many domain-specific exports.

Recommended shape:

- repo root owns shared runtime setup
  - `pyproject.toml`
  - `uv.lock`
  - `.envrc`
  - shared Docker/ODPS helpers
- subprojects own their business logic
  - `docs/`
  - `sql/`
  - `scripts/`
  - `data/`
  - `outputs/`

Use a shared layer when multiple subprojects reuse the same capabilities:

- `shared/connectors/`
- `shared/exporters/`
- `shared/sql/`
- `shared/templates/`
- `shared/skills/`

Use `make new-analysis-subproject` when you need a new analysis unit inside an
existing repo instead of creating another top-level git repository.

Example:

```bash
cd $HOME/work
make new-analysis-subproject \
  PROJECT_ROOT=$HOME/work/projects/analysis-program \
  CONTAINER=operations \
  NAME=inventory_health
```

## Data placement rules

Use lowercase `data/` everywhere. Do not use `DATA/`; case-only differences are
fragile across macOS, Docker, Linux, and CI.

There are two data scopes:

| Host path | Container path | Scope | Access |
|-----------|----------------|-------|--------|
| `~/work/data` | `/workspace/shared-data` | shared workspace data | read-only |
| `~/work/projects/<project>/data` | `/workspace/data` | project-local data | read-write |

Docker Compose mounts them separately:

```
compose.yaml volume mounts:
  ./data:/workspace/data                       # project-local, writable
  ${HOME}/work/data:/workspace/shared-data:ro  # shared, read-only
```

Use `SHARED_DATA_DIR` in code to reference shared data:

```python
import os
from pathlib import Path

DATA_DIR = Path("data")
SHARED_DATA_DIR = Path(os.environ.get("SHARED_DATA_DIR", "/workspace/shared-data"))
```

Put files in `~/work/data` when:

- multiple projects may reuse them
- files are large
- files came from enterprise chat/browser downloads
- files are important reference material, not code

Put files in `~/work/projects/<project>/data` when:

- they are project-local samples
- they are temporary inputs/outputs for that one repo
- they help reproduce the project locally

If project-local `data/` becomes large, move the heavy files to `~/work/data`
and keep only references, manifests, or tiny fixtures in the repo.

## Environment rules

Workspace-level config:

- `~/work/.envrc`
  - only shared variables like `WORK_ROOT`

Project-level config:

- `~/work/projects/<project>/.envrc`
  - project activation logic
- `~/work/projects/<project>/.env`
  - local secrets, ports, machine-specific settings

Recommended rule:

- keep runtime envs project-local
- avoid one shared `~/work/.venv` for everything

For analysis program repos with many subprojects:

- keep one repo-level `pyproject.toml`
- keep one repo-level `uv.lock`
- do not create a separate `.venv` per subproject unless a subproject is being
  split into its own repo

Example:

```bash
cd $HOME/work/projects/<project-name>
python -m venv .venv
direnv allow
```

## Git hygiene

The scaffold already ignores common heavy files:

- parquet/lance/duckdb/arrow/feather
- csv/tsv/xlsx/docx/pptx/pdf
- png/jpg/webp/svg/heic
- `.ruff_cache/`, `.pytest_cache/`, `.mypy_cache/`
- `.venv/`, `.direnv/`, `tmp/`, `logs/`, `artifacts/`, `outputs/`

Before first commit:

```bash
git status
```

Check that only real source files are staged.

## Manual repo creation

If you do not want the scaffold:

```bash
mkdir -p $HOME/work/projects/my-project
cd $HOME/work/projects/my-project
git init -b main
mkdir -p src data notebooks
touch README.md .gitignore .env .env.example .envrc
```

But preferred default: use `./scripts/new-project.sh`.

For nested analysis subprojects, preferred default:

```bash
cd $HOME/work
make new-analysis-subproject \
  PROJECT_ROOT=$HOME/work/projects/<analysis-repo> \
  CONTAINER=<domain-container> \
  NAME=<subproject-name>
```

Or from the workspace root:

```bash
cd $HOME/work
make new-project
```

## Obsidian and knowledge bases

Do not keep long-lived knowledge systems under `~/work/projects` unless they
are tightly bound to a single repo.

- standalone vaults -> `~/work/knowledge/obsidian/`
- project-local `.obsidian/` inside a repo is fine when that repo itself is the
  vault
- large attachments for notes should prefer `~/work/data` or a vault-local
  assets directory, not random placement under `projects/`

## Archive rules

Move items to `~/work/archive` when they are not active but still worth keeping.

- `~/work/archive/projects/`
  - retired repos, frozen snapshots
- `~/work/archive/files/`
  - zip bundles, exported decks, one-off deliveries

Archive should be readable, not runnable by default.

- keep date or source in folder names when useful
- avoid mixing active repos back into archive
- if an archived repo becomes active again, move it back to `projects/`

## Downloads and important files

Auto-organization is enabled for `~/Downloads`.

- important enterprise-sharing files -> `~/work/data/downloads/wecom/...`
- browser software/installers -> `~/work/tmp/downloads/browser/software/...`
- unknown files -> `~/work/tmp/downloads/unsorted/...`

If a downloaded file matters long-term:

- keep it in `~/work/data`
- do not move it into a code repo unless it is truly source material

## Quick checklist

When starting a new repo:

1. create under `~/work/projects`
2. initialize as its own git repo
3. enable `direnv`
4. keep envs local to the project
5. keep big data out of git
6. put shared/important materials in `~/work/data`
7. put project-local data in `./data/` (writable in Docker as `/workspace/data`)
8. use `~/work/tmp` only for disposable files

## Useful make commands

From `~/work`:

```bash
make help
make new-project
make list-projects
make organize-downloads
make cache-report
make clean-cache
make doctor
```
