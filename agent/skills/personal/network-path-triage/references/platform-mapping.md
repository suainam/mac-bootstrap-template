# Platform Mapping

Use this file when the incident is obviously tied to one runtime surface and you
need the closest equivalent check on another platform.

## Shared logic

All platforms answer the same questions:

1. who originated the traffic
2. whether system proxy / PAC shaped it
3. whether TUN or equivalent virtual routing captured it
4. whether the proxy engine owned the final connect
5. which layer boundary actually failed

## macOS host

Typical surfaces:

- `networksetup` for system proxy / PAC
- `route -n get` for route ownership
- Clash Verge runtime files under
  `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/`
- `launchctl print ...` for helper persistence
- process list for `verge-mihomo`, `CorpLink`, `UURemote`

## Windows host

Typical surfaces:

- Windows proxy settings / PAC source
- route table and interface metrics
- Clash / Mihomo generated config on the host
- Task Manager / process list / service state
- firewall rules on the WSL virtual interface when guest reachability disagrees

Repo sample lessons:

- `find-process-mode: always` is safer than `strict` when WSL / VM traffic
  depends on host-side process lookup
- host proxy port reachable but WSL guest not reachable often points to Windows
  firewall ingress, not rule order

## WSL guest

Typical surfaces:

- guest DNS result
- guest route to the target
- guest reachability to the host proxy port
- whether the guest subnet is excluded from host TUN capture

Repo sample lessons:

- if WSL traffic is captured by host TUN and then judged `DIRECT`, you can
  create self-deadlock or timeouts
- WSL subnet exclusions are often correctness requirements, not optimizations

## Mapping table

| Question | macOS sample | Windows host sample | WSL guest sample |
| --- | --- | --- | --- |
| system proxy / PAC owner | `networksetup` | Windows proxy settings | guest app env / inherited config |
| route owner | `route -n get` | route table / interface metric | guest route table |
| proxy engine owner | Clash service log | Clash / Mihomo log | host-side proxy log plus guest test |
| helper persistence | `launchctl` | service / startup task | usually inherited from host |
| host-guest disagreement | n/a | compare host vs WSL proxy-port reachability | compare guest vs host proxy-port reachability |
