#!/usr/bin/env bash

load_proxy_env_from_shell_env() {
  local shell_env="$1"

  if [ ! -f "$shell_env" ]; then
    echo "Error: $shell_env not found" >&2
    return 1
  fi

  set +u
  . "$shell_env"
  set -u
  proxy_on
}

require_proxy_values() {
  HTTP_PROXY_VAL="${HTTP_PROXY:-}"
  HTTPS_PROXY_VAL="${HTTPS_PROXY:-}"

  if [ -z "$HTTP_PROXY_VAL" ] || [ -z "$HTTPS_PROXY_VAL" ]; then
    echo "Error: proxy values not found in shell environment" >&2
    return 1
  fi
}

write_git_proxy_include() {
  local template="$1"
  local target="$2"

  sed \
    -e "s|__HTTP_PROXY__|$HTTP_PROXY_VAL|g" \
    -e "s|__HTTPS_PROXY__|$HTTPS_PROXY_VAL|g" \
    "$template" > "$target"

  git config --global --unset-all include.path "$target" >/dev/null 2>&1 || true
  git config --global --add include.path "$target"
}

clear_git_proxy_include() {
  local target="$1"

  git config --global --unset-all include.path "$target" >/dev/null 2>&1 || true
  rm -f "$target"
}
