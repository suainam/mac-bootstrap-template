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
private/agent/x-mcp.jsonc
private/infra/code-server/env.sh
private/python/odps_config.py
private/zerotier/<host>.network-id
```

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

For Clash specifically, private `private/clash/work-mac.yaml` is synced directly to
the local Clash runtime profile. It is not copied back into
`proxy/clash/Merge.yaml`.

For remote code-server deployment, `infra/code-server/install.sh` first looks
for `private/infra/code-server/env.sh` (or the same path under
`$MAC_BOOTSTRAP_PRIVATE_DIR`) to load `CODE_SERVER_HOST` and
`CODE_SERVER_DIR`. Keep real bastion names there, not in the public template.

The public `Brewfile` installs the ZeroTier client, but it does not join a
network. Keep network IDs, managed addresses, and host-specific SSH routing in
the private parent, for example under `private/zerotier/` and
`private/shell/ssh_config.d/`. Never copy those values into this template.

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
