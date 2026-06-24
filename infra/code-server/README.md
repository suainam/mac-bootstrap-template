# code-server Runbook

This directory is the source of truth for the remote `code-server` container.

Files:

- `docker-compose.yml` wires ports, workspace mounts, extension storage, and AI proxy env vars.
- `Dockerfile` extends `codercom/code-server` with `make`, Docker CLI, and Compose.
- `nginx.conf` configures the current HTTPS reverse proxy and WebSocket forwarding.
- `entrypoint-nginx.sh` generates the self-signed certificate used by the nginx container.
- `Caddyfile` is historical from an earlier proxy attempt and is not the active compose path.
- `install.sh` pushes this directory to the remote host and prefers the live compose working dir when a `code-server` container already exists.

## HTTPS Access

The deployment includes an nginx reverse proxy that provides HTTPS with a self-signed certificate:

- HTTPS: `https://<host>:59443` (default, use this)
- HTTP: `http://<host>:59200` (redirects to HTTPS)

**Why HTTPS?** Browser-based VS Code extensions (Continue, Cline, etc.) require a secure context for webviews and service workers. Without HTTPS, extensions will fail with blank webviews or `about:blank` errors.

**Self-signed certificate warning:** Your browser will show a certificate warning on first access. Click "Advanced" → "Proceed to site" to accept the self-signed cert. This is safe for internal/bastion use.

For webview-based extensions such as Continue, Qoder, Cline, and Tongyi Lingma,
clicking through the browser warning is not enough. Their UI registers a
service worker, and service worker script fetches require a certificate trusted
by the browser/OS trust store.

The nginx entrypoint generates a local CA at `/etc/nginx/ssl/ca.crt` and a
server certificate at `/etc/nginx/ssl/cert.pem`. The server certificate includes
`subjectAltName=IP:<CODE_SERVER_CERT_IP>` and `extendedKeyUsage=serverAuth`.

On macOS, you can import the active CA certificate into the login keychain and
restart Chrome:

```bash
scp "$CODE_SERVER_HOST:/workspace/eda/code-server/data/nginx-ssl/ca.crt" /tmp/code-server-ca.crt
security add-trusted-cert -d -r trustRoot -k "$HOME/Library/Keychains/login.keychain-db" /tmp/code-server-ca.crt
/usr/bin/curl -I https://10.0.103.217:59443
```

As of 2026-06-24, importing the generated CA was sufficient for system tools
such as `/usr/bin/curl`, but it was **not** sufficient to prove Chrome would
trust the same certificate chain on macOS. In that session:

- `/usr/bin/curl -I https://10.0.103.217:59443/_static/out/browser/serviceWorker.js`
  returned `200 OK`
- remote nginx logs showed `Continue.continue` and `tongyi-lingma` webview
  `service-worker.js` requests returning `200`
- Chrome still reported `net::ERR_CERT_AUTHORITY_INVALID`, which then surfaced
  in code-server as `An SSL certificate error occurred when fetching the script`

Treat the generated local CA as a **best-effort development aid**, not as a
guaranteed Chrome-compatible fix. If Chrome still reports the service-worker TLS
error after `chrome://restart` and clearing site data, stop debugging the
extension package and switch to one of these paths:

1. serve code-server with a certificate Chrome already trusts
2. use an internal PKI / enterprise-trusted CA
3. continue investigating Chrome trust-store behavior on that Mac

To use a trusted certificate instead:
1. Obtain a certificate from Let's Encrypt or your internal CA
2. Mount the cert/key into the `nginx` container
3. Update `nginx.conf` to use the mounted certificate paths

Current nginx proxy details:

- Preserve the external host and port with `proxy_set_header Host $http_host`.
- Keep WebSocket upgrade headers: `Upgrade`, `Connection upgrade`, and `proxy_http_version 1.1`.
- Do not reintroduce `X-Forwarded-Host $host` or `X-Forwarded-Port $server_port`; those lost the external port or replaced it with container port `443` during the 2026-06-23 reverse-proxy debugging.
- Keep `CODE_SERVER_TRUSTED_ORIGINS` aligned to the browser HTTPS entrypoint, for example `10.0.103.217:59443`. In this deployment code-server receives `Host: 10.0.103.217` while the browser sends `Origin: https://10.0.103.217:59443`, so code-server must explicitly trust the external origin.
- Do not use `--proxy-domain` for the main code-server URL. It is for code-server's port proxy feature and can corrupt the generated workbench authority when used as the primary access host.

