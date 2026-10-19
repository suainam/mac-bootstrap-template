## Testing Standards

- Write tests before implementation (TDD) for non-trivial logic
- Minimum 80% coverage on new code
- One assertion per test where possible
- Test public API, not implementation details
- Use realistic fixtures, not mocks for external services where practical
- Run full test suite before push
- CI must pass before merge

## Verify the Verification

Green tests prove execution, not detection. For every invariant that a wrong
change could silently break, inject one fault and confirm the suite turns red:

1. Pick the test that owns the invariant.
2. Break the guarded behavior only (flip a cap, drop a guard, invert a
   condition); do not touch the test.
3. Rerun that test. It MUST fail.
4. Restore the code and confirm it passes again.

Red-then-green is evidence that the test detects this fault; it is not proof
that the suite is complete. Record the injected fault and the observed failure
in the completion report. Do not add a mutation-testing dependency for this;
one hand-injected fault per critical invariant is enough.

## Test Types

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | Framework per language | Single function/class |
| Integration | Docker compose | Service boundaries |
| E2E | Playwright/Cypress | Critical user paths |
