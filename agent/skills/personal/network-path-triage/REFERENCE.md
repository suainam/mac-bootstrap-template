# Reference

## Leading word

Path-first = prove the traffic path before changing config.

## Live file map

- Repo source: `private/clash/work-mac.yaml`
- Main note: `private/clash/corplink-experience.md`
- Route helper: `scripts/check-routes.sh`
- Sample hosts: `examples/company-hosts.sample.txt`
- macOS Clash runtime root sample:
  `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/`
- macOS active profile index sample:
  `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles.yaml`
- macOS final runtime config sample:
  `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml`

## Platform branches

- macOS:
  current repo ships exact live command examples for Clash Verge Rev, PAC, and launchd.
- Windows host:
  current repo ships sample lessons inside `private/clash/work-mac.yaml` comments:
  `find-process-mode: always`, WSL firewall ingress, and WSL proxy-port reachability.
- WSL guest:
  current repo ships sample lessons for host-vs-guest reachability and why
  `route-exclude-address` must protect the WSL subnet.

Method is shared across all three. Exact commands in this reference are Mac-first
examples unless a branch says otherwise.

## macOS sample command set

Use the smallest command that can prove the current layer. In this repo, prefer
the local shell wrapper convention and run shell examples through `rtk`.

```bash
# repo source
rtk sed -n '1,260p' private/clash/work-mac.yaml

# active profile
rtk sed -n '1,220p' ~/Library/Application\ Support/io.github.clash-verge-rev.clash-verge-rev/profiles.yaml

# selected local profile body
rtk sed -n '1,260p' ~/Library/Application\ Support/io.github.clash-verge-rev.clash-verge-rev/profiles/LFYEU2DnJ6qB.yaml

# bound profile script
rtk sed -n '1,200p' ~/Library/Application\ Support/io.github.clash-verge-rev.clash-verge-rev/profiles/sbzhF1r8fVFA.js

# final runtime config
rtk sed -n '1,260p' ~/Library/Application\ Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml

# system proxy / PAC
networksetup -getautoproxyurl Wi-Fi
networksetup -getwebproxy Wi-Fi
networksetup -getsecurewebproxy Wi-Fi

# helper processes
ps aux | rg 'CorpLink|UURemote|clash-verge|verge-mihomo'

# launchd ownership
launchctl print system/com.volcengine.corplink.service

# Clash service logs
rtk rg -n 'match |dial |permission denied|i/o timeout' \
  ~/Library/Application\ Support/io.github.clash-verge-rev.clash-verge-rev/logs/service

# sample host route snapshot
rtk .agents/skills/network-path-triage/scripts/check-routes.sh --sample

# real host route snapshot
rtk .agents/skills/network-path-triage/scripts/check-routes.sh host1.example.com host2.example.com

# hosts file route snapshot
rtk .agents/skills/network-path-triage/scripts/check-routes.sh --hosts-file /path/to/hosts.txt

# ad hoc target route snapshot
dig +short <host> A
route -n get <ip>

# targeted grep in final runtime config
rtk rg -n "route-exclude-address|respect-rules|stack:|DOMAIN-SUFFIX,dslyy.com|DOMAIN-SUFFIX,dslbuy.com|GEOSITE,CN|GEOIP,CN|DOMAIN-SUFFIX,cn" \
  ~/Library/Application\ Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml
```

The bundled sample hosts are historical examples only. For real incidents, pass
the current environment's actual hosts. For one-off targets, the ad hoc
`dig + route -n get` flow is often simpler.

## Windows / WSL sample checks

These are sample checks derived from the repo's current Clash source comments:

- verify `find-process-mode: always` when WSL / VM traffic depends on host Clash
- verify `route-exclude-address` covers the active WSL subnet
- compare host proxy-port reachability vs guest proxy-port reachability
- if host works but WSL does not, inspect Windows firewall ingress on the WSL
  virtual interface before changing rules

## Interpretation checklist

When a company target fails, answer these in order:

1. Which app originated the traffic?
2. Did that app honor system proxy / PAC?
3. Did the resolved target IP route to `198.18.0.1`?
4. Did Mihomo log the target?
5. If yes, what final action was used?
6. Is the target a browser-only site, a private IP, a WAF public IP, or an AI /
   cloud-desktop endpoint?

## Known local truths

- `utun1024` + gateway `198.18.0.1` is the recognizable Clash TUN pattern here.
- `CorpLink` and `UURemote` may keep launchd-backed helpers alive after the UI
  exits.
- `DIRECT` can still mean `app -> Mihomo -> DIRECT -> target`.
- `PAC DIRECT` can still mean `browser socket -> Clash TUN -> target`.
- A `/32` exclusion is a last-mile fix, not a default response.

## Escalation hints

- Browser-only failure, CLI fine -> inspect PAC and browser path first.
- CLI or Mihomo gets `permission denied` to company targets -> suspect app-path
  policy difference, not only DNS.
- CN enterprise/cloud-desktop domain still needs proxy -> inspect broad CN rules
  before changing DNS.

## Delivery schema

Use this exact answer shape when you close a diagnosis:

```text
origin app: ...
PAC/system proxy: ...
TUN: ...
Mihomo: ...
owning layer: ...
minimal fix: ...
verification: ...
```
