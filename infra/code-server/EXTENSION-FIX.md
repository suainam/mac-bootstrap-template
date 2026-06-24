# Extension Compatibility Fixes

## Cline (Claude Dev) Navigator Error

**Error:** `PendingMigrationError: navigator is now a global in nodejs`

**Root cause:** The installed version `saoudrizwan.claude-dev-3.89.2` is incompatible with code-server 1.102.0's Node.js version.

### Fix Option 1: Install Official Cline Extension

The official Cline extension (`saoudrizwan.cline`) is actively maintained and compatible with newer VS Code versions:

```bash
# Remote execution required
docker exec code-server code-server --uninstall-extension saoudrizwan.claude-dev
docker exec code-server code-server --install-extension saoudrizwan.cline
```

Verify:
```bash
docker exec code-server sh -c 'ls -la /root/.local/share/code-server/extensions | grep -i cline'
```

### Fix Option 2: Downgrade to Compatible Version

If you must use `claude-dev`, try an older version:

```bash
docker exec code-server code-server --uninstall-extension saoudrizwan.claude-dev
docker exec code-server code-server --install-extension saoudrizwan.claude-dev@3.85.0
```

### Verification

After installing, reload the code-server window and check browser console:
- The `navigator is now a global` error should disappear
- Cline UI should open without errors

## NODE_TLS_REJECT_UNAUTHORIZED Warning

**Warning:** `Setting NODE_TLS_REJECT_UNAUTHORIZED='0' makes TLS connections insecure`

### Diagnosis

Check if this environment variable is set:

```bash
docker exec code-server sh -c 'env | grep NODE_TLS'
```

If it outputs `NODE_TLS_REJECT_UNAUTHORIZED=0`, find the source:

1. Check remote `.env` file:
   ```bash
   ssh <remote> 'cat <remote-dir>/.env | grep NODE_TLS'
   ```

2. Check if it's in the base image:
   ```bash
   docker run --rm codercom/code-server:latest sh -c 'env | grep NODE_TLS'
   ```

### Fix

If found in `.env`:
```bash
ssh <remote>
cd <remote-dir>
sed -i '/NODE_TLS_REJECT_UNAUTHORIZED/d' .env
docker compose up -d --force-recreate
```

If it's in the base image, override it in `docker-compose.yml`:
```yaml
services:
  code-server:
    environment:
      NODE_TLS_REJECT_UNAUTHORIZED: "1"  # Re-enable TLS verification
```

## Continue YAML Extension Dependency

**Error:** `Failed to register Continue config.yaml schema, YAML extension not installed`

**Fix:** Already applied in previous session:
```bash
docker exec code-server code-server --install-extension redhat.vscode-yaml
```

No further action needed if `redhat.vscode-yaml` is present in extensions directory.

## Continue / Qoder / Lingma Webview TLS Failure

**Error:** `Error loading webview: Could not register service worker ... An SSL certificate error occurred when fetching the script`

### What this error actually means

This is usually **not** an extension-install problem.

In the 2026-06-24 incident, the following were all true at the same time:

- code-server page opened normally over `https://10.0.103.217:59443`
- terminal and file tree worked
- websocket traffic was healthy after the `--trusted-origins` fix
- nginx returned `200` for the webview `service-worker.js`
- system `curl` trusted the regenerated local CA
- Chrome still rejected the page with `net::ERR_CERT_AUTHORITY_INVALID`

That combination means the remaining failure is in the browser certificate trust
path, not in the extension package itself.

### Do not start here

Avoid these as the first response:

- reinstall Continue
- reinstall Qoder
- tweak random nginx websocket headers again
- change code-server auth flags without new evidence

### Verify the layers in order

1. Service worker URL is actually served:

```bash
/usr/bin/curl -I https://10.0.103.217:59443/_static/out/browser/serviceWorker.js
```

2. nginx saw the webview/service-worker request:

```bash
docker logs code-server-nginx --since 5m | grep service-worker.js
```

3. code-server is no longer failing websocket origin validation:

```bash
docker logs code-server --since 5m | grep -E "does not match origin|ManagementConnection|ExtensionHostConnection"
```

If those pass and Chrome still says the site is unsafe, the next step is
certificate trust investigation, not extension reinstall.
