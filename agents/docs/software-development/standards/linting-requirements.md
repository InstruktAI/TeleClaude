---
description:
  Linting and type-checking rules. Required fixes, import rules, and suppression
  limits.
id: software-development/standards/linting-requirements
scope: domain
type: policy
---

# Linting & Type-Checking Requirements

## Required reads

- @software-development/standards/code-quality

## Requirements

@~/.teleclaude/docs/software-development/standards/code-quality.md

## Linting Rules (Non-Negotiable)

1. **Fix all lint violations before commit**
2. **Do not suppress lint errors** unless explicitly approved and documented
3. **All imports at module top level** (no import-outside-toplevel)
4. No unused imports, variables, or arguments
5. Respect configured formatter/linter defaults (do not override project config)

## Type-Checking Rules (Non-Negotiable)

1. **Resolve all type-checker errors before commit**
2. Avoid `Any` or untyped values unless explicitly justified
3. Provide explicit return types for public functions
4. Provide explicit parameter types where inference is ambiguous
5. Use fully-parameterized generics (`list[str]`, `dict[str, int]`)

## When a Suppression Is Allowed

- Only when required by a third-party limitation or transitional migration
- Must include a concise comment explaining the reason and scope
- Must include a follow-up todo for removal if temporary

**CRITICAL**: Never commit with lint or type-check failures.
