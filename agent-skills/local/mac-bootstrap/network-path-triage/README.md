# Network Path Triage

Cross-platform network diagnosis skill.

Purpose:

- identify which layer owns a failure path
- keep fixes minimal and verifiable
- separate reusable method from machine-specific samples

What is generic:

- path-first diagnosis method
- fixed delivery schema
- route helper script interface
- platform branch model: macOS host / Windows host / WSL guest

What is repo-specific:

- `private/clash/work-mac.yaml`
- `private/clash/corplink-experience.md`
- the current Clash Verge runtime paths in the Mac examples
- the sample company hosts file

When to use:

- enterprise access works partially and one path is abnormal
- PAC / TUN / DNS / Mihomo / helper-process ownership is unclear
- browser, CLI, Windows host, and WSL guest disagree about reachability

When not to use:

- plain ISP outage with no proxy / enterprise / route split
- application-layer bugs already proven unrelated to path ownership

Primary files:

- `SKILL.md` — process
- `REFERENCE.md` — commands and interpretation
- `references/platform-mapping.md` — equivalent checks by platform
- `scripts/check-routes.sh` — sample route helper
- `examples/company-hosts.sample.txt` — sample input only
