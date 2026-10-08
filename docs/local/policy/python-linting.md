---
description: TeleClaude-specific Python lint exceptions and guardrail placement that are not portable to other repositories.
---

# Python Linting — Policy

## Required reads

@~/.teleclaude/docs/sdlc/policy/linting-requirements.md
@~/.teleclaude/docs/sdlc/policy/python/core.md

## Rules

<!-- planned-change:isolate-todo-command-dependencies -->

- Startup-boundary lazy imports are the only standing first-party exception to Python's module-top import rule.
- The exception is limited to:
  - `teleclaude/daemon.py`
  - `teleclaude/daemon_event_platform.py`
  - `teleclaude/core/adapter_client/_client.py`
- Every local-import suppression in those files includes the same-line reason `startup boundary` and names the suppressed import-placement rule.
- Existing local-import exceptions outside this allowlist are transitional debt and must not expand.

<!-- change:isolate-todo-command-dependencies -->

- Startup-boundary lazy imports remain limited to:
  - `teleclaude/daemon.py`
  - `teleclaude/daemon_event_platform.py`
  - `teleclaude/core/adapter_client/_client.py`
- Every local-import suppression in those files includes the same-line reason
  `startup boundary` and names the suppressed import-placement rule.
- Command-boundary imports are a standing exception only in
  `teleclaude/cli/telec/handlers/todo.py`. They load a selected command's handler
  or dependencies after CLI clearance, inside that command's entrypoint or a
  helper executed only by commands that need the dependency. A shared router
  loads no command-specific dependency before selection
  (`local/projects/teleclaude/design/architecture/cli-invocation-boundary`).
- Each command-boundary local import names the narrow import-placement rule in
  its same-line suppression and states the `command boundary` reason. Imports
  within the selected leaf modules remain at module top level unless an existing
  separate exception applies.
- Other first-party local-import exceptions remain transitional debt and do not
  expand. Linter configuration, type-checker exemptions and general suppression
  surfaces retain their existing scope.

<!-- /planned-change:isolate-todo-command-dependencies -->

- Test files do not carry `# guard: no-companion`. Temporary orphan-test exceptions live centrally in `[tool.test-mapping].orphan-exclude` and only shrink.

### Argument-type checking

- Pyright reports argument-type incompatibility for Python files under the
  analyzed source roots configured in `pyrightconfig.json`, apart from the
  CLI/API carve-out below. Those roots do not cover every first-party Python
  directory; enabling the rule does not imply repository-wide coverage.
  Mypy's per-module overrides disable `arg-type` across a large first-party
  surface, so Pyright is the effective gate for those checked call sites.
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

## Rationale

<!-- planned:isolate-todo-command-dependencies -->

A CLI router selects one action for one invocation. Loading every sibling's
workflow and rendering dependencies before that selection charges an action for
work it never performs. The bounded router exception makes the command's import
owner coincide with its execution owner while keeping ordinary leaf modules and
the rest of the Python source tree under the module-top rule.
<!-- /planned:isolate-todo-command-dependencies -->

These exceptions name TeleClaude modules and guardrail configuration, so they cannot be universal Python rules. Keeping them in project scope prevents adopting repositories from inheriting mothership paths or exception mechanics while retaining one explicit owner for the exceptions here.

An invariant belongs in the strongest layer that can express it, and for
argument compatibility that layer is the type system
(`sdlc/policy/code-quality-practices`). A closed type that no
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

## Scope

- TeleClaude's Python source tree, lint configuration, and test-mapping guardrails.

## Enforcement

<!-- planned-change:isolate-todo-command-dependencies -->

- Reviewers reject new first-party lazy-import locations and expansion of the transitional set.

<!-- change:isolate-todo-command-dependencies -->

- Reviewers apply the named startup and todo-command boundaries above and reject
  new locations, unrelated eager dependency loading, or expansion of the remaining
  transitional set. Independent deep review assesses any proposed widening of
  these standing exceptions before dependent work enters the lifecycle
  (`general/policy/agent-artifact-governance`).

<!-- /planned-change:isolate-todo-command-dependencies -->

- Python lint reports local imports outside the declared exception surface.
- Guardrail review rejects test-local companion suppression and expansion of centralized orphan exclusions.

- Reviewers reject a new or broadened argument-type exemption that carries no
  record of independent deep review, and treat maintenance framing of such a
  diff as the signature of erosion rather than as mitigation.
- Reviewers reject a call-site correction that widens a parameter, introduces
  `Any`, or suppresses the diagnostic where the annotation was the defect.

## Exceptions

<!-- planned-change:isolate-todo-command-dependencies -->

- None beyond the explicit startup-boundary allowlist above.

<!-- change:isolate-todo-command-dependencies -->

- Only the explicitly named startup and todo-command boundaries above.

<!-- /planned-change:isolate-todo-command-dependencies -->
