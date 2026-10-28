# Local Persistent `fake-ip-filter` Injection (no subscription edits)

## When to use

You need a company/enterprise domain to resolve to a **real IP** (bypass Mihomo
fake-ip `198.19.x.x`) on a persistent basis, but you do **not** want to edit the
cloud subscription (which refreshes and can silently drop your entry, and which
you may not control).

Typical symptom that lands here:

- `di +short <domain> A` returns `198.19.0.x` (fake-ip) even after TUN
  exclusions were added, because DNS is still hijacked by Mihomo's fake-ip
  resolver.
- Browser/CLI fail with `T_CONNECTION_CLOSED` / `SSL_ERROR_SYSCALL` while the
  underlying route is already correct (see `corplink-experience.md` §13).

## Ownership boundary (the critical rule)

In Clash Verge Rev (v2.5.5+):

- **`tun.route-exclude-address` is app-owned.** Script writes are dropped with a
  warning. Always add `/32` exclusions in GUI Settings -> TUN Mode (⚙️) ->
  Route Exclude Address (persisted to `config.yaml`).
- **`dns.fake-ip-filter` list is script-writable.** The GUI has no list editor
  for it (the DNS settings page only toggles enhanced mode). Injecting entries
  via the Global Script is honored in the generated `clash-verge.yaml`. This is
  the verified path (2026-10-28, `+.ex-talent.com`).

So: TUN exclusions go to **GUI**; fake-ip-filter entries go to **Script.js**.


## Automation entry

The repo `Makefile` target `make clash-script-sync` renders `private/clash/Script.js`
from the Vault and writes to BOTH runtime projections (Global Script + current
profile-bound script). It uses the template venv python (`template/.venv/bin/python`),
which has PyYAML. Run it after editing any injection block, then re-apply the
profile in the GUI.
## Entry points (must keep all three in sync)

| File | Role |
| :--- | :--- |
| `private/clash/Script.js` | repo source of truth |
| `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/Script.js` | Global Script runtime projection |
| `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/<profile-script-uid>.js` | current profile-bound script projection (resolve from `profiles.yaml` -> `current` -> `option.script`) |

The repo source uses `__VARS__` placeholders (deployed by
`sync-clash-wireguard.py`). The runtime projections contain rendered values. Do
not copy one over the other blindly; apply the same injection block to all
three.

## Injection block (ES5, appended inside `main()` before `return config;`)

```javascript
// 本机持久 fake-ip-filter 豁免：域名避免被 DNS 劫持引入 TUN
var localFakeIpFilter = [
  '+.ex-talent.com'
];
if (config && config.dns && Array.isArray(config.dns['fake-ip-filter'])) {
  for (var j = 0; j < localFakeIpFilter.length; j++) {
    if (config.dns['fake-ip-filter'].indexOf(localFakeIpFilter[j]) === -1) {
      config.dns['fake-ip-filter'].push(localFakeIpFilter[j]);
    }
  }
}
```

Idempotent: only appends missing entries, never duplicates, never removes
subscript entries.

## Verification

```bash
# 1. syntax check all three
node --check private/clash/Script.js
node --check "$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/Script.js"
node --check "$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/<uid>.js"

# 2. trigger re-apply in GUI (right-click profile -> 重新应用 / restart Verge)

# 3. confirm the entry survives in final runtime config
rtk grep -n 'ex-talent' \
  "$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml"
# expect a fake-ip-filter line.

# 4. confirm DNS now returns a real IP
dig +short <domain> A   # expect real IP, not 198.19.x.x

# 5. browser: flush stale socket pools (chrome://net-internals/#sockets -> Flush), then hard reload
```

## Guardrail

Do not put every domain here. Use it only for targets that must resolve real and
that are not otherwise controllable. For general rule behaviour, prefer
`fake-ip-filter` cloud entries or `PROCESS-PATH` where they fit.
