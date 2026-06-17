# code-server Runbook

This directory is the source of truth for the remote `code-server` container.

Files:

- `docker-compose.yml` wires ports, workspace mounts, extension storage, and AI proxy env vars.
- `Dockerfile` extends `codercom/code-server` with `make`, Docker CLI, and Compose.
- `install.sh` pushes this directory to the remote host and prefers the live compose working dir when a `code-server` container already exists.

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

Practical consequence:

- If Continue or another extension "opens with no reaction", inspect `/root/.local/share/code-server/extensions` and `docker logs code-server` before assuming the extension is missing.

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
