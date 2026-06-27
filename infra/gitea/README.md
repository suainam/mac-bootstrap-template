# Gitea Docker Scaffold

This directory is the starting point for a self-hosted Gitea deployment on a remote bastion or internal server.

## Scope

- Docker Compose only
- No domain name assumed
- IP-based access only
- Git over HTTP on a high port
- Git over SSH on a separate high port
- PostgreSQL for persistence

## Default topology

- Web UI: `http://<server-ip>:13000`
- Git SSH: `ssh://git@<server-ip>:2222/<owner>/<repo>.git`
- Database: `postgres:16`

## Why this shape

- IP-only avoids DNS and certificate work.
- Separate SSH port avoids fighting the host's existing `sshd`.
- PostgreSQL is safer than SQLite once the instance stops being a toy.
- The stack is small enough to copy via `scp` and bring up quickly.

## Files

- `docker-compose.yml` wires Gitea and PostgreSQL.
- `.env.example` holds the IP, ports, secrets, and optional proxy settings.
- `install.sh` copies the scaffold to the remote host.

## Important limits

- `HTTP_PROXY` / `HTTPS_PROXY` help Gitea reach the internet through the freellmapi/mimo path.
- Those env vars do not affect Docker image pulls.
- If the remote server cannot reach public registries, preload the images on a machine with access and `docker load` them on the bastion, or point `GITEA_IMAGE` / `POSTGRES_IMAGE` at an internal mirror.

## First run

1. Copy the files to the remote host.
2. Set `.env` with the real IP and password.
3. Start the stack with `docker compose up -d`.
4. Open the web UI and finish Gitea setup.
5. Create the first admin account.
6. Check that clone URLs show the IP and port you expect.

## Suggested `.env`

```env
GITEA_DOMAIN=10.0.103.217
GITEA_ROOT_URL=http://10.0.103.217:13000/
GITEA_SSH_DOMAIN=10.0.103.217
GITEA_HTTP_PORT=13000
GITEA_SSH_PORT=2222
POSTGRES_PASSWORD=change-me
HTTP_PROXY=http://freellmapi-proxy:7890
HTTPS_PROXY=http://freellmapi-proxy:7890
NO_PROXY=localhost,127.0.0.1,::1,db,gitea
```

## Operations

```bash
docker compose ps
docker compose logs -f gitea
docker compose logs -f db
docker compose down
docker compose pull
docker compose up -d
```

## Notes on outbound access

If the bastion server has no direct outbound network access, plan for one of these before the first `up`:

- host-level Docker proxy / registry mirror
- preloaded image tarballs
- a reachable internal mirror for `GITEA_IMAGE` and `POSTGRES_IMAGE`

If you want the scaffold to attach to a specific existing proxy network later, keep that detail in the private overlay instead of hardcoding it here.
