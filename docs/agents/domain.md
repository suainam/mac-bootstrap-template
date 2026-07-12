# Domain docs

This repository uses a single public context:

- Read `CONTEXT.md` before non-trivial work.
- Read relevant documents under `docs/` before changing a specialized subsystem.
- Keep reusable behavior and defaults in the template.
- Keep private machine configuration in the parent repository's private overlay;
  do not copy it into this repository.
- Use the registry, quarantine, distributor, and reconcile vocabulary for Agent
  Skill work. Runtime directories are generated views, not authority.
