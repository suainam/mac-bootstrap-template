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
  shell/
    ssh_config.d/
      <host>          # SSH host config snippets (deployed to ~/.ssh/config.d/)
```

Keep real subscription URLs, access keys, personal domains, local hostnames, and
machine-specific notes in `private/`, not in tracked template files.
Do not treat Clash Verge Rev files under
`~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/`
as source files; they are generated runtime state.
