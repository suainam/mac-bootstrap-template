# AuroraOps Service Role Refactoring Patterns

Practical recipes from the `cliproxyapi` and `singbox` role refactorings.

## 1. Directory Blueprint (`vps.services.<role>`)

```text
roles/<role>/
├── defaults/
│   └── main.yml                  # Public interface and fail-closed defaults
├── meta/
│   └── main.yml                  # Role galaxy metadata
├── handlers/
│   └── main.yml                  # Dual reload/restart handlers (docker & systemd/openrc)
├── tasks/
│   ├── main.yml                  # Entry point with mode dispatch
│   ├── resolve.yml               # singbox_deploy_mode validation and path resolution
│   ├── preflight.yml             # Architecture and kernel safety checks
│   ├── common_prep.yml           # Cryptographic keys, tokens, short IDs
│   ├── configure_common.yml      # Render shared modular configurations (DRY)
│   ├── docker.yml                # Docker container deploy runner
│   ├── native.yml                # OpenRC / systemd native service runner
│   ├── verify.yml                # Entry point for verify tasks
│   ├── verify_docker.yml         # Container health and port probes
│   ├── verify_native.yml         # Native service status and check commands
│   ├── rollback.yml              # Graceful shutdown with persistent data preservation
│   └── rollback_verify.yml       # Post-rollback absence assertions
└── templates/
    ├── *.json.j2 / *.yaml.j2     # Canonical, unified templates (DRY)
```

## 2. TypeSafe Decision Pattern (`typesafe_question`)

Use Jev to validate candidate directory patterns before cutting code:

```json
{
  "state": {
    "role": "vps.services.singbox",
    "modes": ["docker", "native"],
    "templates": ["01_base", "02_outbounds", "03_dns", "04_inbounds", "05_route", "06_wireguard"]
  },
  "questions": {
    "role_structure_pattern": {
      "type": "choice",
      "instructions": "Which directory and task structure best mirrors the proven cliproxyapi unification pattern?",
      "criteria": {
        "cliproxyapi_mirror": "Follow cliproxyapi: tasks/main.yml delegates to resolve.yml, configure_common.yml, then branches to tasks/docker.yml or tasks/native.yml",
        "flat_single_file": "Keep all logic in a single file with when conditionals",
        "separate_roles": "Create two completely separate roles"
      }
    }
  }
}
```

## 3. Userspace Interface Guard Pattern

On lightweight Alpine NAT nodes without real kernel WireGuard interfaces, never allow HTTP inbounds to bind to virtual tunnel IPs:

```jinja2
{% if (singbox_wireguard_system | default(false) | bool) and (singbox_wireguard_http_inbound | default(false) | bool) %}
  "inbounds": [
    {
      "type": "http",
      "tag": "sub-in-wg",
      "listen": "{{ singbox_wireguard_address.split('/')[0] }}",
      "listen_port": {{ singbox_wireguard_http_port | default(10080) }}
    }
  ]
{% endif %}
```

## 4. Residue Cleanup Checklist

- [ ] Delete `docker_apps/tasks/<role>*.yml`
- [ ] Delete `docker_apps/templates/<role>/`
- [ ] Remove `<role>` from `docker_apps_containers_host` lists in inventories
- [ ] Run `rtk grep -rn "<legacy_role_alias>"` to prove zero dangling references
