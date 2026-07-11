# DevSpace Local

Run DevSpace locally against `~/work/config/mac-bootstrap` as an MCP sidecar.
The same runtime config supports foreground debugging and user-level launchd
background services.

## Files

- Example config: `template/agent/devspace.runtime.example.jsonc`
- Real config: `private/agent/devspace.runtime.jsonc`
- Private home mirror config: `private/agent/devspace.home.config.json`
- Private home mirror auth: `private/agent/devspace.home.auth.json`
- Entrypoint: `template/scripts/devspace-local.sh`
- Logs: `private/agent/logs/devspace/`
- Cloudflare Tunnel token: `exposure.cloudflare_tunnel_token` in the private
  config only

`private/agent/devspace.runtime.jsonc` is the only real runtime config. The
example file is documentation and shape reference only.

## Home Mirror

- `private/agent/devspace.home.config.json` and
  `private/agent/devspace.home.auth.json` are the durable authoritative copies.
- `~/.devspace/config.json` and `~/.devspace/auth.json` are runtime mirrors
  used by upstream DevSpace tooling.
- `devspace.home.auth.json`, `devspace.runtime.jsonc`, and materialized runtime
  files are kept at mode `0600` by the push/pull workflow.

Normal workflow:

1. edit `private/agent/devspace.home.*.json`
2. run `make devspace-home-push`
3. verify health

Exceptional workflow:

1. make an intentional upstream change with DevSpace tooling
2. run `make devspace-home-pull`
3. review and commit the private mirror change

`home-push` validates the private mirror, creates
`private/agent/backups/devspace-home/<timestamp>/`, verifies health, and rolls
back on failure.

## Command Flow

Review the effective config first:

```bash
template/scripts/devspace-local.sh print-config
```

Validate config, roots, host/port, and required binaries:

```bash
template/scripts/devspace-local.sh check
```

If `check` reports that DevSpace is not initialized, complete the one-time
interactive setup first:

```bash
devspace init
```

For first pass with Cloudflare's temporary URL:

```bash
cloudflared tunnel --url http://127.0.0.1:7676
```

Use the printed `https://...trycloudflare.com` origin as DevSpace's public base
URL. Do not include `/mcp`. For a hosted Cloudflare domain, point a named tunnel
at `http://127.0.0.1:7676`, then set `exposure.public_base_url` in
`private/agent/devspace.runtime.jsonc`.

Install missing dependencies without starting the service:

```bash
template/scripts/devspace-local.sh install
```

Start DevSpace in the foreground:

```bash
template/scripts/devspace-local.sh run
```

Probe the local service and classify failures:

```bash
template/scripts/devspace-local.sh doctor
```

Run the configured Cloudflare Tunnel in the foreground:

```bash
template/scripts/devspace-local.sh tunnel-run
```

Push the private home mirror into `~/.devspace/`:

```bash
make devspace-home-push
```

Pull the current `~/.devspace/` runtime files back into `private/agent/`:

```bash
make devspace-home-pull
```

## Background LaunchAgents

Install and start the local DevSpace service plus the Cloudflare Tunnel service:

```bash
make devspace-install-agent
```

Check launchd state, local `/mcp` health, and the configured public MCP URL:

```bash
make devspace-status
```

Tail recent service logs:

```bash
make devspace-logs
```

Restart both services:

```bash
make devspace-restart
```

Stop both services and remove only the installed plist files:

```bash
make devspace-unload-agent
```

The two LaunchAgent labels are:

- `io.local.mac-bootstrap.devspace`
- `io.local.mac-bootstrap.devspace-tunnel`

The tunnel token stays only in `private/agent/devspace.runtime.jsonc`. Public
launchd templates and installed logs should only contain redacted operational
messages.

## Web UI Reference

If service health is normal but the MCP client does not prompt for approval, use
the upstream walkthrough for the browser-side flow:

- Gitee reference: `DevSpace_macOS部署教程`
- ChatGPT app creation section:
  `https://gitee.com/tanlinhai/llm-knowledge-base/tree/master/90_AI%E5%8D%8F%E4%BD%9C%E4%B8%8E%E7%BB%B4%E6%8A%A4/%E5%B7%A5%E5%85%B7%E9%85%8D%E7%BD%AE/DevSpace_macOS%E9%83%A8%E7%BD%B2%E6%95%99%E7%A8%8B#4-chatgpt-%E4%B8%AD%E5%88%9B%E5%BB%BA-devspace-%E5%BA%94%E7%94%A8`

Use that page together with this local runbook:

- This repo owns the local server, Cloudflare Tunnel, LaunchAgents, and MCP URL
  distribution.
- The Gitee page is the reference for browser-side app creation and approval
  flow inside ChatGPT.
- For Codex CLI specifically, keep DevSpace disabled in normal sessions. Run
  `codex-mcp devspace mcp login devspace` once to authorize, then use
  `codex-mcp devspace` for on-demand sessions.
- The DevSpace approval page asks for the Owner password, which is the
  `ownerToken` stored in `~/.devspace/auth.json`.

When troubleshooting, check the layers in this order:

1. `make devspace-status`
2. `curl -sS -o /dev/null -w '%{http_code}\n' https://devspace.suainam.eu.org/mcp`
3. run `codex-mcp devspace mcp login devspace` for Codex, or the equivalent
   login flow in another MCP client
4. start a new `codex-mcp devspace` session after approval
5. compare the browser-side steps with the Gitee walkthrough above

## Local Verification

Confirm the configured port is listening:

```bash
lsof -nP -iTCP:7676 -sTCP:LISTEN
```

Confirm the local `/mcp` endpoint responds:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7676/mcp
```

## Failure Notes

- `check` should fail on config errors, missing roots, or missing binaries.
- `check` should also fail if `~/.devspace/config.json` or `~/.devspace/auth.json`
  is missing and tell you to run `devspace init`.
- `install` should only install dependencies; it should not start DevSpace.
- `run` should fail if port `7676` is already in use; it should not auto-kill
  another process.
- `doctor` should point to `private/agent/logs/devspace/` when runtime health
  checks fail.
- LaunchAgent health treats local `/mcp` HTTP `200`, `400`, `401`, or `405` as
  service-ready; OAuth-protected `401` is expected for the current setup.
