---
description: Investigate pre-dispatch import-closure refusals and justify required shared imports with startup evidence and independent review.
---

# Pre-dispatch Import-Closure Refusal — Procedure

## Required reads

- @docs/project/design/architecture/cli-invocation-boundary.md
- @~/.teleclaude/docs/general/policy/agent-artifact-governance.md
- @~/.teleclaude/docs/sdlc/policy/process-change-authority.md

## Goal

Determine whether an import belongs in the shared pre-dispatch closure, using
the startup cost it imposes on every CLI command as evidence.

## Preconditions

- The import-closure guardrail has reported a failure.
- The candidate change and its base revision are available for comparison.

## Steps

1. Read the reported failure. Continue with closure analysis only when it
   identifies an unexpected import edge or closure mismatch. A package-version
   or probe-execution failure is evidence about that probe, not about whether the
   import belongs in the closure.
2. Trace an unexpected import edge through package initializers and its
   third-party dependencies, then assess whether the pre-dispatch auth gate
   needs it against the gate's dependency boundary
   (`project/design/architecture/cli-invocation-boundary`).
3. When the dependency is necessary before dispatch, compare fresh-process
   startup of the same cheap CLI command from the base and candidate on the same
   host. Inspect the import and initialization delta that explains any shared
   startup cost.
4. Before changing the declared closure, record the same-host startup comparison,
   import and initialization delta, material reason for the shared pre-dispatch
   cost, and before-and-after guarantee in the change description or RFC, as
   required by `sdlc/policy/process-change-authority`. Do not add a module merely
   to silence the guardrail or hide its import behind a local import without
   accounting for when it runs.
5. Treat a closure expansion as a relaxation of a quality guardrail. It requires
   explicit approval from an independent reviewer with no stake in the change
   (`general/policy/agent-artifact-governance`).

## Outputs

- The import edge is moved behind dispatch, or a closure update is supported by
  same-host startup comparison, import and initialization evidence, and a
  documented reason and before-and-after guarantee before independent review.

## Recovery

- If the reported failure does not identify an import edge or closure mismatch,
  leave the declared closure unchanged and investigate the reported probe failure
  on its own evidence.
- If evidence does not establish that the gate needs the dependency, keep it out
  of the pre-dispatch path until the need and shared-cost evidence are established.
