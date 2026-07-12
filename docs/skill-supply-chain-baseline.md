# Skill Supply Chain Baseline

This is the redacted review baseline captured before enabling the bundle-managed
Matt Pocock workflow.

| Surface | Entries |
| --- | ---: |
| Global agent targets | 171 |
| Project `.agents/skills` targets | 33 |

The raw snapshot was written with label `pre-mattpocock-bundle` under the local
`.agent-state/skill-snapshots/` runtime directory. It is intentionally ignored:
it contains machine-specific paths and symlink targets. This report keeps only
the counts needed to review the migration in the public template.

Post-change review should capture another local snapshot and compare it with
the baseline. Expected changes are limited to the approved bundle workflow,
the disabled `superpowers` entries, and the directory/soft-link target format;
unrelated project-target changes require investigation.
