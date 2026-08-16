---
description: 'Linting and type-checking rules. Required fixes, import rules, and suppression limits.'
visibility: 'public'
---

# Linting Requirements — Policy

## Rules

0. **Checks block; there is no passing warning tier.** Every agent-facing check is a blocker or it is removed. A warning that does not block is a silent failure — the gate-level form of the anti-pattern named in `software-development/principle/design-fundamentals` (Fail Fast): agents reliably do not act on warnings, so they accumulate into noise that hides the next real defect and trains everyone to ignore the channel.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- There is no warn-and-pass flag: `telec sync` always blocks on findings (`--skip-deploy` is the read-only gate; it still blocks). Tool warnings (e.g. an `eslint` `warning`) must be configured as errors or the rule deleted.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- There is no warn-and-pass flag: bare `telec sync` validates without mutation and always blocks on findings; `telec sync --deploy` mutates only after the same validation passes. Tool warnings (e.g. an `eslint` `warning`) must be configured as errors or the rule deleted.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- A finding that needs human judgment blocks **with an explicit, auditable override** using the applicable tool or language policy's narrow suppression mechanism, or a declared exception that lands in the diff with a reason — never a passive warning. The override is a conscious, reviewable decision; a warning is silent rot.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- The only validation bypass is the docs watcher's hidden, role-gated `--skip-validation` (live reload must not block; the commit gate is the contract). The only non-gating _output_ is pure information (status/progress) — it signals nothing to act on.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- There is no general validation bypass, including for watcher deployments. Project bootstrap is the sole non-blocking exception: it reports findings, then completes its internal initial deployment so initialization can finish. The only non-gating _output_ is pure information (status/progress) — it signals nothing to act on.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

1. **Fix all lint violations before commit**
2. **Do not suppress lint errors** unless explicitly approved and documented
3. Follow the applicable language policy's import-placement and dependency rules
4. No unused imports, variables, or arguments according to the language's native tooling
5. Respect configured formatter/linter defaults (do not override project config)

6. **Resolve all type-checker errors before commit**
7. Preserve type soundness; the applicable language policy owns unknown-value handling and prohibited escape types
8. Follow the language policy's return-type requirements
9. Follow the language policy's parameter-type and inference requirements
10. Use the language's fully specified generic or parametric types

- Only when required by a third-party limitation or transitional migration
- Must include a concise comment explaining the reason and scope
- Must include a follow-up todo for removal if temporary
- Standing exceptions and first-party path allowlists are project-owned policy. They never live in this generic contract.

**CRITICAL**: Never commit with lint or type-check failures.

- Prefer smallest viable suppression; scope to a single line when unavoidable.
- Suppressions must not hide real defects (unused code, unreachable branches).
- Keep lint configuration centralized; do not add ad hoc per-file overrides.
- Keep lint/tooling versions pinned to project config.
- Invoke lint and type-check tools through the runner owned by the applicable language tooling policy.
- Project-specific guard directives and temporary path exceptions are centralized in project-owned configuration or policy and ratcheted down.

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
