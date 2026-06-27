#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_SSH_CONFIG_DIR="$TEMPLATE_DIR/shell/ssh_config.d"
TEMPLATE_SSH_MAIN_CONFIG="$TEMPLATE_DIR/shell/ssh_config"
SSH_KEY_RUNTIME_DIR="$HOME/.ssh/keys"

usage() {
  cat <<'EOF'
Usage:
  scripts/ssh-manage.sh install
  scripts/ssh-manage.sh verify
  scripts/ssh-manage.sh add-key --name NAME [--generate|--import PATH|--stdin] [options]

Commands:
  install    Deploy SSH config snippets, keys, and helper scripts into ~/.ssh/.
  verify     Validate deployed SSH config, keys, permissions, and ssh -G output.
  add-key    Create or import a key into private/shell/ssh_keys/ and optionally
             scaffold a host config snippet.

add-key options:
  --name NAME        Key filename under private/shell/ssh_keys/ (required).
  --generate         Generate a new key with ssh-keygen.
  --type TYPE        Key type for --generate (default: ed25519).
  --import PATH      Import an existing private key from PATH.
  --stdin            Read a pasted private key from stdin.
  --host NAME        Also create private/shell/ssh_config.d/NAME if missing.
  --hostname HOST    HostName for the generated host snippet.
  --user USER        User for the generated host snippet.
  --port PORT        Port for the generated host snippet (default: 22).
EOF
}

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

resolve_private_shell_dir() {
  if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR/shell" ]; then
    printf '%s\n' "$MAC_BOOTSTRAP_PRIVATE_DIR/shell"
    return
  fi
  if [ -d "$TEMPLATE_DIR/../private/shell" ]; then
    (
      cd "$TEMPLATE_DIR/../private"
      printf '%s\n' "$PWD/shell"
    )
    return
  fi
  if [ -d "$TEMPLATE_DIR/private/shell" ]; then
    printf '%s\n' "$TEMPLATE_DIR/private/shell"
    return
  fi
}

PRIVATE_SHELL_DIR="${PRIVATE_SHELL_DIR:-$(resolve_private_shell_dir)}"
PRIVATE_SSH_CONFIG_DIR=""
PRIVATE_SSH_KEYS_DIR=""
PRIVATE_SSH_MAIN_CONFIG=""
if [ -n "$PRIVATE_SHELL_DIR" ]; then
  PRIVATE_SSH_CONFIG_DIR="$PRIVATE_SHELL_DIR/ssh_config.d"
  PRIVATE_SSH_KEYS_DIR="$PRIVATE_SHELL_DIR/ssh_keys"
  PRIVATE_SSH_MAIN_CONFIG="$PRIVATE_SHELL_DIR/ssh_config"
fi

ensure_private_shell_dir() {
  [ -n "$PRIVATE_SHELL_DIR" ] || die "private shell dir not found; set MAC_BOOTSTRAP_PRIVATE_DIR or create private/shell"
}

ensure_ssh_root() {
  mkdir -p "$HOME/.ssh" "$HOME/.ssh/config.d" "$SSH_KEY_RUNTIME_DIR"
  chmod 700 "$HOME/.ssh"
  chmod 700 "$HOME/.ssh/config.d" "$SSH_KEY_RUNTIME_DIR"
}

set_source_mode() {
  local mode="$1" path="$2"
  chmod "$mode" "$path"
}

deploy_link() {
  local src="$1" dst="$2" mode="$3"
  mkdir -p "$(dirname "$dst")"
  set_source_mode "$mode" "$src"
  rm -rf "$dst"
  ln -sf "$src" "$dst"
}

main_config_source() {
  if [ -n "$PRIVATE_SSH_MAIN_CONFIG" ] && [ -f "$PRIVATE_SSH_MAIN_CONFIG" ]; then
    printf '%s\n' "$PRIVATE_SSH_MAIN_CONFIG"
  else
    printf '%s\n' "$TEMPLATE_SSH_MAIN_CONFIG"
  fi
}

