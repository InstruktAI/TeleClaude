# Enforce Code Quality Standards via Linting — Idea

**Status:** Actionable Finding
**Memory Sources:** IDs 3, 22
**Created:** 2026-02-19

## Problem

Two persistent friction points around code and documentation quality:

- **ID 3:** Module docstrings are frequently inadequate (one-liners instead of substantive descriptions)
- **ID 22:** Artifacts describe transitional state instead of target state ("not yet implemented", "legacy", etc.)

Both are recurring patterns that require manual catch-and-correct cycles.

## Insight

These aren't one-off oversights—they're patterns that keep resurfacing, which suggests:

1. The standard isn't automated/enforced
2. Agents know the standard but don't reliably apply it
3. Manual review catches them too late in the process

The solution is automation. Linting rules can catch both patterns before code is committed.

## Recommendation

1. **Module docstring enforcement:** Add a linter rule (flake8 plugin or similar) that:
   - Fails if any module lacks a docstring
   - Fails if docstring is one-liner
   - Checks for required sections: purpose, inputs, outputs, integration
   - Exempts test files, auto-generated code

2. **Target-state validation:** Add a doc linter that:
   - Flags phrases like "not yet", "legacy", "will be", "to be migrated" in doc artifacts
   - Enforces present/future tense for intended state
   - Exempts decision records and historical notes

3. **Integration:** Wire into pre-commit hooks so violations are caught locally before push.

## Follow-up

- Audit existing code for violations to establish baseline
- Configure linters with exceptions list
- Update CI to enforce on all PRs
- Document the standards in the linting rules themselves for agent reference
