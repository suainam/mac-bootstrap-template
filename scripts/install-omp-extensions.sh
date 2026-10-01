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

Manifest entries are either registry packages or repository-owned local sources:

  { "package": "@scope/name", "version": "1.2.3", "settings": "name.json" }
  { "kind": "local", "package": "multiplexer/herdr-dispatch/omp/index.ts",
    "target": "dispatch-omp.ts" }

Local entries are symlinked into $PI_CODING_AGENT_DIR/extensions/ so this
repository stays their single source of truth: they are never fetched, never
version-resolved, and cannot be replaced by a registry update.
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

link_settings_file() {
  local settings="$1"
  local source="$ROOT/agent/omp/$settings"
  local target="$AGENT_DIR/$settings"
  [[ -r "$source" ]] || { echo "Missing extension settings: $source" >&2; exit 2; }
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would link $target -> $source"
  else
    link_setting "$source" "$target"
  fi
}

# Registry state is only consulted when a package entry is actually processed,
# so a manifest made purely of local sources needs no registry round-trip.
installed=""
installed_loaded=0

install_package() {
  local package="$1"
  local version="$2"
  if [[ "$installed_loaded" -eq 0 ]]; then
    installed="$(omp plugin list --json)"
    installed_loaded=1
  fi
  local spec="$package@$version"
  local current
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
}

# Unit separator, not tab: tab is IFS whitespace, so `read` would collapse runs
# of empty fields and silently shift every column after the first gap.
while IFS=$'\x1f' read -r kind package version settings target; do
  [[ -n "$package" ]] || continue

  if [[ "$kind" == "local" ]]; then
    [[ -n "$target" ]] || target="$(basename "$package")"
    source="$ROOT/$package"
    link="$AGENT_DIR/extensions/$target"
    [[ -r "$source" ]] || { echo "Missing local extension source: $source" >&2; exit 2; }
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "Would link $link -> $source"
    else
      link_setting "$source" "$link"
    fi
  else
    install_package "$package" "$version"
  fi

  if [[ -n "$settings" ]]; then
    link_settings_file "$settings"
  fi
done < <(
  jq -r '
    .extensions[]
    | [
        (
          if .kind then .kind
          elif (.package | type) == "string" and (.package | startswith("@") | not)
          then "local"
          else "package"
          end
        ),
        (.package // ""),
        (.version // ""),
        (.settings // ""),
        (.target // "")
      ]
    | join("\u001f")' "$MANIFEST"
)