deploy_main_config() {
  local src
  src="$(main_config_source)"
  deploy_link "$src" "$HOME/.ssh/config" 600
  log "  ~/.ssh/config -> $src"
}

deploy_config_sources() {
  local src_dir="$1" label="$2"
  [ -d "$src_dir" ] || return 0
  local f name
  for f in "$src_dir"/*; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    [[ "$name" == *.template ]] && continue
    deploy_link "$f" "$HOME/.ssh/config.d/$name" 600
    log "  ~/.ssh/config.d/$name -> $label:$name"
  done
}

gather_identity_filenames() {
  local config_dir="$1"
  [ -d "$config_dir" ] || return 0
  awk '
    /^[[:space:]]*IdentityFile[[:space:]]+~\/\.ssh\/keys\// {
      sub(/^[[:space:]]*IdentityFile[[:space:]]+~\/\.ssh\/keys\//, "", $0)
      split($0, parts, /[[:space:]]+/)
      print parts[1]
    }
  ' "$config_dir"/*
}

deploy_key_file() {
  local src="$1"
  local name
  name="$(basename "$src")"
  if [[ "$name" == *.pub ]]; then
    deploy_link "$src" "$SSH_KEY_RUNTIME_DIR/$name" 644
  else
    deploy_link "$src" "$SSH_KEY_RUNTIME_DIR/$name" 600
  fi
  log "  ~/.ssh/keys/$name -> $(dirname "$src")/$(basename "$src")"
}

deploy_private_keys() {
  [ -n "$PRIVATE_SHELL_DIR" ] || return 0
  local deployed_list="" f key_name
  if [ -d "$PRIVATE_SSH_KEYS_DIR" ]; then
    for f in "$PRIVATE_SSH_KEYS_DIR"/*; do
      [ -f "$f" ] || continue
      deploy_key_file "$f"
      deployed_list="${deployed_list}
$(basename "$f")"
    done
  fi
  if [ -d "$PRIVATE_SSH_CONFIG_DIR" ]; then
    while IFS= read -r key_name; do
      [ -n "$key_name" ] || continue
      if printf '%s\n' "$deployed_list" | grep -Fxq "$key_name"; then
        continue
      fi
      if [ -f "$PRIVATE_SHELL_DIR/$key_name" ]; then
        deploy_key_file "$PRIVATE_SHELL_DIR/$key_name"
        deployed_list="${deployed_list}
$key_name"
      fi
      if [ -f "$PRIVATE_SHELL_DIR/$key_name.pub" ] && ! printf '%s\n' "$deployed_list" | grep -Fxq "$key_name.pub"; then
        deploy_key_file "$PRIVATE_SHELL_DIR/$key_name.pub"
        deployed_list="${deployed_list}
$key_name.pub"
      fi
    done < <(gather_identity_filenames "$PRIVATE_SSH_CONFIG_DIR" | sort -u)
  fi
}

deploy_proxy_helper() {
  local src="$TEMPLATE_DIR/scripts/ssh-connect-proxy.py"
  if [ -f "$src" ]; then
    deploy_link "$src" "$HOME/.ssh/connect-proxy.py" 755
    chmod +x "$src"
    log "  ~/.ssh/connect-proxy.py -> $src"
  fi
}

cleanup_legacy_backups() {
  local path
  for path in "$HOME/.ssh"/*.corrupt.* "$HOME/.ssh"/*.bak "$HOME/.ssh"/known_hosts.old; do
    [ -e "$path" ] || continue
    rm -f "$path"
    log "  removed legacy backup $path"
  done
}

cleanup_legacy_key_entries() {
  local f name
  [ -d "$PRIVATE_SSH_KEYS_DIR" ] || return 0
  for f in "$PRIVATE_SSH_KEYS_DIR"/*; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    if [ -e "$HOME/.ssh/$name" ] || [ -L "$HOME/.ssh/$name" ]; then
      rm -f "$HOME/.ssh/$name"
      log "  removed legacy top-level key ~/.ssh/$name"
    fi
  done
}

managed_host_aliases() {
  local src_dir="$1"
  [ -d "$src_dir" ] || return 0
  awk '
    /^[[:space:]]*Host[[:space:]]+/ {
      for (i = 2; i <= NF; i++) {
        if ($i !~ /[*?!]/) {
          print $i
        }
      }
    }
  ' "$src_dir"/* | sort -u
}

verify_symlink_target() {
  local path="$1"
  [ -L "$path" ] || die "$path is not a symlink"
  [ -e "$path" ] || die "$path is a broken symlink"
}

verify_source_mode() {
  local path="$1" expected="$2"
  local actual
  actual="$(stat -f '%Lp' "$path")"
  [ "$actual" = "$expected" ] || die "$path mode is $actual, expected $expected"
}

verify_identity_paths() {
  local host="$1"
  local out
  if ! out="$(ssh -G "$host" 2>&1)"; then
    printf '%s\n' "$out" >&2
    die "ssh -G $host failed"
  fi
  while IFS= read -r identity; do
    [ -n "$identity" ] || continue
    if [[ "$identity" == "$HOME/.ssh/"* ]] && [ ! -e "$identity" ]; then
      die "ssh -G $host resolved missing IdentityFile $identity"
    fi
  done < <(printf '%s\n' "$out" | awk '$1 == "identityfile" { print $2 }')
}

verify_runtime_layout() {
  local path name kind
  for path in "$HOME/.ssh"/*; do
    [ -e "$path" ] || [ -L "$path" ] || continue
    name="$(basename "$path")"
    kind="$(stat -f '%HT' "$path")"
    case "$name" in
      config|connect-proxy.py)
        verify_symlink_target "$path"
        ;;
      config.d|keys)
        [ "$kind" = "Directory" ] || die "$path must be a directory"
        ;;
      known_hosts)
        [ "$kind" = "Regular File" ] || die "$path must be a regular file"
        ;;
      agent)
        [ "$kind" = "Directory" ] || die "$path must be a directory"
        ;;
      cm-*)
        [ "$kind" = "Socket" ] || die "$path must be a control socket"
        ;;
      *)
        die "unexpected ~/.ssh entry: $name"
        ;;
    esac
  done
}

cmd_install() {
  ensure_ssh_root
  log "=== Setup SSH config ==="
  deploy_main_config
  deploy_proxy_helper
  if [ -d "$PRIVATE_SSH_CONFIG_DIR" ]; then
    deploy_config_sources "$PRIVATE_SSH_CONFIG_DIR" "private"
  else
    deploy_config_sources "$TEMPLATE_SSH_CONFIG_DIR" "template"
  fi
  deploy_private_keys
  cleanup_legacy_backups
  cleanup_legacy_key_entries
}

cmd_verify() {
  ensure_ssh_root
  local config_dir config_src
  if [ -d "$PRIVATE_SSH_CONFIG_DIR" ]; then
    config_dir="$PRIVATE_SSH_CONFIG_DIR"
  else
    config_dir="$TEMPLATE_SSH_CONFIG_DIR"
  fi
  config_src="$(main_config_source)"
  verify_symlink_target "$HOME/.ssh/config"
  [ "$(realpath "$HOME/.ssh/config")" = "$(realpath "$config_src")" ] || die "~/.ssh/config points to unexpected target"
  verify_source_mode "$config_src" 600
  verify_symlink_target "$HOME/.ssh/connect-proxy.py"
  verify_source_mode "$TEMPLATE_DIR/scripts/ssh-connect-proxy.py" 755

  local f name
  for f in "$config_dir"/*; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    [[ "$name" == *.template ]] && continue
    verify_symlink_target "$HOME/.ssh/config.d/$name"
    verify_source_mode "$f" 600
  done

  if [ -d "$PRIVATE_SSH_KEYS_DIR" ]; then
    for f in "$PRIVATE_SSH_KEYS_DIR"/*; do
      [ -f "$f" ] || continue
      name="$(basename "$f")"
      verify_symlink_target "$SSH_KEY_RUNTIME_DIR/$name"
      if [[ "$name" == *.pub ]]; then
        verify_source_mode "$f" 644
      else
        verify_source_mode "$f" 600
      fi
    done
  fi

  if [ -d "$PRIVATE_SSH_CONFIG_DIR" ]; then
    while IFS= read -r name; do
      [ -n "$name" ] || continue
      verify_symlink_target "$SSH_KEY_RUNTIME_DIR/$name"
    done < <(gather_identity_filenames "$PRIVATE_SSH_CONFIG_DIR" | sort -u)
  fi

  while IFS= read -r host; do
    [ -n "$host" ] || continue
    verify_identity_paths "$host"
  done < <(managed_host_aliases "$config_dir")

  for name in connect-proxy.py config; do
    verify_symlink_target "$HOME/.ssh/$name"
  done
  verify_runtime_layout
  log "SSH verify ok"
}

write_host_snippet() {
  local host="$1" hostname="$2" user="$3" port="$4" key_name="$5"
  local dst="$PRIVATE_SSH_CONFIG_DIR/$host"
  [ ! -e "$dst" ] || die "host snippet already exists: $dst"
  mkdir -p "$PRIVATE_SSH_CONFIG_DIR"
  cat >"$dst" <<EOF
Host $host
  HostName $hostname
  User $user
  Port $port
  IdentityFile ~/.ssh/keys/$key_name
  IdentitiesOnly yes
EOF
  chmod 600 "$dst"
  log "  created $dst"
}

cmd_add_key() {
  ensure_private_shell_dir
  mkdir -p "$PRIVATE_SSH_KEYS_DIR" "$PRIVATE_SSH_CONFIG_DIR"
  local name="" mode="" key_type="ed25519" import_path="" host="" hostname="" user="" port="22"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --name) name="${2:?missing value for --name}"; shift ;;
      --generate) mode="generate" ;;
      --type) key_type="${2:?missing value for --type}"; shift ;;
      --import) mode="import"; import_path="${2:?missing value for --import}"; shift ;;
      --stdin) mode="stdin" ;;
      --host) host="${2:?missing value for --host}"; shift ;;
      --hostname) hostname="${2:?missing value for --hostname}"; shift ;;
      --user) user="${2:?missing value for --user}"; shift ;;
      --port) port="${2:?missing value for --port}"; shift ;;
      *) die "unknown add-key option: $1" ;;
    esac
    shift
  done
  [ -n "$name" ] || die "--name is required"
  [ -n "$mode" ] || die "choose one of --generate, --import, or --stdin"

  local dst="$PRIVATE_SSH_KEYS_DIR/$name"
  [ ! -e "$dst" ] || die "key already exists: $dst"

  case "$mode" in
    generate)
      ssh-keygen -q -t "$key_type" -N '' -f "$dst"
      ;;
    import)
      cp "$import_path" "$dst"
      if [ -f "$import_path.pub" ]; then
        cp "$import_path.pub" "$dst.pub"
      fi
      ;;
    stdin)
      cat >"$dst"
      ;;
  esac

  chmod 600 "$dst"
  if [ -f "$dst.pub" ]; then
    chmod 644 "$dst.pub"
  fi
  log "  created $dst"
  if [ -n "$host" ]; then
    [ -n "$hostname" ] || die "--hostname is required when --host is set"
    [ -n "$user" ] || die "--user is required when --host is set"
    write_host_snippet "$host" "$hostname" "$user" "$port" "$name"
  fi
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    install)
      shift
      cmd_install "$@"
      ;;
    verify)
      shift
      cmd_verify "$@"
      ;;
    add-key)
      shift
      cmd_add_key "$@"
      ;;
    -h|--help|"")
      usage
      ;;
    *)
      die "unknown command: $cmd"
      ;;
  esac
}

main "$@"
