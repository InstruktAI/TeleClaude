---
description: Python verification permits one bounded black-box CLI acceptance harness, independent review, and integrator judgment of runtime logs.
---

# Test Moratorium — Policy

## Rules

- **Python test authorship is limited to the CLI acceptance harness.** Exceptions defines its allowed scope. Outside that allowance, adding a test file, a test dependency, or a test runner is a violation regardless of quality, size, or justification, and that includes markup-serialization snapshots (`toMatchSnapshot` over component trees) — a serialized render is the code restating itself.
- **The live daemon supplies operational signals.** What the main-only restart action reports, and where post-restart health is judged, is owned by `local/projects/teleclaude/policy/daemon-availability`. After activation, the standing integrator reads the delivery's log window under `sdlc/procedure/lifecycle/integrate` and uses its judgment to investigate anomalies and fix forward. The log bug hunter provides a later anomaly backstop. A regular committer's validation and independent commit-review obligations remain governed by `general/policy/commits`.
- **The CLI help smoke runs in the worktree.** A CLI-touching builder exercises each affected help path once through its worktree's own `bin/telec`, and the independent reviewer repeats that targeted smoke the same way. The wrapper runs the worktree's code against the home repository clone the platform provisions with the worktree, and the global `telec` runs installed code against the live platform (`local/projects/teleclaude/spec/feature/agent_runtime/isolated-home`); neither agent assembles home files or sets the variable. A shared command-surface change may traverse its affected help paths in one batch of those wrapper calls; routine lint never performs or substitutes for this check. Throwaway in-session probes are permitted — driven the same way and deleted before commit. An agent never sets, exports, or removes `TELECLAUDE_HOME` or `HOME`, and never removes a directory named by a variable: a shell variable does not survive from one tool call to the next, so a home set in one call and removed in another resolves to the live home. This smoke covers behavior inside the CLI process; commands that write project state or act through the daemon are outside its scope.
- **This repository does not bind the generic `test` action.** The platform base registry defines the action without a binding. Each repository owns its bindings through its own `teleclaude.yml`; satellite projects follow their own testing contracts.
- **The moratorium expires when the Rust runtime supersedes v1.** The Rust runtime states its own testing doctrine; nothing in this policy constrains it.

## Rationale

Verification uses a standard independent of the implementation under judgment
(`general/principle/verification-independence`). Python runtime substitution can
bypass the process boundaries where integration failures occur. The bounded
harness exercises those boundaries with real CLI processes, daemon requests and
persistent state, against independently reviewed public scenarios.

An uneventful log window does not prove every specified behavior occurred.
Build review judges conformance to the specifications, the logging policy
exposes significant operations and failures, and the integrator judges anomalies
after activation. The CLI journeys supply evidence for the behavior they
exercise; unvisited behavior is outside that evidence.

Disposable runtime isolation protects the operator's configuration, credentials
and services. Shared cold and full profiles concentrate verification on the
named public journeys, while full installation proof covers the supported
installation path. These boundaries keep the verification claim proportional to
what actually executes.

## Scope

This repository only. Satellite projects keep their own testing contract, declared in their own configuration. Extending the moratorium beyond this repository is a separate decision on its own evidence, never a consequence of this policy.

## Enforcement

- The `code` overlay block is absent from this repository's `teleclaude.yml`; the equivalent scope remains a generic binding carrying `log-check` alone. The binding identifies which changed paths owe integrator judgment, and the overlay assigns `log-check` to the standing integrator (`local/projects/teleclaude/design/architecture/checkpoint-system`), so the ordinary committing session's file-based checkpoint does not surface that action. A re-authored overlay keeps that assignment.
- **The quality-configuration assessment does not author a `code` block for this repository.** The checkpoint overlay is authored at assess-time — `sdlc/procedure/code-config-assessment` writes it and feeds `agent_stop` with `test` + `log-check` — and every session started with `/projects-assess-config` reaches that path. A re-authored `code` block silently re-binds `test` and voids this policy. Until a guardrails check enforces this, the absence of that block is a contract, not an oversight — an agent that finds it missing leaves it missing. The project-analysis procedure (`/projects-analyze`) never touches the overlay and is not a door to this failure.
- **Log judgment is the integrator's.** The `log-check` action records that the integrator read the activated delivery's log window. Its assessment and recovery remain intelligence work per `general/principle/intelligence-boundaries`.
- Reviewers treat test files, runners, and dependencies outside the bounded CLI acceptance allowance as blocking findings. The harness consumes independently reviewed scenarios from before implementation; its author does not bless a captured failure as the expected result.

## Exceptions

- One black-box CLI acceptance harness may be authored and maintained under
  `local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`.
  It drives real public entry points in fresh subprocesses and, for the full
  profile, a disposable runtime with real daemon, socket and persistent storage.
  Its controller imports no application modules and substitutes no application
  collaborators or authentication decisions. Synthetic input and disposable
  operating environments provide isolation; no live user configuration,
  credentials, daemon or storage is used.
- Python is preferred for harness orchestration, health observations, timeouts,
  cleanup and report handling, keeping shell orchestration from accumulating.
  Real CLI journeys invoke the public executables as subprocesses.
  Public command-line tools, including `curl`, are permitted when they serve the
  boundary being verified; supporting HTTP reads may use a Python client.
  Tool choice preserves real invocation fidelity and bounded, diagnosable
  execution. The Python preference is not a categorical subprocess-tool ban.
- The allowance includes only the harness, its scenario data, essential execution
  dependencies, and its fast commit/full hosted-CI/release wiring. General-purpose
  test corpora, the generic `test` binding, unit tests, per-module checks and markup
  snapshots are outside that allowance. Full installation proof is required by
  the release contract.
- Scenario assertions derive from the public contracts and are independently
  reviewed before implementation. Any unexpected error or wrong observable
  result fails its journey, regardless of error class. Coverage claims name the
  journeys exercised; passing cannot imply that every command works.
- Other verification needs require changes to this policy rather than one-off
  additions to the corpus.

## See Also

- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why the log-check conclusion is not machine-graded.
- ~/.teleclaude/docs/general/principle/verification-independence.md — why a self-authored check carries no information, and what counts as a standard from outside the session.
- ~/.teleclaude/docs/sdlc/policy/testing.md — the opt-in default this policy declares against.
- docs/local/adr/0100-commit-maintenance-drains-after-hook-return.md — why post-commit maintenance may complete after the agent's log read.
