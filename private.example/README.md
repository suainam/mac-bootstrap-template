# Private Overlay Example

Copy this layout into your private repository or ignored `private/` directory.

```text
private/
  clash/
    Merge.yaml
  python/
    odps_config.py
  infra/
    code-server/
      env.sh          # CODE_SERVER_HOST / CODE_SERVER_DIR for deploy scripts
  agent/
    context7.runtime.jsonc  # Optional Context7 key, consumed only by Codex
  shell/
    ssh_config         # Optional override for ~/.ssh/config; canonical source when you want full private ownership
    ssh_config.d/
      <host>          # SSH host config snippets (deployed to ~/.ssh/config.d/)
    ssh_keys/
      <key>           # Private keys (deployed to ~/.ssh/keys/<key> with mode 600)
      <key>.pub       # Public keys (deployed to ~/.ssh/keys/<key>.pub with mode 644)
```

Keep real subscription URLs, access keys, personal domains, local hostnames, and
machine-specific notes in `private/`, not in tracked template files.
Do not treat Clash Verge Rev files under
`~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/`
as source files; they are generated runtime state.
