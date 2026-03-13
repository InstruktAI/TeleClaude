# Input: lint-baseline-fix

## Context

`make lint` fails on the codebase due to pre-existing type checker errors that existed before
the `rlf-core-infra` structural decomposition task. These failures are not introduced by recent
work — they represent accumulated technical debt in the type checking configuration.

## Evidence

- **Mypy:** 5937 errors across ~272 files. Root cause: `[tool.mypy]` configuration uses
  `disallow_any_expr = true` with `strict = true` — maximum strictness that was already
  producing thousands of errors on `origin/main`.
- **Pyright:** 73 errors across 24 files (18 from main merge, ~6 from cross-mixin attr-defined
  patterns in recently decomposed submodules).
- **Ruff:** PASS — no issues.
- **Guardrails:** PASS — no issues.

## Goal

Restore `make lint` to a passing state without silently degrading code quality. Specifically:

1. Fix or suppress the mypy baseline — either:
   - Add per-module `[[tool.mypy.overrides]]` entries to scope down errors to modules that
     genuinely have Any-type issues, OR
   - Reduce `disallow_any_expr` strictness in `pyproject.toml` (if the team agrees this
     config was accidentally set too strict)
2. Fix pyright errors — address the ~73 pre-existing pyright failures:
   - Cross-mixin `attr-defined` patterns (use `if TYPE_CHECKING:` stubs where needed)
   - Any remaining pyright failures from the `origin/main` merge baseline

## Constraint

- Do not change runtime behavior.
- Do not suppress errors globally without review — use targeted overrides or targeted type fixes.
- Prefer fixing errors over suppressing them where the fix is straightforward.
