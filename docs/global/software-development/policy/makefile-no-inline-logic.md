---
description: "Makefile targets carry no inline orchestration logic; recipes delegate to testable, lintable scripts. Mandated for TeleClaude's own repo; offered to satellites, never mandated."
visibility: internal
---

# Makefile No Inline Logic — Policy

## Rules

- A Makefile target carries no inline orchestration logic. Each recipe is a
  one-line delegation to a script that holds the logic — a bash script under
  `tools/` or `bin/` when the work only shells out to binaries, a module
  entrypoint when the work warrants a typed, tested unit.
- Trivial direct binary delegation is not "logic." A recipe whose body is a
  single tool invocation (`uv run pytest`, `cargo fmt --all`) stays inline; the
  rule targets multi-step orchestration — scoped-vs-full branching, argument
  parsing, file bucketing, loops, conditionals.
- The relocated script is the unit of testability and review: bash scripts are
  `set -euo pipefail` and shellcheck-clean; module entrypoints are linted and
  type-checked like any other code.
- Status `@echo` lines and make-variable pass-through (`FILES_FROM`,
  `SNAPSHOT_UPDATE`) are not logic and may remain in the recipe.
- The Makefile stays the thin convention surface the project toolchain model
  defines: it owns the native toolchain contract and standalone runnability, not
  the steps.

## Rationale

Logic embedded in a Makefile recipe is neither linted nor tested nor easily read
— it accretes shell complexity that no quality gate inspects, the exact failure
the platform's testability bar exists to prevent. Relocating it to a script puts
the logic where shellcheck, review, and (for modules) the type checker can hold
it, while the Makefile keeps doing the one thing it is good at: naming
conventional entry points. Direct binary calls are exempt because wrapping a
one-line tool invocation in a script would only add indirection without moving
any logic out of sight.

## Scope

- TeleClaude's own (mothership) repository: mandated. Every `Makefile` recipe
  here delegates; none embeds orchestration logic.
- Adopting satellite projects: offered, never mandated. The blessed satellite
  `Makefile.template` stays self-contained and satellite-owned; a satellite may
  adopt this convention but is never required to.

## Enforcement

- Reviewers reject a TeleClaude-repo Makefile recipe that embeds orchestration
  logic instead of delegating.
- The relocated scripts are held to their language's quality bar
  (shellcheck-clean bash; linted/type-checked modules).

## Exceptions

- Satellite repositories — the rule is offered, not enforced.
- Single-tool-invocation recipes — exempt by the trivial-delegation rule above.

## See Also

- ~/.teleclaude/docs/software-development/design/project-toolchain.md
