## Testing Standards

- Write tests before implementation (TDD) for non-trivial logic
- Minimum 80% coverage on new code
- One assertion per test where possible
- Test public API, not implementation details
- Use realistic fixtures, not mocks for external services where practical
- Run full test suite before push
- CI must pass before merge

## Test Types

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | Framework per language | Single function/class |
| Integration | Docker compose | Service boundaries |
| E2E | Playwright/Cypress | Critical user paths |
