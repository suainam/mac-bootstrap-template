# Clash Profile Flow

This setup has three different layers. Keep them separate.

## 1. Source Of Truth

- `template/proxy/clash/Merge.yaml` is the checked-in public working default.
- `template/proxy/clash/Merge.yaml.template` is the lower-level fallback seed.
- `private/clash/Merge.yaml` is the private override, and is the best place for
  machine-specific proxy rules, DNS, local domains, and subscription-specific
  tweaks.
- `make render-configs` copies the best available source into the rendered
  working tree, and automatically syncs it directly to the active Clash Verge profiles folder.

## 2. Runtime State

- Clash Verge Rev stores generated profiles under
  `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/`.
- Files in that folder are generated runtime state.
- Do not treat them as the source of truth.
- Subscription refresh can rewrite the remote-profile layer, so manual edits
  there are easy to lose.
- Refreshing a Clash subscription does not update `template/proxy/clash/Merge.yaml`
  or `private/clash/Merge.yaml`; it only changes the app-managed runtime
  profile state.

## 3. Privacy Boundaries

- Public template files must not contain subscription URLs, API keys, tokens,
  usernames, internal hostnames, private IPs, or private notes.
- Put those values in `private/` in the private parent repo.
- Run `make privacy-audit` before publishing anything public.

## Recommended Workflow

1. Edit `private/clash/Merge.yaml` for machine-specific behavior.
2. Edit `template/proxy/clash/Merge.yaml` only when changing public defaults.
3. Run `make render-configs`.
4. Reload or reselect the profile in Clash Verge Rev.
5. Keep runtime files in `Application Support` out of version control.
