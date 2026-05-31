---
name: docker-data-project
description: Use for Docker-first Python data projects where host tools should stay minimal and development, testing, and publishing happen inside containers.
---

# Docker Data Project

Keep the host thin and the container authoritative.

Project expectations:

- `Dockerfile` defines the runtime and system packages.
- `compose.yaml` exposes interactive services such as marimo, notebooks, APIs,
  or databases.
- `.devcontainer/devcontainer.json` lets VS Code attach without installing
  Python/Jupyter extensions on the host.
- `pyproject.toml` and `uv.lock` live in the project.
- `data/` is either ignored, mounted, or documented; never accidentally commit
  private datasets.

Workflow:

1. Build or start the container.
2. Run analysis, tests, linters, and formatters inside the container.
3. Export only intentional artifacts.
4. Push code and lockfiles so the server can reproduce the same environment.

If a command needs host installation, first ask whether it belongs in the
container image instead.
