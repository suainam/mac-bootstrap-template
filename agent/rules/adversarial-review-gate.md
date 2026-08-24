# Adversarial Review & Solidification Patterns

These patterns guide multi-agent collaboration, advisory findings, skepticism, and code review. Priority: supplementary to the 12 Core Operating Rules.

## Core Principle

Every confirmed review finding or defect resolves through paired implementation and automated verification.

---

# Review & Solidification Lifecycle

## 1. Assert First (Reproduce Before Fix)
Express the reviewed flaw, edge case, or drift as an executable assertion that fails on the defect before changing implementation code.

Example:
```typescript
// Add a targeted test case capturing the review edge case
test('rejects callback with invalid signature (fail-closed)', () => {
  const result = verifier.verify({ signature: 'tampered' });
  expect(result.allowed).toBe(false);
  expect(result.statusCode).toBe(401);
});
```

## 2. Implement & Pass
Update the implementation or configuration until both the new assertion and the full test suite pass cleanly.

Example:
```bash
bun test tests/callback_verifier.test.ts  # New assertion turns green
bun test                                 # Full suite remains green
```

## 3. Codify for Permanent Regression Defense
Include the new assertion in the standard test runner or verification target so all future runs inherit the check.

Example:
```bash
# Verify via the project's canonical gate
bun test
bun run typecheck
```

## 4. Document Synchronization
Update authority documents (`CONTEXT.md`, `README.md`, `docs/ARCHITECTURE.md`) in the same commit whenever review changes architecture, security boundaries, or operational contracts.

Example:
```bash
# Keep code, tests, and authority metrics aligned in one commit
git add src/ tests/ README.md docs/ARCHITECTURE.md
git commit -m "fix(auth): enforce fail-closed signature verification"
```

---

# Clean Worktree & Closeout Patterns

## 1. Worktree Placement
Create feature worktrees inside the repository under `.worktrees/<name>`, keeping `.worktrees/` in `.gitignore`.

Example:
```bash
git worktree add .worktrees/feat-auth -b feat/auth
```

## 2. Closeout Lifecycle
Clean up branches and worktrees in a single sequence once a PR merges.

Example:
```bash
git push origin --delete <branch_name>  # Remote branch cleanup
git worktree remove .worktrees/<name>  # Local worktree cleanup
git branch -d <branch_name>            # Local branch cleanup
git fetch --prune origin                # Prune dead references
```

## 3. Issue Linkage
Link PRs to their tracking issues to close them automatically on merge.

Example:
```markdown
## Summary
Implement WeCom cryptographic callback verifier.

Closes #19
```

## 4. Metric Synchronization
Keep document metrics in sync with actual test suite outputs within the same commit.

Example:
```bash
# Extract numbers from real runner output and update README/ARCHITECTURE
bun test -> "80 pass, 3262 expects" -> README.md
```

## 5. Clean State Verification
Verify zero-residue workspace status before concluding a session.

Example:
```bash
git branch -a       # main only
git worktree list   # repository root only
git status --short  # clean working tree
```
