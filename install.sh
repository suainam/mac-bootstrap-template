#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
ASSUME_YES=0
RUN_VIM=0
RUN_PROXY=1
RUN_BREW_UPDATE=1
RUN_CLEANUP=0
GIT_NAME="${GIT_NAME:-}"
GIT_EMAIL="${GIT_EMAIL:-}"

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  -y, --yes              Run with defaults where possible.
  --git-name NAME        Configure git user.name.
  --git-email EMAIL      Configure git user.email.
  --with-vim             Install/link Vim config and plugins.
  --skip-proxy           Do not configure Docker/npm proxy.
  --skip-brew-update     Do not run brew update before brew bundle.
  --cleanup              Run safe cache cleanup after install.
  -h, --help             Show this help.

Environment:
  GIT_NAME and GIT_EMAIL can be used instead of --git-name/--git-email.
  MAC_BOOTSTRAP_PRIVATE_REPO optionally points to a private overlay repo.
  MAC_BOOTSTRAP_PRIVATE_DIR optionally points to an external private overlay dir.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes)
      ASSUME_YES=1
      ;;
    --git-name)
      GIT_NAME="${2:?Missing value for --git-name}"
      shift
      ;;
    --git-email)
      GIT_EMAIL="${2:?Missing value for --git-email}"
      shift
      ;;
    --with-vim)
      RUN_VIM=1
      ;;
    --skip-proxy)
      RUN_PROXY=0
      ;;
    --skip-brew-update)
      RUN_BREW_UPDATE=0
      ;;
    --cleanup)
      RUN_CLEANUP=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

echo "=== Create work directories ==="
mkdir -p ~/work/{projects,data,notebooks,scripts,config,tmp}

echo "=== Link workspace entrypoints ==="
for f in Makefile PROJECTS_GUIDE.md; do
  if [ -f "$DIR/workspace/$f" ]; then
    ln -sf "$DIR/workspace/$f" ~/work/"$f"
    echo "  ~/work/$f -> workspace/$f"
  fi
done
if [ -d "$DIR/workspace/scripts" ]; then
  rm -rf ~/work/scripts
  ln -sf "$DIR/workspace/scripts" ~/work/scripts
  echo "  ~/work/scripts -> workspace/scripts"
fi

echo "=== Install Xcode Command Line Tools if needed ==="
if ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install
  echo "Please rerun after Xcode CLI tools installation completes."
  exit 1
fi

echo "=== Install Homebrew if needed ==="
if ! command -v brew >/dev/null 2>&1; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

if [ "$RUN_BREW_UPDATE" -eq 1 ]; then
  echo "=== Update Homebrew ==="
  brew update
fi

echo "=== Install from Brewfile ==="
"$DIR/scripts/brew-bundle.sh"

echo "=== Install Antigravity CLI ==="
"$DIR/scripts/install-antigravity-cli.sh"

echo "=== Configure Git ==="
if [ -z "$GIT_NAME" ]; then
  if [ "$ASSUME_YES" -eq 1 ]; then
    GIT_NAME="$(git config --global user.name || true)"
  else
    read -rp "Git user name: " GIT_NAME
  fi
fi
if [ -z "$GIT_EMAIL" ]; then
  if [ "$ASSUME_YES" -eq 1 ]; then
    GIT_EMAIL="$(git config --global user.email || true)"
  else
    read -rp "Git user email: " GIT_EMAIL
  fi
fi
if [ -n "$GIT_NAME" ]; then
  git config --global user.name "$GIT_NAME"
else
  echo "  Skip user.name: pass --git-name or set GIT_NAME."
fi
if [ -n "$GIT_EMAIL" ]; then
  git config --global user.email "$GIT_EMAIL"
else
  echo "  Skip user.email: pass --git-email or set GIT_EMAIL."
fi
git config --global init.defaultBranch main
git config --global core.autocrlf input
git config --global push.autoSetupRemote true

echo "=== Link shell config ==="
for f in zprofile zshenv zshrc shell_env bash_profile p10k.zsh; do
  if [ -f "$DIR/shell/$f" ]; then
    ln -sf "$DIR/shell/$f" ~/."$f"
    echo "  ~/.$f -> shell/$f"
  fi
done

