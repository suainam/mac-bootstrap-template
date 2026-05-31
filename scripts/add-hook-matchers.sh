#!/usr/bin/env bash
# Add finer-grained PreToolUse and PostToolUse hook matchers to Claude settings.json
# These supplement the core hooks managed by caveman/rtk.

set -euo pipefail

DRY_RUN=0
case "${1:-}" in --dry-run) DRY_RUN=1 ;; esac

SETTINGS="$HOME/.claude/settings.json"
[ -f "$SETTINGS" ] || { echo "No settings.json found at $SETTINGS"; exit 0; }

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# Add additional hook matchers via Node.js JSON manipulation
run node - "$SETTINGS" <<'NODE'
const fs = require("fs");
const path = process.argv[2];
const data = JSON.parse(fs.readFileSync(path, "utf8"));

if (!data.hooks) data.hooks = {};
if (!data.hooks.PreToolUse) data.hooks.PreToolUse = [];
if (!data.hooks.PostToolUse) data.hooks.PostToolUse = [];

const pre = data.hooks.PreToolUse;
const post = data.hooks.PostToolUse;

// Check if our matchers already exist
const hasMatcher = (arr, matcher) =>
  arr.some(h => h.matcher === matcher);

// PreToolUse: detect console.log in Edit on .ts/.tsx files
if (!hasMatcher(pre, "tool == \"Edit\" && args.file_path matches \"\\.(ts|tsx|js|jsx)$\"")) {
  pre.push({
    "matcher": "tool == \"Edit\" && args.file_path matches \"\\.(ts|tsx|js|jsx)$\"",
    "hooks": [{
      "type": "command",
      "command": "echo 'CHECK: remove console.log before commit'"
    }]
  });
}

// PreToolUse: warn on destructive npm/pip operations
if (!hasMatcher(pre, "tool == \"Bash\" && command matches \"(npm publish|pip install --user|rm -rf /)\"")) {
  pre.push({
    "matcher": "tool == \"Bash\" && command matches \"(npm publish|pip install --user|rm -rf /)\"",
    "hooks": [{
      "type": "command",
      "command": "echo 'WARNING: destructive operation — confirm with user first'"
    }]
  });
}

// PostToolUse: remind about tests after Edit
if (!hasMatcher(post, "tool == \"Edit\"")) {
  post.push({
    "matcher": "tool == \"Edit\"",
    "hooks": [{
      "type": "command",
      "command": "echo 'REMINDER: run tests after code changes'"
    }]
  });
}

fs.writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
console.log("Added finer-grained hook matchers to settings.json");
NODE
