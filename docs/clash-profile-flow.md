# Clash Profile Flow

This setup has three layers. Keep them separate.

## 1. Source Of Truth

- The server-owned compatible subscription is the source of truth for the
  complete common Mihomo profile: TUN, DNS, process rules, capability groups,
  and routing policy.
- `private/clash/work-mac.yaml` remains the private local fallback and source
  for machine-only overlays. It is not copied over a remote compatible profile.
- `make render-configs` only syncs `work-mac.yaml` when the active profile is
  local. For a remote profile it skips without editing `profiles.yaml` or
  restarting Clash Verge; refresh the subscription through Clash Verge.

## 2. Runtime State

- Clash Verge Rev stores generated profiles under
  `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/`.
- `profiles.yaml` in that directory maps the active `current` uid to its profile
  file (e.g. `LFYEU2DnJ6qB.yaml`).
- Files in that folder are generated runtime state.
- Do not treat them as the source of truth.
- Subscription refresh can rewrite the remote-profile layer, so manual edits
  there are easy to lose.
- Refreshing a Clash subscription does not update `private/clash/work-mac.yaml`;
  it only changes the app-managed runtime profile state.

## 3. Privacy Boundaries

- Public template files must not contain subscription URLs, API keys, tokens,
  usernames, internal hostnames, private IPs, or private notes.
- Put those values in `private/` in the private parent repo.
- Do not keep private working backups under version control in the public
  template.
- Run `make privacy-audit` before publishing anything public.

## Recommended Workflow

1. Deploy common policy from the server and refresh the remote compatible
   subscription in Clash Verge.
2. Keep company-only domains, addresses, and other machine-only settings in
   `private/clash/work-mac.yaml` or the authorized private overlay.
3. Run `make render-configs` only when using the local fallback profile; it
   safely skips a remote active profile.
4. Keep runtime files in `Application Support` out of version control.
