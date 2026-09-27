# App-owned proxy environment

## Leading word

App-owned proxy = the process's own inherited environment, not the shell or
GUI toggle, decides which proxy it actually uses.

## Diagnose: compare process environment, not shell or GUI state

Shell and system proxy settings do not prove which proxy an app or agent CLI
uses. On macOS, inspect the target PID with `ps eww -p <pid>` and check whether
its `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` (including lowercase variants)
point to a closed port. Compare against `private/profiles/<profile>/proxy.env`,
the live listeners, and `networksetup` output. A closed configured proxy port
plus a working active backend identifies a stale process environment rather
than a Mihomo rule or remote-target failure.

## Case: Clash Verge app itself (e.g. WebDAV backups)

Recover by quitting the app, confirming its process and core/listeners stop,
then relaunching it with stale proxy variables removed or corrected. If
graceful quit leaves an orphaned app process, terminate that app PID only
after checking its identity; verify the app starts once and its effective
proxy port responds. Retest the original operation: an unauthenticated
WebDAV request may return HTTP 401, which proves reachability but not backup
success.

Completion criterion: the app environment matches the active backend (or has
no explicit proxy), the listener responds, and the original operation is
re-tested with live evidence.

## Case: an agent CLI with a shared daemon (Codex)

An interactive agent pane can inherit a corrected proxy while its shared
background daemon still holds the old port, because the daemon started once
and kept its own environment. Diagnose the process that actually sends the
model request, not the pane shell or the Clash GUI.

For Codex:

1. Check the daemon's identity with `codex app-server daemon version`, then
   inspect that PID's proxy variable **names and ports** with `ps eww -p <pid>`
   (redact values). Compare against the selected machine profile and the live
   listener.
2. Run `codex doctor --json`. It reports `config.load`/`auth.credentials`
   separately from `network.provider_reachability` (inference HTTPS) and
   `network.websocket_reachability` (Responses WebSocket). A bare TCP connect
   or an unauthenticated HTTP 401 on either endpoint proves only a partial
   path, not that a real request will succeed.
3. `codex --no-daemon` runs the CLI without the shared daemon and is a useful
   differential probe to confirm the daemon (not the model/auth/config) is the
   stale layer. It is not a permanent fix; ordinary `codex` still uses the
   daemon.
4. If the daemon inherited a closed port, start from a shell whose proxy
   variables already match the active backend, then run
   `codex app-server daemon stop` followed by `codex app-server daemon start`.
   Confirm the **new** daemon PID inherited the correct port (same `ps eww`
   check), rerun `codex doctor`, and get a real completed reply from ordinary
   `codex` (not just a tool-server health check) before calling it fixed.
5. If `codex app-server daemon restart` times out, inspect daemon identity and
   state first rather than retrying blindly; the explicit stop-then-start
   sequence is more reliable than the combined restart when the old daemon is
   in a stuck state.

Leave Clash and its TUN running when their listener and target route already
work: restarting the proxy backend cannot update an already-running agent
daemon's captured environment, so it does not fix this failure mode.

## Rules specific to this branch

- Do not assume relaunching only the pane-visible CLI clears a shared daemon's
  stale environment.
- Do not treat a working Context7 MCP call, or an HTTP 401 from an
  unauthenticated probe, as proof the primary agent request succeeded.
- Redact proxy values in any output; compare port numbers and variable names
  only.
