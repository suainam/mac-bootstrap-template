# Private Overlay

Goal: keep real machine-specific values in a private parent repo while keeping
this template repo public-safe.

## Layout

Keep this public template as a submodule in a private parent repo:

```text
mac-bootstrap-private/
  template/
  private/
  bootstrap.sh
```

Files in `private/` mirror the public repo paths:

```text
private/clash/work-mac.yaml
private/editors/neovim/ai.lua
private/infra/code-server/env.sh
private/python/odps_config.py
private/zerotier/<host>.network-id
private/agent/context7.runtime.jsonc
```

The optional Context7 key belongs in `private/agent/context7.runtime.jsonc` with
mode `0600`. Only `scripts/context7-mcp-bridge.py` reads it for the default-
enabled Codex Context7 server; generated configs and other agent hosts remain
keyless. Missing or placeholder keys use the anonymous service. Validate the
overlay and managed configs with `stat -f '%Sp' private/agent/context7.runtime.jsonc`
and `make doctor-agent`.
The Aliyun DataWorks credentials live in `private/agent/dataworks.runtime.jsonc`
with mode `0600`; only `scripts/dataworks-mcp-bridge.py` reads it, injecting
`ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` / `REGION`
into the child MCP server environment. Validate with
`python3 scripts/dataworks-mcp-bridge.py --validate-private-config`.

Note: Private paths stay as `private/clash/`, `private/infra/`, and `private/python/` (not the new
public paths `proxy/clash/` or `infra/python/`) to avoid breaking existing
private overlays.

Editor-specific private runtime config follows the same rule. For example,
Neovim AI credentials can live in:

```text
private/editors/neovim/ai.lua
```

That file stays in the private parent repo and is loaded at runtime by the
public Neovim config.

`make render-configs` resolves each config in this order:

1. `$MAC_BOOTSTRAP_PRIVATE_DIR/<path>`
2. `../private/<path>`
3. `private/<path>`
4. local ignored `<path>`
5. public `<path>.template`

For Clash specifically, `private/clash/work-mac.yaml` is synced directly to
the active Clash Verge local profile and the app is restarted to force a
mihomo reload.

For remote code-server deployment, `infra/code-server/install.sh` first looks
for `private/infra/code-server/env.sh` (or the same path under
`$MAC_BOOTSTRAP_PRIVATE_DIR`) to load `CODE_SERVER_HOST` and
`CODE_SERVER_DIR`. Keep real bastion names there, not in the public template.

The public `Brewfile` installs the ZeroTier client, but it does not join a
network. Keep network IDs, managed addresses, and host-specific SSH routing in
the private parent, for example under `private/zerotier/` and
`private/shell/ssh_config.d/`. Never copy those values into this template.

Environment-specific additions belong in `private/profiles/<profile>/Brewfile`
and its `Brewfile.experimental` symlink. The public Brewfile evaluates these
once through Homebrew's Ruby DSL; legacy `brew.skip` files are not consumed.
Temporary opt-outs use native `HOMEBREW_BUNDLE_BREW_SKIP` and
`HOMEBREW_BUNDLE_CASK_SKIP` variables.

`scripts/brew-bundle.sh` installs zerobrew through the official Homebrew tap.
Eligible dependency-free core bottles without services or post-install steps
transfer to zb. After installation and `zb doctor`, normal `brew uninstall`
removes the corresponding Brew copy. Migration stops if Brew dependents remain;
it never uses `--ignore-dependencies`. Other formulas, casks, taps and npm stay
Homebrew-owned. Keep `brew` available; do not alias it to `zb`.
Docker Compose/Buildx bottles are linked into `$DOCKER_CONFIG/cli-plugins`
(default: `$HOME/.docker/cli-plugins`) so `docker compose` and `docker buildx`
remain discoverable after the Brew copies are removed.

Shell sources set `ZEROBREW_ROOT` and `ZEROBREW_PREFIX` (default:
`/opt/zerobrew` for both home and work) and prefer its `bin`/`sbin`.
The prefix must be at most 13 characters to fit macOS Mach-O relocation paths.
On each machine, provision the directory once:

```bash
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 755 /opt/zerobrew
```

Then run `scripts/brew-bundle.sh` from the template. Bootstrap invokes
`zb init --no-modify-path`; `system-upgrade` updates both managers. Verify with
`zb doctor`, a second bundle run, migrated command execution, and absence of
transferred packages from `brew list --formula`. Old user-directory stores
are not automatically deleted; remove them only after short-prefix verification.

Parent `bootstrap.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export MAC_BOOTSTRAP_PRIVATE_DIR="$ROOT/private"
exec "$ROOT/template/install.sh" "$@"
```

## Sync

```bash
export MAC_BOOTSTRAP_PRIVATE_REPO="git@github.com:<you>/mac-bootstrap-private.git"
make private-sync
make render-configs
```

Optional:

```bash
export MAC_BOOTSTRAP_PRIVATE_BRANCH=main
```

The sync script does not print the private repo URL, so tokens embedded in a URL
are not echoed to the terminal. Prefer SSH remotes or a credential manager.

## Publishing Publicly

Rule: never make this private repo or its history public. Publish only an export.

Run before publishing:

```bash
make privacy-audit
make privacy-audit-history
```

`make privacy-audit` scans the public export view, not every private tracked
file. `make privacy-audit-history` is intentionally stricter and scans this
private repo history; any hit means the history itself should stay private.

If history contains real secrets, subscription URLs, or private config, do not
publish that history. Rotate affected credentials and publish a fresh export:

```bash
make export-public DEST=/path/to/mac-bootstrap-public
```

Then create the public GitHub repository from that exported directory.

Or publish directly:

```bash
PUBLIC_REPO=<you>/mac-bootstrap-template make publish-public
```

`publish-public` exports into a temporary directory, runs the public-view audit,
creates the GitHub repository as public if needed, commits the exported tree, and
force-pushes a single clean branch. It never pushes this private repo history.
