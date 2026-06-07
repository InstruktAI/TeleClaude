---
description: Audit existing tests against the reviewer test-quality lane and write a report.
argument-hint: '[scope]'
---

# Test Suite Audit

## Required reads

- @~/.teleclaude/docs/software-development/procedure/test-suite-audit.md

You are now the Reviewer.

## Purpose

Re-run the reviewer test-quality lane against an existing test scope and write a durable audit report.

## Steps

1. Resolve the audit scope from `$ARGUMENTS`. If none is provided, use the full suite.
2. Execute the `test-suite-audit` procedure against that scope.
3. Write the report using the procedure's report contract.
4. Return the report path and a concise severity summary.

## Discipline

This command is an evaluation entry point, not a repair flow. Do not rewrite tests,
do not broaden scope mid-run, and do not invent a second audit standard. Apply the
reviewer test-quality lane exactly as loaded from the required reads and record
findings with enough specificity that a later fix pass can act on them.
