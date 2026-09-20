## RTK Command Execution & Diagnostics

### RTK Design

RTK wraps common commands for:
- **Usage tracking**: Records command execution in RTK logs
- **Readability**: Filters verbose output for terminal display
- **Completeness**: Preserves full output in `artifact://` URLs

### When to Use RTK

**Prefer RTK for**:
- High-volume human-readable commands: `git diff`, `git log`, `git status`, test runners, `make` targets, log files
- Commands where filtered summary + drill-down is sufficient

**Avoid RTK for**:
- Control-flow probes where exact stdout/exit status determines next action: `test`, `which`, `command -v`, `printenv`, `pgrep`, HTTP status checks
- Rewrite commands: `rtk rewrite` may transform content; verify afterward

### Diagnostic Pattern

When RTK output appears truncated or incomplete:

1. **Check for artifact link** in RTK output footer:
   ```
   Read artifact://123 for full output
   ```

2. **Read the artifact** instead of re-running raw commands:
   ```
   read artifact://123
   ```

3. **Filter artifact content** with the repository search tool:
   ```
   rtk cat large-file.log  # truncated display, but leaves artifact://N
   read artifact://N       # read full content
   grep 'error|fail' artifact://N
   ```

4. **Combine RTK + targeted search** when only selected evidence is needed:
   ```
   rtk cat /path/to/log | grep -E 'fail|error|success.*false'
   ```

### Common Mistakes

❌ **Wrong**: Assume RTK truncation means data loss
```bash
# Seeing truncated RTK output, then bypassing RTK entirely
tail -1000 /var/log/service.log | grep error
```

✅ **Right**: Use RTK's artifact mechanism
```bash
rtk cat /var/log/service.log  # may truncate, leaves artifact://N
read artifact://N             # read full content
```

❌ **Wrong**: Use RTK for control-flow probes
```bash
if rtk run -c 'which python3'; then  # exit code may be wrapped
  ...
fi
```

✅ **Right**: Use raw commands for control flow
```bash
if command -v python3 >/dev/null 2>&1; then
  ...
fi
```

### Verification Commands

For probes that must return exact values without transformation:
- File existence: `test -f path` or `[ -f path ]`
- Command availability: `command -v cmd` or `which cmd`
- Environment vars: inspect only masked values or key presence; never print secret values
- Process checks: `pgrep -f pattern`
- Exit status: capture raw command exit code

These should run raw or via `rtk run -c '...'` only when usage tracking is required AND you verify the exit status is preserved.
