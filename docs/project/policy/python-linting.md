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

<!-- planned:enable-pyright-argument-type-checking -->

### Argument-type checking

- Pyright reports argument-type incompatibility across the repository. It is the
  only checker that does so everywhere: mypy's per-module overrides in
  `pyproject.toml` disable `arg-type` across a large first-party surface, so a
  call-site type error inside that surface reaches no other gate.
- The carve-out covers the CLI surface and the API surface, and nothing else:
  the `teleclaude/cli` package, the `teleclaude/api` package, and the
  `teleclaude/api_server` module that serves the same routes from the package
  root. `pyrightconfig.json` owns the exact paths and the severity applied to
  them; this policy owns the rule that the carve-out reaches those three and no
  further.
- The carve-out is transitional debt that only shrinks. Narrowing it, or
  removing it, needs no approval. Widening it — a new exempt path, a broader
  glob, or a lowered severity — is a relaxation of quality-defining
  configuration and requires the independent deep review that
  `general/policy/agent-artifact-governance` mandates.
- Pyright's checked surface only grows. A first-party Python directory that
  enters it never leaves; a directory still outside it is an unclosed gap, not a
  sanctioned exclusion.
- A call site that pyright rejects is corrected at the boundary — the annotation
  that tells the truth about the value. Widening a parameter to accept the wrong
  argument, introducing `Any`, or suppressing the diagnostic defeats the check.
  Where a third-party stub genuinely misdescribes a library that accepts the
  value at runtime, the narrow same-line suppression form with its stated reason
  applies, as it does for every other suppression here.

<!-- /planned:enable-pyright-argument-type-checking -->

## Rationale

These exceptions name TeleClaude modules and guardrail configuration, so they cannot be universal Python rules. Keeping them in project scope prevents adopting repositories from inheriting mothership paths or exception mechanics while retaining one explicit owner for the exceptions here.

<!-- planned:enable-pyright-argument-type-checking -->

An invariant belongs in the strongest layer that can express it, and for
argument compatibility that layer is the type system
(`software-development/policy/code-quality-practices`). A closed type that no
checker enforces is a comment: the annotation reads as a constraint, nothing
rejects the call that violates it, and every reader downstream trusts a
guarantee the build never made. Declaring strict type checking and then
disabling the rule that enforces it at call sites is that failure written into
configuration.

The carve-out is bounded to the CLI and API surfaces rather than removed because
the errors concentrate there, and burning them down inside this contract change
would bury the contract. Naming the packages here, while the paths and severity
stay in the checker's own configuration, keeps one source of truth for the
values and one owner for the rule about them. The asymmetry between shrinking
and widening follows from what the configuration is: the wall the work is
measured against. A session blocked by that wall has every reason to move it and
none to move it correctly, so moving it outward is the one direction that needs
an author with no stake in the result.
<!-- /planned:enable-pyright-argument-type-checking -->

## Scope

- TeleClaude's Python source tree, lint configuration, and test-mapping guardrails.

## Enforcement

- Reviewers reject new first-party lazy-import locations and expansion of the transitional set.
- Python lint reports local imports outside the declared exception surface.
- Guardrail review rejects test-local companion suppression and expansion of centralized orphan exclusions.

<!-- planned:enable-pyright-argument-type-checking -->
- Reviewers reject a new or broadened argument-type exemption that carries no
  record of independent deep review, and treat maintenance framing of such a
  diff as the signature of erosion rather than as mitigation.
- Reviewers reject a call-site correction that widens a parameter, introduces
  `Any`, or suppresses the diagnostic where the annotation was the defect.
<!-- /planned:enable-pyright-argument-type-checking -->

## Exceptions

- None beyond the explicit startup-boundary allowlist above.
