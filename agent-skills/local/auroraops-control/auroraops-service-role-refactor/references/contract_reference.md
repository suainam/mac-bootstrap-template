# Lifecycle & Seam Contract Reference

This reference defines the strict contract requirements for refactored AuroraOps service roles.

## 1. Mode Dispatch Contract (`tasks/resolve.yml`)

Every unified role must implement fail-closed deployment mode resolution:

```yaml
- name: Resolve role deployment mode
  ansible.builtin.set_fact:
    service_effective_mode: >-
      {{
        service_deploy_mode
        | default(
            'native'
            if (ansible_facts.distribution | default('') == 'Alpine' or (ansible_memtotal_mb | default(1024)) < 512)
            else 'docker'
          )
        | lower
      }}

- name: Validate role deployment mode
  ansible.builtin.assert:
    that:
      - service_effective_mode in ['native', 'docker']
    fail_msg: "Invalid deployment mode '{{ service_effective_mode }}'. Must be 'native' or 'docker'."
```

## 2. Test Seams

1. **Jinja2 Rendering Seam**:
   - Render server-side template with `jinja2.StrictUndefined`.
   - Assert structured dictionary keys (`yaml.safe_load` / `json.loads`).
2. **OpenRC / Systemd Unit Contract**:
   - Verify environment file paths and working directory arguments.
   - Assert no Docker commands called on Alpine native nodes.
3. **Fail-Closed Gate Seam**:
   - Test that omitting required keys raises explicit failure rather than silent fallback defaults.
