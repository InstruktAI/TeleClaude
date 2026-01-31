---
description: Linting and type-checking rules. Required fixes, import rules, and suppression
  limits.
id: software-development/policy/linting-requirements
scope: domain
type: policy
---

# Linting Requirements — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md

## Rules

1. **Fix all lint violations before commit**
2. **Do not suppress lint errors** unless explicitly approved and documented
3. **All imports at module top level** (no import-outside-toplevel)
4. No unused imports, variables, or arguments
5. Respect configured formatter/linter defaults (do not override project config)

6. **Resolve all type-checker errors before commit**
7. Avoid `Any` or untyped values unless explicitly justified
8. Provide explicit return types for public functions
9. Provide explicit parameter types where inference is ambiguous
10. Use fully-parameterized generics (`list[str]`, `dict[str, int]`)

- Only when required by a third-party limitation or transitional migration
- Must include a concise comment explaining the reason and scope
- Must include a follow-up todo for removal if temporary

**CRITICAL**: Never commit with lint or type-check failures.

- Prefer smallest viable suppression; scope to a single line when unavoidable.
- Suppressions must not hide real defects (unused code, unreachable branches).
- Keep lint configuration centralized; do not add ad hoc per-file overrides.
- Keep lint/tooling versions pinned to project config.

## Rationale

- Linting enforces consistent style and eliminates avoidable defects.
- Type-checking prevents runtime errors and documents intent.

## Scope

- Applies to all languages with configured linters/type-checkers in the repo.

## Enforcement

- Pre-commit hooks and CI block merges on lint/type errors.
- Reviewers must reject unjustified suppressions.

## Exceptions

- Third-party constraints or legacy code may allow scoped suppressions with documented follow-ups.
