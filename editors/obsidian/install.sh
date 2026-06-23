#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT="${1:-}"

if [ -z "$VAULT" ]; then
  echo "Usage: editors/obsidian/install.sh /path/to/vault" >&2
  exit 2
fi

echo "=== Install Obsidian vault kit ==="
mkdir -p "$VAULT/.obsidian" "$VAULT/docs/templates" "$VAULT/docs/daily" "$VAULT/docs/weekly" "$VAULT/docs/monthly" "$VAULT/docs/quarterly" "$VAULT/docs/yearly"

copy_file() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  echo "  $dst <- ${src#$DIR/}"
}

for f in app.json appearance.json community-plugins.json core-plugins.json daily-notes.json templates.json; do
  copy_file "$DIR/vault/.obsidian/$f" "$VAULT/.obsidian/$f"
done

mkdir -p "$VAULT/.obsidian/plugins/periodic-notes" "$VAULT/.obsidian/plugins/templater-obsidian"
copy_file "$DIR/vault/.obsidian/plugins/periodic-notes/data.json" "$VAULT/.obsidian/plugins/periodic-notes/data.json"
copy_file "$DIR/vault/.obsidian/plugins/templater-obsidian/data.json" "$VAULT/.obsidian/plugins/templater-obsidian/data.json"

for f in daily.md weekly.md monthly.md quarterly.md yearly.md; do
  copy_file "$DIR/vault/docs/templates/$f" "$VAULT/docs/templates/$f"
done

echo "Done. Open or reload Obsidian vault: $VAULT"
