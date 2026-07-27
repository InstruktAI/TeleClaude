---
description: Executable logic lives in script or module files and nowhere else. Any other file carries only declaration and wiring, whatever its format. Mandated for TeleClaude's own repo; offered to satellites, never mandated.
visibility: internal
---

# No Inline Logic — Policy

## Rules

- **Executable logic lives in a script or module file. Nowhere else.** A file
  whose purpose is configuration, declaration, orchestration, or convention
  carries no behavior of its own — it names a delegated entrypoint that owns the
  behavior.
- **The carrier's format is irrelevant.** `Makefile` recipes, CI workflow `run:`
  blocks, container build steps, git hooks, service unit definitions, task
  runners, and every future format that grows an executable body are the same
  case. This policy keeps no list of covered file types, because a list is an
  invitation to argue that the next format is not on it.
- **The delegation is a single line.** Passing variables or literal arguments to
  the delegated entrypoint is part of that line. A second step is a second line
  of the script, not a second line of the carrier.
- **The threshold is a handful of lines of literal wiring — roughly three to
  five.** Beyond that, it is code and it moves. Below it, a body is still only
  permitted when it is pure wiring: naming a command and its arguments. Line
  count is a smell test, never a budget to spend.
- **Any one of these makes a body code, at any length:** a conditional, a loop, a
  pipeline, a chained command, variable computation or string surgery, argument
  parsing, file traversal, error handling, or arithmetic. A body that branches is
  code at three lines.
- **The tells are mechanical.** A body that cannot be run standalone, cannot be
  linted, and cannot be tested is in the wrong place. If reproducing a failure
  means triggering the pipeline that wraps it, it belongs in a script.
- A typed module entrypoint invoked through the package runner
  (`uv run -m <module>`) is the blessed module-delegation form. The forbidden
  shape is a bare external tool (`pytest`, `docker`, `jq`, `git`, `find`, and
  similar) carrying inline arguments and logic in the carrier itself.
- **The relocated script or module is the unit of testability and review.** Bash
  scripts are `set -euo pipefail` and shellcheck-clean; module entrypoints are
  linted and type-checked like any other code. Relocation that lands the logic
  somewhere still unlintable has not discharged this rule.
- Help text, cleanup, coverage, diagrams, daemon lifecycle, cron checks, install
  behavior, version computation, release tagging, changelog generation, and
  quality behavior all live behind delegated scripts or typed module entrypoints.

## Rationale

Logic embedded in a carrier file is neither linted nor typed nor tested nor
easily read. It runs only when the surrounding machinery runs, so a defect in it
surfaces at the worst possible moment — mid-pipeline, mid-release, mid-deploy —
and cannot be reproduced without re-triggering that machinery. Every quality gate
the project owns is blind to it.

The carrier format is not the variable. A conditional is equally unreviewable in
a Make recipe, a workflow `run:` block, and a container build step; scoping the
rule to one format leaves the identical defect legal in the next one. Enumerating
covered formats also fails by construction: the list is always one format behind
whatever was adopted most recently, and the gap reads as permission.

Small bodies are where this starts. A single tool invocation accretes a status
line, then a guard, then a fallback, then argument shaping — each addition
defensible against the last, none against the original. Naming a low threshold
makes the accretion visible while it is still cheap to move.

## Scope

- TeleClaude's own mothership repository: mandated, without exception, for every
  file that can carry an executable body.
- Adopting satellite projects: offered, never mandated. A satellite may adopt
  this convention, but it is never required to.

## Enforcement

- Reviewers reject any carrier body in this repository that is not a single
  delegation line, regardless of the file's format or extension.
- Reviewers reject a body that clears the line threshold but branches, loops,
  computes, or parses. Length is not the discriminator; behavior is.
- "It is only a few lines" and "this format is not covered" are both rejected —
  the first misreads the threshold as a budget, the second asks for the whitelist
  this policy refuses to keep.
- The relocated scripts and modules are held to their language quality bar.

## Exceptions

- Satellite repositories are outside the mandate.
- Within this repository there is no exception — not for direct-binary
  invocations, not for status output, not for a format this policy does not name.

## See Also

- ~/.teleclaude/docs/software-development/design/project-toolchain.md
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md — the workflow catalog whose pipelines this policy keeps thin.
