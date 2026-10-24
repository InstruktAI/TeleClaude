---
description: 'The telec quality runner (test/lint/format, via make) launches its native toolchain as a detached process-group leader and reaps the whole group before returning — on a caught signal, a propagating exception, and the normal-return path — so no suite-spawned descendant survives reparented to PID 1.'
visibility: 'public'
---

# Quality Runner Process Groups — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

<!-- planned-change:telec-repo-command-family -->

`telec code test`, `telec code lint`, and `telec code format` run the
project's selected native checks. Each invocation owns its spawned command
processes and reaps their descendants before returning, on success, failure, or
cancellation; the command's original result or error remains the outcome.

<!-- change:telec-repo-command-family -->

`telec repo test`, `telec repo lint`, and `telec repo format` run the
project's selected native checks. Each invocation owns its spawned command
processes and reaps their descendants before returning, on success, failure, or
cancellation; the command's original result or error remains the outcome.

<!-- /planned-change:telec-repo-command-family -->

Guardrail subprocesses use the checked-out TeleClaude runtime independently of
the launching interpreter. Native Python checks use the already prepared
project environment and do not synchronize dependencies. Full-native lint
requests for the same Git repository serialize; each request runs its selected
checks once and receives its own outcome, and a queued request can be cancelled.
Cancellation reaches started command groups, which are reaped before temporary
grading environments are removed. Guardrail stage records use an opaque
execution-root identifier and never include the raw root path; recording does
not change the check outcome.

## Canonical fields

### Use cases

<!-- planned-change:telec-repo-command-family -->

#### UC-CQD1: telec code test reaps a suite-spawned descendant on a normal-exit (session_timeout) interrupt

#### UC-CQD2: telec code lint runs a guardrails step under the bundled interpreter regardless of the launching interpreter

<!-- change:telec-repo-command-family -->

#### UC-CQD1: telec repo test reaps a suite-spawned descendant on a normal-exit (session_timeout) interrupt

#### UC-CQD2: telec repo lint runs a guardrails step under the bundled interpreter regardless of the launching interpreter

<!-- /planned-change:telec-repo-command-family -->

#### UC-CQD3: routine lint does not execute CLI help paths

#### UC-CQD4: Guardrail stage durations distinguish subprocess checks from source validation

#### UC-CQD5: Full native lint runs share one repository concurrency slot

#### UC-CQD6: Root formatting checks reuse Prettier's content cache

#### UC-CQD7: Full Python analysis uses bounded Pyright workers

#### UC-CQD8: Independent lint checks overlap after preparation

#### UC-CQD9: Concurrent lint retains process ownership through interruption

#### UC-CQD10: Native Python lint uses the prepared environment

## Known caveats

- Abrupt process termination can prevent a stage's completion record. TRACE
  entry records identify which stage was entered when diagnosing that case.
- Guardrail stage durations do not include earlier hook startup or Git-tree
  materialization, and do not time the separate native toolchain.
- Full-native concurrency control reduces competition; it does not reuse
  arbitrary Make or state-dependent guardrail results. Scoped native requests
  retain their existing behavior.
- Prettier's cache does not fingerprint plugin implementations. This project's
  root formatter currently has no plugins; adopting or updating a plugin
  requires invalidating its formatting cache.
- Pyright's worker mode is experimental in the pinned tool version. The worker
  count is bounded to two rather than derived from all available processors.

## See also

- docs/local/adr/0064-runner-reaps-process-group-on-normal-exit.md
- docs/local/adr/0050-restore-declarative-test-budgets.md