## AI proxy wiring

The compose file injects OpenAI-compatible variables for editor extensions:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL=http://host.docker.internal:15721`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL=http://host.docker.internal:15721`

This assumes the remote host already has an SSH reverse tunnel or local proxy
listening on `15721`. When AI features fail but the extension still loads, verify
the tunnel before blaming the editor UI.

## Expected runtime model

- The compose service runs with `user: "0"`, so the effective runtime user is `root`.
- `code-server` settings and extensions therefore live under `/root/.local/share/code-server`, not `/home/coder/.local/share/code-server`.
- The integrated terminal shell is `/bin/bash` for both `root` and `coder` in the base image.
- Workspace files mount to `/root/dev`.
- The default workspace host path is `/workspace`, so `/workspace/eda` appears as `/root/dev/eda` in the browser.
- User-visible code-server state is bind-mounted under this deployment directory by default:
  - `./data/config` -> `/root/.config`
  - `./data/code-server` -> `/root/.local/share/code-server`
  - `./data/nginx-ssl` -> `/etc/nginx/ssl`
- The compose service overrides the base image entrypoint with `entrypoint: ["/usr/bin/entrypoint.sh"]`. Keep this override: without it, the base image entrypoint included default `--bind-addr ... .` arguments and compose appended another command, producing duplicate code-server arguments.

Practical consequence:

- If Continue or another extension "opens with no reaction", inspect `/root/.local/share/code-server/extensions` and `docker logs code-server` before assuming the extension is missing.
- If `dev` is empty in the Explorer, check `docker compose config` and confirm the `/root/dev` source points to your `CODE_SERVER_WORKSPACE_DIR`.

## Persisting browser-managed settings

The current compose file intentionally uses bind mounts for code-server state so settings, extensions, and user data are visible from the browser under `/root/dev/eda/code-server/data`.

When migrating an older deployment that used named volumes, copy existing data before restarting with the bind-mount compose:

```bash
cd /workspace/eda/code-server
mkdir -p data/config data/code-server
docker run --rm \
  -v code-server_code-server-config:/from:ro \
  -v "$PWD/data/config:/to" \
  alpine sh -lc 'cp -a /from/. /to/ 2>/dev/null || true'
docker run --rm \
  -v code-server_code-server-extensions:/from:ro \
  -v "$PWD/data/code-server:/to" \
  alpine sh -lc 'cp -a /from/. /to/ 2>/dev/null || true'
docker compose up -d --build
```

Do not commit `data/`; it can contain extension cache, local settings, auth state, and other machine-specific files.

## Deployment flow

Push the local config:

```bash
cd template/infra/code-server
./install.sh
```

`install.sh` behavior:

- Requires a live `ssh -O check "$CODE_SERVER_HOST"` ControlMaster session.
- If `CODE_SERVER_DIR` is unset, it first asks the running `code-server` container for `com.docker.compose.project.working_dir`.
- Falls back to `/srv/code-server` only when no running container exposes that label.

After push, rebuild remotely:

```bash
ssh "$CODE_SERVER_HOST" 'cd "$CODE_SERVER_DIR" && docker compose up -d --build'
```

If your bastion blocks non-interactive remote commands, keep an authenticated
remote shell or tmux pane open and run the rebuild there instead.

## Rebuild pitfalls

### 1. Do not hardcode the Debian codename

The base image currently reports Debian 13 (`trixie`). If the Docker APT source is pinned to `bookworm`, rebuilds can hang or fail while fetching Docker packages.

The Dockerfile therefore derives the source from `/etc/os-release`:

```bash
. /etc/os-release
echo "... ${VERSION_CODENAME} stable"
```

### 2. Long rebuilds can outlive an SSH session

If the bastion or ControlMaster session drops mid-build, the remote container may stay on the old image even though the Dockerfile was already patched.

