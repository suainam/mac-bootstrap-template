# Clash Profile Flow

This setup has three different layers. Keep them separate.

## 1. Source Of Truth

- `private/clash/work-mac.yaml` is the private machine-specific source of truth
  for proxy rules, DNS, local domains, and subscription-specific tweaks on this
  Mac.
- `make render-configs` syncs `work-mac.yaml` directly to the active Clash Verge
  local profile (identified by `profiles.yaml` `current` field) and restarts the
  app to force a mihomo reload.

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

1. Edit `private/clash/work-mac.yaml` for machine-specific behavior.
2. Run `make render-configs`.
3. The script syncs to the active local profile and restarts Clash Verge.
4. Keep runtime files in `Application Support` out of version control.
