# Adversarial Review & Solidification Gate

These rules govern multi-agent collaboration, advisory findings, skepticism, and cross-model code review. Priority: supplementary to the 12 Core Operating Rules.

## Core Principle

A review finding or bug report is NOT resolved until both the implementation fix AND an automated regression gate are verified in place.

## 3-Step Solidification Lifecycle

1. **Assert First (Fail Before Fix)**:
   Convert the reviewed flaw, edge case, or drift into an executable assertion (test case, audit check, or lint rule) that fails on the defect before applying code changes.
2. **Fix & Verify**:
   Modify implementation or configuration until the newly added assertion and the entire test suite pass cleanly.
3. **Codify for Reuse**:
   Incorporate the assertion into the project's permanent verification chain (`make check`, `pytest`, `parent-privacy-audit`, or custom audit scripts). Future agent runs must inherit regression defense automatically.

## Negative Redlines

- ❌ **No Oral Fixes**: Never declare an issue "fixed" merely in chat without checking in an automated test, reproducible script, or audit gate.
- ❌ **No Weakened Assertions**: Never delete existing tests, skip checks, or relax safety boundaries just to make a gate turn green.
- ❌ **No Ghost Audits**: An automated audit script must genuinely execute assertions (e.g. diffing content, checking line limits); never report simulated "all clear" for unverified claims.
- ❌ **Sync Authority Documents**: When a review changes architecture, security boundaries, or operational contracts, update the Single Source of Truth (`CONTEXT.md` / `README.md`) in the same change set.