Use a log-backed background rebuild when the connection is flaky:

```bash
cd "$CODE_SERVER_DIR"
nohup sh -lc 'docker compose up -d --build' >/tmp/code-server-build.log 2>&1 </dev/null &
tail -f /tmp/code-server-build.log
```

### 3. `code-server` can be healthy while extensions are still wrong

Always separate these checks:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}'
docker exec code-server sh -lc 'command -v make && docker compose version'
docker logs --tail 120 code-server
```

Container health only proves the editor booted. It does not prove extensions, webviews, or AI endpoints are usable.

### 4. WebSocket 1006 from origin mismatch

On 2026-06-24, browser testing with Playwright/CDP reproduced WebSocket failures under:

```text
The workbench failed to connect to the server (Error: WebSocket close with status code 1006)
ENOPRO: No file system provider found for resource 'vscode-remote://10.0.103.217:59443/root'
```

Confirmed evidence:

- Login succeeded and the workbench rendered, so this was not a password or basic HTTP routing failure.
- Browser DevTools showed repeated WebSocket handshakes to `/stable-...` returning `403`.
- code-server trace logs showed the exact block reason: `host "10.0.103.217" does not match origin "10.0.103.217:59443"`.
- The 403 came from code-server's `ensureOrigin`, before the VS Code WebSocket protocol handshake.
- `--trusted-origins 10.0.103.217:59443` fixed the origin check. After restart, DevTools showed WebSocket `101 Switching Protocols` and Explorer listed `/root`.

Useful verification commands:

```bash
docker exec code-server sh -lc 'tr "\0" " " </proc/1/cmdline; echo'
docker exec code-server sh -lc 'code-server --help | grep -A3 -B3 -i trusted'
docker exec code-server sh -lc 'grep -n "ensureOrigin\|trusted-origins\|authenticateOrigin" /usr/lib/code-server/out/node/http.js | sed -n "1,120p"'
docker exec code-server-nginx sh -lc 'nginx -T 2>/dev/null | grep -nE "proxy_set_header (Host|X-Forwarded|Forwarded)|listen|proxy_pass"'
docker logs code-server --since 5m | grep -E "does not match origin|Forbidden|ManagementConnection|ExtensionHostConnection"
```

### 5. Chrome webview TLS can fail even after the local CA is imported

On 2026-06-24, the deployment reached this state simultaneously:

- browser page, Explorer, and terminal loaded
- websocket handshakes succeeded (`101 Switching Protocols`)
- nginx served webview `service-worker.js` with `200`
- system `curl` trusted the regenerated CA
- Chrome still showed the site as insecure and webviews failed with
  `ERR_CERT_AUTHORITY_INVALID`

That means these symptoms are **not** enough to conclude the extension itself
is broken:

- Continue sidebar opens but webview fails to render
- `Error loading webview: Could not register service worker`
- Chrome still shows the certificate as unsafe

When this happens, do not start with extension reinstall. First separate the
layers:

```bash
/usr/bin/curl -I https://10.0.103.217:59443/_static/out/browser/serviceWorker.js
docker logs code-server-nginx --since 5m | grep service-worker.js
docker logs code-server --since 5m | grep -E "ManagementConnection|ExtensionHostConnection|does not match origin"
```

If those pass while Chrome still rejects the page, the remaining problem is the
browser trust path, not code-server routing.

## Extension triage

Recommended checks for "installed but cannot open":

```bash
docker exec code-server sh -lc 'getent passwd root; getent passwd coder'
docker exec code-server sh -lc 'ls -la /root/.local/share/code-server/extensions'
docker exec code-server sh -lc 'ls -la /root/.local/share/code-server/User'
docker logs --tail 200 code-server
```

Known facts from this environment:

- Continue was installed under `/root/.local/share/code-server/extensions/continue.continue-...`.
- Reloading the window alone was not enough to prove the extension UI path worked.

## ODPS export dependency

The `auto_display` export path depended on two workspace scripts:

- `template/workspace/scripts/odps-export`
- `template/workspace/scripts/odps-export-runner.py`

If only the shell wrapper exists on the remote host, `make export` fails with a missing runner error. Keep the pair deployed together.
