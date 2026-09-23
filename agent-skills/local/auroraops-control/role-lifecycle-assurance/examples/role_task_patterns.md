# Task Structure Examples for 9-Stage Roles (任务组织实战范例)

以 `vps.system.sysctl` 为例，标准的 Role 目录结构与各阶段任务组织如下：

## 1. 任务文件分布 (Standard File Layout)

```text
roles/<role_name>/
├── defaults/
│   └── main.yml           # 默认变量、基线 fact 路径、受管目标路径定义
├── tasks/
│   ├── main.yml           # 调度入口：判断启用状态，按序引用各阶段
│   ├── preflight.yml      # Stage 1: 只读探测与条件校验
│   ├── apply.yml          # Stage 2 & 4: 固化基线 fact，并执行真实写入与重载
│   ├── verify.yml         # Stage 5 & 9: 运行时断言检查
│   ├── rollback.yml       # Stage 7: 从基线 fact 恢复旧内容与清理本轮生成物
│   └── rollback_verify.yml# Stage 8: 验证旧配置已成功复原
```

---

## 2. 关键阶段任务编写范式 (Snippets)

### A. `defaults/main.yml`（声明基线路径）
```yaml
---
sysctl_fact_path: /etc/ansible/facts.d/sysctl.fact
sysctl_managed_file: /etc/sysctl.d/99-auroraops.conf
```

### B. `tasks/apply.yml`（Stage 2: 固化基线）
```yaml
- name: Ensure facts.d directory exists for baseline
  become: true
  ansible.builtin.file:
    path: /etc/ansible/facts.d
    state: directory
    mode: "0755"

- name: Persist pre-deploy baseline
  become: true
  ansible.builtin.copy:
    dest: "{{ sysctl_fact_path }}"
    mode: "0644"
    content: |
      {{
        {
          "auroraops_managed": true,
          "version": 1,
          "sysctl_managed_file": sysctl_managed_file,
          "pre_deploy_file_exists": current_file_stat.stat.exists | default(false),
          "pre_deploy_file_content": (current_file_raw.content | b64decode) if (current_file_stat.stat.exists | default(false)) else '',
          "pre_deploy_values": current_values
        } | to_nice_json
      }}
  when: not sysctl_fact_stat.stat.exists
```

### C. `tasks/verify.yml`（Stage 5: 严格断言，含环境只读容错）
```yaml
- name: Notice read-only environment
  ansible.builtin.debug:
    msg: "Target environment is read-only. Skipping runtime assertions."
  when: not (proc_writable | default(true) | bool)

- name: Read applied parameters
  become: true
  ansible.builtin.command: "sysctl -n {{ item.key }}"
  loop: "{{ final_params | dict2items }}"
  register: applied_values
  changed_when: false
  when: proc_writable | default(true) | bool

- name: Assert parameters match desired values
  ansible.builtin.assert:
    that:
      - item.item.value | string == item.stdout | trim
    fail_msg: "Value mismatch for {{ item.item.key }}"
  loop: "{{ applied_values.results | default([]) }}"
  when: proc_writable | default(true) | bool
```

### D. `tasks/rollback.yml`（Stage 7: 基线还原）
```yaml
- name: Restore previous file content
  become: true
  ansible.builtin.copy:
    dest: "{{ managed_file }}"
    content: "{{ baseline.pre_deploy_file_content }}"
    mode: "0644"
  when: baseline.pre_deploy_file_exists | bool

- name: Remove file if not present before deploy
  become: true
  ansible.builtin.file:
    path: "{{ managed_file }}"
    state: absent
  when: not (baseline.pre_deploy_file_exists | bool)

- name: Restore pre-deploy runtime values
  become: true
  ansible.builtin.command: "sysctl -w {{ item.key }}={{ item.value | quote }}"
  loop: "{{ (baseline.pre_deploy_values | default({})) | dict2items }}"
  changed_when: false
  when:
    - baseline.runtime_restore_enabled | default(true) | bool
    - (baseline.proc_writable | default(true)) | bool
```

### E. `tasks/rollback_verify.yml`（独立终态断言）

不要只判断 `service_facts` 中是否存在 unit key。systemd 可能继续返回已
删除 unit 的 `not-found` 历史条目；应检查 manager 的明确状态，并同时断言
受保护数据仍在：

```yaml
- name: Query runtime unit load state after rollback
  become: true
  ansible.builtin.systemd:
    name: "{{ item }}"
  loop:
    - example.service
  register: rollback_unit_states
  changed_when: false
  failed_when: false

- name: Assert runtime units are absent
  ansible.builtin.assert:
    that:
      - (item.status | default({})).LoadState | default('not-found') == 'not-found'
  loop: "{{ rollback_unit_states.results }}"
```

### F. 代理服务的实机验收

Ansible `wait_for` 和 `/v1/models` 只证明本地进程可达。对代理后端补充一
次脱敏请求，只记录模型 ID、HTTP 状态和响应字节数，不记录响应正文、Token
或 `Authorization` 头。网站返回上游 `403` 要与本地连接失败分开记录。

---

## 3. 多驱动存储与持久化模式组织范式 (Storage Drivers & Sync Patterns)

在诸如 `cliproxyapi` 等支持文件、数据库（PostgreSQL）、对象存储（S3/R2）多后端且存在运行期双向同步的应用中，生命周期各阶段需遵循以下模式：

### A. 存储模式条件解耦与环境变量分离 (`tasks/docker.yml`)

不要在容器参数中混入不兼容的驱动变量（例如切换到文件/S3模式时残留 `PGSTORE_DSN`，会导致应用继续使用数据库作为权威源覆盖本地文件）：

```yaml
- name: Resolve container environment for selected storage mode
  ansible.builtin.set_fact:
    app_container_env: >-
      {{
        base_env
        | combine(
            s3_env
            if (app_storage_driver == 's3' or app_s3_endpoint | default('') | length > 0)
            else (
              pg_env
              if app_use_postgres | bool
              else {}
            )
          )
      }}
  no_log: true
```

### B. 对象存储双向同步的持久化挂载 (`cdp_volumes`)

当应用具备 S3 本地镜像与双向监听（如 `/CLIProxyAPI/objectstore`）时，宿主机挂载点应自适应切换，将本地持久化缓存对齐到 S3 镜像目录：

```yaml
cdp_volumes: >-
  {{
    [ "/opt/dockers/app/logs:/app/logs" ]
    + (
      [ "/opt/dockers/app/objectstore:/app/objectstore" ]
      if (app_storage_driver == 's3' or app_s3_endpoint | default('') | length > 0)
      else [
        "/opt/dockers/app/config.yaml:/app/config.yaml",
        "/opt/dockers/app/auths:/root/.auths"
      ]
    )
  }}
```

### C. Check 模式与幂等守卫 (`check-mode & idempotence`)

1. **正则替换防止空行穿透**：多行块正则（如 `(?ms)^section:\n.*?(?=^[^ \t#\r\n][^:\r\n]*:\s*$|\Z)`）必须显式排除 `\r\n`，避免遇到段落内空行时提前截断匹配导致非幂等重复变更。
2. **Check 模式跳过主动验证**：验证断言任务（`verify_*.yml`）必须守卫 `when: not ansible_check_mode`，避免在演练预览阶段因未落盘或未启动触发误报中断。
3. **在线刷新凭证保护**：被应用运行期维护、写回的动态凭据（如 OAuth Token JSON），下发时默认应使用 `force: "{{ app_force_overwrite | default(false) | bool }}"`，避免每次部署抹去最新在线刷新状态导致幂等检测抖动。