echo "=== Link terminal helpers ==="
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/scripts/tmux-workspace.sh" "$HOME/.local/bin/tmux-workspace.sh"
chmod +x "$HOME/.local/bin/tmux-workspace.sh"
echo "  ~/.local/bin/tmux-workspace.sh -> scripts/tmux-workspace.sh"

echo "=== Install Hammerspoon config ==="
"$DIR/hammerspoon/install.sh"

echo "=== Configure iTerm2 ==="
"$DIR/iterm2/install.sh"

echo "=== Configure tmux ==="
"$DIR/tmux/install.sh"

echo "=== Setup SSH config ==="
SSH_SRC="$DIR/shell/ssh_config.d"
PRIVATE_SSH_SRC=""
if [ -n "${MAC_BOOTSTRAP_PRIVATE_DIR:-}" ] && [ -d "$MAC_BOOTSTRAP_PRIVATE_DIR/shell/ssh_config.d" ]; then
  PRIVATE_SSH_SRC="$MAC_BOOTSTRAP_PRIVATE_DIR/shell/ssh_config.d"
elif [ -d "$DIR/../private/shell/ssh_config.d" ]; then
  PRIVATE_SSH_SRC="$(cd "$DIR/../private" && pwd)/shell/ssh_config.d"
elif [ -d "$DIR/private/shell/ssh_config.d" ]; then
  PRIVATE_SSH_SRC="$DIR/private/shell/ssh_config.d"
fi
mkdir -p ~/.ssh/config.d
deploy_file() {
  local src="$1" dst="$2"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    return 0
  fi
  cp "$src" "$dst"
}
if [ -f "$DIR/scripts/ssh-connect-proxy.py" ]; then
  deploy_file "$DIR/scripts/ssh-connect-proxy.py" ~/.ssh/connect-proxy.py
  chmod +x ~/.ssh/connect-proxy.py
  echo "  ~/.ssh/connect-proxy.py"
fi
if [ -n "$PRIVATE_SSH_SRC" ]; then
  for f in "$PRIVATE_SSH_SRC"/*; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    [[ "$name" == *.template ]] && continue
    deploy_file "$f" ~/.ssh/config.d/"$name"
    chmod 600 ~/.ssh/config.d/"$name"
    echo "  ~/.ssh/config.d/$name <- private:$name"
  done
else
  for f in "$SSH_SRC"/*; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    [[ "$name" == *.template ]] && continue
    deploy_file "$f" ~/.ssh/config.d/"$name"
    chmod 600 ~/.ssh/config.d/"$name"
    echo "  ~/.ssh/config.d/$name <- template:$name"
  done
fi
if ! grep -q 'Include ~/.ssh/config.d/\*' ~/.ssh/config 2>/dev/null; then
  sed -i '' '1i\
Include ~/.ssh/config.d/*\
' ~/.ssh/config
  echo "  Added Include ~/.ssh/config.d/* to ~/.ssh/config"
fi

if [ "$ASSUME_YES" -eq 0 ] && [ "$RUN_VIM" -eq 0 ]; then
  echo "=== Install vim config? [y/N] ==="
  read -r do_vim
  if [[ "$do_vim" =~ ^[Yy]$ ]]; then
    RUN_VIM=1
  fi
fi
if [ "$RUN_VIM" -eq 1 ]; then
  "$DIR/vim/install.sh"
fi

echo "=== Install VS Code extensions if available ==="
"$DIR/vscode/install-extensions.sh"

if [ "$RUN_PROXY" -eq 1 ]; then
  echo "=== Configure proxy for Docker & npm ==="
  "$DIR/scripts/configure-proxies.sh"
fi

echo "=== Setup Docker & Colima ==="
"$DIR/docker/install.sh"

if [ -n "${MAC_BOOTSTRAP_PRIVATE_REPO:-}" ]; then
  echo "=== Sync private overlay ==="
  "$DIR/scripts/sync-private-overlay.sh"
fi

echo "=== Render config templates ==="
"$DIR/scripts/render-configs.sh"

echo "=== Install Pi packages ==="
if command -v pi >/dev/null 2>&1; then
  "$DIR/scripts/install-pi-packages.sh" --yes
else
  echo "  Pi not installed — skipping Pi packages"
fi

if [ "$RUN_CLEANUP" -eq 1 ]; then
  "$DIR/scripts/clean-cache.sh"
fi

echo "=== Done. Restart your terminal. ==="
