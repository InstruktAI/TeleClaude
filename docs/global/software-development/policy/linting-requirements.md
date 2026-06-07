---
description: 'Linting and type-checking rules. Required fixes, import rules, and suppression limits.'
id: 'software-development/policy/linting-requirements'
scope: 'domain'
type: 'policy'
visibility: 'public'
---

# Linting Requirements — Policy

## Rules

0. **Checks block; there is no passing warning tier.** Every agent-facing check is a blocker or it is removed. A warning that does not block is a silent failure — the gate-level form of the anti-pattern named in `software-development/principle/design-fundamentals` (Fail Fast): agents reliably do not act on warnings, so they accumulate into noise that hides the next real defect and trains everyone to ignore the channel.
   - `telec sync --warn-only` must not be used as a passing mode; tool warnings (e.g. an `eslint` `warning`) must be configured as errors or the rule deleted.
   - A finding that needs human judgment blocks **with an explicit, auditable override** (a scoped `noqa` / `--approved` / declared exception that lands in the diff with a reason) — never a passive warning. The override is a conscious, reviewable decision; a warning is silent rot.
   - The only non-gating channel is **pure information** (status/progress from the safe, decision-free watcher) — it signals nothing to act on, so it is output, not a warning.
1. **Fix all lint violations before commit**
2. **Do not suppress lint errors** unless explicitly approved and documented
3. **All imports at module top level by default** (`import-outside-toplevel` is disallowed unless explicitly approved)
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
- Startup-boundary lazy imports are the only standing policy exception for performance reasons
- Startup-boundary lazy imports are approved only in:
  - `teleclaude/daemon.py`
  - `teleclaude/daemon_event_platform.py`
  - `teleclaude/core/adapter_client/_client.py`
- Every startup-boundary `import-outside-toplevel` exception must include the same-line reason comment `startup boundary`
- Existing legacy exceptions outside this allowlist are transitional debt and must not expand

**CRITICAL**: Never commit with lint or type-check failures.

- Prefer smallest viable suppression; scope to a single line when unavoidable.
- Suppressions must not hide real defects (unused code, unreachable branches).
- Keep lint configuration centralized; do not add ad hoc per-file overrides.
- Keep lint/tooling versions pinned to project config.
- In uv-managed Python repositories, lint and type-check tools must be invoked through `uv run <tool> ...`, not bare executable names or the runtime interpreter.
- Test files must not carry `# guard: no-companion`; temporary orphan-test exceptions must be centralized in `[tool.test-mapping].orphan-exclude` and ratcheted down.

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
