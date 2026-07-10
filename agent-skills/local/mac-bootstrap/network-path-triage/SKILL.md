---
name: network-path-triage
description: >
  Path-first troubleshooting for enterprise access, proxy, PAC, TUN, DNS, and
  route anomalies across macOS, Windows, and WSL. Use when the user reports
  飞连/CorpLink, 无影云/UURemote, Clash Verge, WSL proxy failures, PAC/TUN
  conflicts, "内网不通", "外网正常但公司站点异常", or asks which layer owns a
  failing connection path. Also use when another skill needs real route/config
  diagnosis before changing network settings.
---

# Network Path Triage

Path-first. Do not guess from symptoms. Prove which layer owns the failing path:

1. Browser/system proxy or PAC
2. Clash TUN routing
3. Mihomo rules / DNS
4. Platform-specific helper/runtime state
5. Remote target or current network

## Steps

### 1. Freeze the path model

Always start from the main note:

- `private/clash/corplink-experience.md`

Then branch:

- identify the current platform branch first: macOS host, Windows host, or WSL guest
- read `private/clash/work-mac.yaml` when the task is about intended source
  rules or the repo's Win/WSL sample lessons
- read `scripts/check-routes.sh` when you need a route snapshot helper
- use `examples/company-hosts.sample.txt` only as a sample input set, never as a
  canonical production host list
- use the live runtime files when the task is about current machine state

Completion criterion: you can state the expected path for the failing traffic in
one line, such as `Chrome -> PAC DIRECT -> browser socket -> maybe TUN`, and you
know which next artifact proves it on the current platform.

### 2. Inspect live ownership, not repo intent

Check the active runtime layers before proposing a fix:

- platform-owned runtime directory or service surface
- active profile or equivalent selected config
- selected profile body or effective generated config
- relevant service logs and helper processes

Completion criterion: every claim about "current config" is backed by a live file,
log line, process, route, or command result.

### 3. Separate match from path

Never stop at "rule matched DIRECT" or "domain hit CN".

For each failing target, answer all three:

1. Did the traffic enter system proxy / PAC?
2. Did the resolved IP enter Clash TUN?
3. If it entered Mihomo, what final action was used: `DIRECT` or proxy group?

Completion criterion: the failure is localized to one layer boundary, not left as
"network abnormal".

### 4. Prefer minimal path fixes

Apply the smallest fix that changes the bad path:

- PAC / system-proxy split for browser-only issues
- `route-exclude-address` or `/32` exclusion only when the site fails and the IP
  should keep the CorpLink/browser path
- rule-order exception before broad `GEOSITE,CN,DIRECT` rules when a CN target
  must still proxy
- runtime verification after any config change

Completion criterion: the proposed fix names the exact file or GUI surface to
change, plus the verification command or file to re-check.

### 5. Deliver the diagnosis in a fixed schema

The final answer must include:

1. origin app
2. PAC / system-proxy verdict
3. TUN verdict
4. Mihomo verdict
5. owning failure layer
6. minimal fix
7. verification proof or explicitly unverified live check

Completion criterion: another agent can pick up your output and continue without
re-deriving the path model.

## Rules

1. Do not assume quitting the GUI exits CorpLink, UURemote, Clash, or platform
   helpers.
2. Do not assume `DIRECT` means "did not pass through Mihomo".
3. Do not assume `PAC DIRECT` means "did not enter TUN".
4. Do not add `/32` exclusions just because an IP maps to `198.18.0.1`.
5. Do not trust repo copies over live runtime files when the task is diagnosis.
6. If sandbox blocks DNS or route observation, say which live check is still
   unverified instead of inventing the result.

## Reference Routing

- Read `REFERENCE.md` for the command set, path map, and interpretation checklist.
- Read `references/platform-mapping.md` when the current incident is clearly
  platform-bound and you need the nearest equivalent check surface.
- Re-read `private/clash/corplink-experience.md` when the issue involves company
  domains, PAC, TUN, or the route snapshot helper.
