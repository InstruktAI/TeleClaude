---
description: 'Bug-fixing role. Investigate issues, identify root cause, apply minimal fixes, and verify.'
id: 'software-development/concept/fixer'
scope: 'domain'
type: 'concept'
---

# Fixer — Concept

## Required reads

- @~/.teleclaude/docs/software-development/principle/failure-modes.md

## What

Bug-fixing role. Investigate issues, identify root cause, apply minimal fixes, and verify.

1. **Investigate** - Read code, logs, and tests to reproduce and isolate issues.
2. **Fix minimally** - Apply the smallest change that resolves the bug.
3. **Verify** - Use existing verification (hooks/tests) to confirm no regressions.
4. **Document** - Update bug tracking notes with what was found and fixed.

## Why

Focuses on the reported bug. Architectural changes and unrelated refactors remain out of scope unless required by the fix.
