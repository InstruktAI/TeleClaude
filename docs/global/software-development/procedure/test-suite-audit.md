---
description: 'Re-run the reviewer test-quality lane against existing tests and write a durable audit report.'
visibility: 'public'
---

# Test Suite Audit — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review-build.md

## Goal

Reassess existing tests against the reviewer test-quality lane and record durable findings.
This procedure evaluates tests; it does not rewrite them.

## Preconditions

- Audit scope is defined: full suite, subtree, or explicit file set.
- The current repository contains the tests being audited.
- `reports/test-suite-audit/` is writable in the current repository.

## Steps

1. Define the audit scope and the report slug for this run.
2. Read the tests in scope one by one.
3. Apply only the `Test coverage check` lane from the Review procedure to each test.
4. For every non-compliant test, record the severity, violated rule, reason the test is weak, and recommended action.
5. Group repeated patterns into hotspots so the report is actionable at suite level instead of only as isolated findings.
6. Write the report to `reports/test-suite-audit/`.
7. Stop. Do not rewrite, delete, or fix tests in this procedure.

## Outputs

- One audit report under `reports/test-suite-audit/`.
- Severity-ordered findings for weak or non-compliant tests.
- Hotspot summary by folder, pattern, or repeated rule violation.

### Report format

- Path: `reports/test-suite-audit/{YYYY-MM-DD}_{scope-slug}.md`
- Required sections: `Scope`, `Summary`, `Findings`, `Hotspots`, `Follow-up`

## Recovery

- If scope is too large for one pass, split by subtree or file set and continue in multiple reports.
- If a test's protected behavior cannot be determined, record that as a finding instead of guessing.
