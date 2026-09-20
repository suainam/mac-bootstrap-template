#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="${OMP_EXTENSIONS_MANIFEST:-$ROOT/agent/omp/extensions.json}"
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.omp/agent}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/install-omp-extensions.sh [--dry-run]

Install the version-pinned public OMP extensions and link their non-secret settings.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ -r "$MANIFEST" ]] || { echo "Missing OMP extension manifest: $MANIFEST" >&2; exit 2; }
command -v jq >/dev/null || { echo "Missing required command: jq" >&2; exit 2; }
command -v omp >/dev/null || { echo "Missing required command: omp" >&2; exit 2; }

jq -e '.version == 1 and (.extensions | type == "array")' "$MANIFEST" >/dev/null || {
  echo "Invalid OMP extension manifest: $MANIFEST" >&2
  exit 2
}

link_setting() {
  local source="$1"
  local target="$2"
  local backup="${target}.pre-mac-bootstrap"
  mkdir -p "$(dirname "$target")"
  if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
    return 0
  fi
  if [[ -L "$target" ]]; then
    rm -f "$target"
  elif [[ -e "$target" ]]; then
    if [[ -e "$backup" || -L "$backup" ]]; then
      echo "Refusing to overwrite $target; backup already exists: $backup" >&2
      exit 2
    fi
    mv "$target" "$backup"
  fi
  ln -s "$source" "$target"
}

installed="$(omp plugin list --json)"
while IFS=$'\t' read -r package version settings; do
  [[ -n "$package" ]] || continue
  spec="$package@$version"
  current="$(jq -r --arg package "$package" '.npm[] | select(.name == $package) | .version' <<<"$installed" | sed -n '1p')"
  if [[ "$current" != "$version" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "Would install $spec"
    else
      omp install "$spec"
      installed="$(omp plugin list --json)"
    fi
  else
    echo "Already installed $spec"
  fi

  if [[ -n "$settings" ]]; then
    source="$ROOT/agent/omp/$settings"
    target="$AGENT_DIR/$settings"
    [[ -r "$source" ]] || { echo "Missing extension settings: $source" >&2; exit 2; }
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "Would link $target -> $source"
    else
      link_setting "$source" "$target"
    fi
  fi
done < <(jq -r '.extensions[] | [.package, .version, (.settings // "")] | @tsv' "$MANIFEST")
