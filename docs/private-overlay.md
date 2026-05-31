# Private Overlay

Goal: keep a private working repository with real machine-specific values while
exporting a separate public template tree.

## Layout

This repo's `origin` can stay private and track real config directly. For the
cleaner long-term layout, keep this public template as a submodule in a private
parent repo:

```text
mac-bootstrap-private/
  template/
  private/
  bootstrap.sh
```

Files in `private/` mirror the public repo paths:

```text
private/clash/Merge.yaml
private/python/odps_config.py
```

`make render-configs` resolves each config in this order:

1. `$MAC_BOOTSTRAP_PRIVATE_DIR/<path>`
2. `../private/<path>`
3. `private/<path>`
4. local ignored `<path>`
5. public `<path>.template`

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
