# Private Overlay Example

Copy this layout into your private repository or ignored `private/` directory.

```text
private/
  clash/
    Merge.yaml
  python/
    odps_config.py
  shell/
    ssh_config.d/
      <host>          # SSH host config snippets (deployed to ~/.ssh/config.d/)
```

Keep real subscription URLs, access keys, personal domains, local hostnames, and
machine-specific notes in `private/`, not in tracked template files.
