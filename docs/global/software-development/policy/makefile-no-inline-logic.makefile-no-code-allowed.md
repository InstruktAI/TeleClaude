---
description: Makefile targets contain no inline shell behavior; recipes delegate to testable, lintable scripts. Mandated for TeleClaude's own repo; offered to satellites, never mandated.
visibility: internal
---

# Makefile No Inline Logic — Policy

## Rules

- The TeleClaude mothership `Makefile` is a target-name convention surface only.
  Each recipe is a single delegation to a script or module entrypoint that owns
  the behavior.
- A recipe contains no inline shell behavior: no status `echo` lines, direct
  binary invocations, loops, conditionals, pipelines, chained commands,
  directory setup, argument parsing, file traversal, cleanup, or other shell
  logic.
- Passing Make variables or literal arguments to the delegated entrypoint is
  allowed only as part of the single delegation line.
- Help text, cleanup, coverage, diagrams, Rust workspace commands, daemon
  lifecycle commands, cron checks, install behavior, and quality behavior all
  live behind delegated scripts or typed module entrypoints.
- The relocated script or module is the unit of testability and review: bash
  scripts are `set -euo pipefail` and shellcheck-clean; module entrypoints are
  linted and type-checked like any other code.
- The Makefile stays the thin convention surface the project toolchain model
  defines: it owns target names and standalone runnability, not the steps.

## Rationale

Logic embedded in a Makefile recipe is neither linted nor tested nor easily read.
Even direct tool invocations accrete status output, setup, cleanup, branching, and
argument shaping over time. Moving every behavior behind a script or module keeps
the convention surface stable while placing executable logic where the normal
quality gates can inspect it.

## Scope

- TeleClaude's own mothership repository: mandated. Every `Makefile` recipe here
  delegates; none embeds shell behavior or direct tool execution.
- Adopting satellite projects: offered, never mandated. A satellite may adopt
  this convention, but it is never required to.

## Enforcement

- Reviewers reject a TeleClaude-repo Makefile recipe that is not a single
  delegation line.
- Reviewers reject any direct-binary exemption in the TeleClaude mothership
  `Makefile`; direct tool calls belong in delegated scripts or modules.
- The relocated scripts and modules are held to their language quality bar.

## Exceptions

- Satellite repositories are outside the mandate.
- There is no direct-binary or status-output exception for TeleClaude's own
  Makefile.

## See Also

- ~/.teleclaude/docs/software-development/design/project-toolchain.md
