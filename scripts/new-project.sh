#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
name="${PROJECT_NAME:-${1:-}}"
desc="${PROJECT_DESC:-}"

if [ -n "${2:-}" ] && [ -z "$desc" ]; then
  desc="$2"
fi

if [ -z "$name" ]; then
  read -rp "Project name: " name
fi
if [ -z "$desc" ]; then
  read -rp "Description: " desc
fi

target="$HOME/work/projects/$name"

if [ -e "$target" ]; then
  echo "Project path already exists: $target" >&2
  exit 1
fi

mkdir -p "$target/.devcontainer" "$target/notebooks" "$target/src" "$target/data"

# pyproject.toml
cp "$DIR/infra/python/pyproject.template.toml" "$target/pyproject.toml"
sed -i '' "s/my-analysis/$name/; s/description = \"\"/description = \"$desc\"/" "$target/pyproject.toml"

# README
cat > "$target/README.md" << EOF
# $name

$desc

## Docker setup

\`\`\`bash
docker compose up --build
\`\`\`

Open <http://localhost:2718> for Marimo. If you start Jupyter on a server,
use its browser URL directly instead of the VS Code Jupyter extension.

## 数据目录

统一使用小写 \`data/\`：

| 本机路径 | 容器路径 | 范围 | 权限 |
|----------|----------|------|------|
| \`./data/\` | \`/workspace/data\` | 项目数据 | 可读写 |
| \`~/work/data\` | \`/workspace/shared-data\` | 全局共享数据 | 只读 |

\`\`\`python
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
SHARED_DATA_DIR = Path(os.environ.get("SHARED_DATA_DIR", "/workspace/shared-data"))
\`\`\`
EOF

# .gitignore
cat > "$target/.gitignore" << 'EOF'
.venv/
__pycache__/
*.pyc
.python-version
.direnv/
.ruff_cache/
.pytest_cache/
.mypy_cache/
.hypothesis/
.DS_Store
.cache/
tmp/
logs/
.env
.env.*
!.env.example
*.log
*.tmp
*.temp
*.swp
*.bak
*.sqlite
*.sqlite3
*.db
*.parquet
*.parquet.*
*.lance
*.arrow
*.feather
*.ipc
*.duckdb
*.csv
*.tsv
*.xlsx
*.xls
*.doc
*.docx
*.ppt
*.pptx
*.pdf
*.png
*.jpg
*.jpeg
*.gif
*.webp
*.svg
*.heic
data/
artifacts/
outputs/
reports/
.ipynb_checkpoints/
EOF

cat > "$target/.env.example" << 'EOF'
MARIMO_PORT=2718
EOF

cat > "$target/.envrc" << 'EOF'
export PROJECT_ROOT="$PWD"
dotenv_if_exists .env

# Keep Python environments project-local when they exist.
if [ -d "$PWD/.venv" ]; then
  export VIRTUAL_ENV="$PWD/.venv"
  PATH_add "$PWD/.venv/bin"
fi
EOF

# Main script
cat > "$target/main.py" << 'EOF'
"""Entry point."""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
SHARED_DATA_DIR = Path(os.environ.get("SHARED_DATA_DIR", "/workspace/shared-data"))
EOF

cat > "$target/Dockerfile" << 'EOF'
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
RUN uv pip install --system -e .

COPY . .

CMD ["marimo", "edit", "--host=0.0.0.0", "--port=2718"]
EOF

cat > "$target/compose.yaml" << 'EOF'
services:
  analysis:
    build: .
    working_dir: /workspace
    volumes:
      - .:/workspace
      - ./data:/workspace/data
      - ${HOME}/work/data:/workspace/shared-data:ro
    ports:
      - "${MARIMO_PORT:-2718}:2718"
    environment:
      - SHARED_DATA_DIR=/workspace/shared-data
    env_file:
      - .env
    command: marimo edit --host=0.0.0.0 --port=2718
EOF

cat > "$target/.devcontainer/devcontainer.json" << 'EOF'
{
  "name": "analysis",
  "dockerComposeFile": "../compose.yaml",
  "service": "analysis",
  "workspaceFolder": "/workspace",
  "shutdownAction": "stopCompose"
}
EOF

cp "$target/.env.example" "$target/.env"

if command -v git >/dev/null 2>&1; then
  git -C "$target" init -q -b main
fi

direnv_status="not available"
if command -v direnv >/dev/null 2>&1; then
  if direnv allow "$target"; then
    direnv_status="allowed"
  else
    direnv_status="allow failed"
    echo "Warning: direnv allow failed for $target; run it manually in your shell." >&2
  fi
fi

echo ""
echo "Project created: $target"
echo "  cd $target"
if [ "$direnv_status" = "allowed" ]; then
  echo "  direnv allow  # already run automatically"
else
  echo "  direnv allow"
fi
echo "  docker compose up --build"
