---
description: TeleClaude-specific Python lint exceptions and guardrail placement that are not portable to other repositories.
---

# Python Linting — Policy

## Required reads

@~/.teleclaude/docs/software-development/policy/linting-requirements.md
@~/.teleclaude/docs/software-development/policy/python/core.md

## Rules

- Startup-boundary lazy imports are the only standing first-party exception to Python's module-top import rule.
- The exception is limited to:
  - `teleclaude/daemon.py`
  - `teleclaude/daemon_event_platform.py`
  - `teleclaude/core/adapter_client/_client.py`
- Every local-import suppression in those files includes the same-line reason `startup boundary` and names the suppressed import-placement rule.
- Existing local-import exceptions outside this allowlist are transitional debt and must not expand.
- Test files do not carry `# guard: no-companion`. Temporary orphan-test exceptions live centrally in `[tool.test-mapping].orphan-exclude` and only shrink.

## Rationale

These exceptions name TeleClaude modules and guardrail configuration, so they cannot be universal Python rules. Keeping them in project scope prevents adopting repositories from inheriting mothership paths or exception mechanics while retaining one explicit owner for the exceptions here.

## Scope

- TeleClaude's Python source tree, lint configuration, and test-mapping guardrails.

## Enforcement

- Reviewers reject new first-party lazy-import locations and expansion of the transitional set.
- Python lint reports local imports outside the declared exception surface.
- Guardrail review rejects test-local companion suppression and expansion of centralized orphan exclusions.

## Exceptions

- None beyond the explicit startup-boundary allowlist above.
