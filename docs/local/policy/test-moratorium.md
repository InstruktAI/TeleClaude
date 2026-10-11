---
description: The Python test corpus remains absent; a bounded black-box CLI acceptance harness is the sole authoring exception, alongside integrator judgment of runtime logs.
---

# Test Moratorium — Policy

## Rules

- **The general Python test corpus and toolchain remain absent.** The CLI acceptance harness defined in Exceptions is the sole authoring allowance. Outside that allowance, adding a test file, a test dependency, or a test runner is a violation regardless of quality, size, or justification, and that includes markup-serialization snapshots (`toMatchSnapshot` over component trees) — a serialized render is the code restating itself.
- **The live daemon supplies operational signals.** What the main-only restart action reports, and where post-restart health is judged, is owned by `local/projects/teleclaude/policy/daemon-availability`. After activation, the standing integrator reads the delivery's log window under `sdlc/procedure/lifecycle/integrate` and uses its judgment to investigate anomalies and fix forward. The log bug hunter remains a later anomaly backstop. A regular committer's validation and independent commit-review obligations remain governed by `general/policy/commits`.
- **The CLI help smoke runs in the worktree.** A CLI-touching builder exercises each affected help path once through its worktree's own `bin/telec`, and the independent reviewer repeats that targeted smoke the same way. The wrapper runs the worktree's code against the home repository clone the platform provisions with the worktree, and the global `telec` runs installed code against the live platform (`local/projects/teleclaude/spec/feature/agent_runtime/isolated-home`); neither agent assembles home files or sets the variable. A shared command-surface change may traverse its affected help paths in one batch of those wrapper calls; routine lint never performs or substitutes for this check. Throwaway in-session probes are permitted — driven the same way and deleted before commit. An agent never sets, exports, or removes `TELECLAUDE_HOME` or `HOME`, and never removes a directory named by a variable: a shell variable does not survive from one tool call to the next, so a home set in one call and removed in another resolves to the live home. This smoke covers behavior inside the CLI process; commands that write project state or act through the daemon are outside its scope.
- **The `test` action is unbound, never removed.** The platform base registry keeps the `test` action; only this repository's `code` scope stops binding it. The unbind is expressed in this repository's own `teleclaude.yml`, and the platform base carries no `test` binding of its own, so no satellite project's contract changes.
- **The moratorium expires when the Rust runtime supersedes v1.** The Rust runtime states its own testing doctrine; nothing in this policy constrains it.

## Rationale

Why a self-authored check carries no information is `general/principle/verification-independence`, and is not restated here. Two things are specific to this repository.

An uneventful log window does not prove that every specified behavior occurred.
That limit is accepted here: build review judges conformance to the specs, the
logging policy exposes significant operations and failures, and the integrator
judges anomalies after activation. The bounded CLI journeys add pre-delivery evidence for real process wiring and observable outcomes; they do not establish unvisited behavior. Breakage found later enters normal recovery
and is fixed forward. Requiring live proof for each delivery would recreate the
preparation work this ruling removes.

**The substrate makes the worthless path the cheapest one.** Python's runtime patching means faking a collaborator costs one line, so the cheapest route to a green test is a test that asserts nothing. The Rust runtime's corpus carries no mocks at all. That contrast reflects substrate and doctrine together — a different language, a stricter doctrine, and a younger codebase — not the language alone.

### Measured evidence

Every bug in the durable record — 167 of them, spanning 2026-03-31 to 2026-07-27 — was classified against a fixed rubric by five independent readers:

| Finding                                                 | Count     |
| ------------------------------------------------------- | --------- |
| Catchable by no realistic pre-written agent test        | 122 (73%) |
| Plainly catchable by a straightforward test             | 35 (21%)  |
| Catchable only by booting heavy machinery               | 6 (4%)    |
| Delivered items whose subject was the test suite itself | 12        |

Failure classes: wiring 32%, logic 30%, state 13%, process 12%, race 8%. The verification budget was aimed at logic; 70% of failures were elsewhere.

The control is built in: the 1312-test suite was fully in place while all 167 shipped, including every one of the 35 plainly catchable ones. Suite size is uncorrelated with defect capture in this codebase. Four diagnoses record an existing test _pinning the defect as correct_, so the suite entrenched wrong behavior rather than merely missing it.

Method limits: one classifier vote per bug, and 36 were judged from bug reports rather than diagnosis artifacts. Two independent aggregations agreed within two percentage points.

The 35 catchable defects are branch and table errors in first-party logic — precisely the class Rust's exhaustive matching and closed types make unrepresentable. They fund the Rust runtime's type discipline, not a Python suite that demonstrably did not catch them.

Recovery cost is the other half of the case. An agent rewrites a module in minutes, so the refactoring-safety-net argument that funds a suite in human-paced development does not hold here. What insurance still pays for is failure that is both silent and irreversible. That class is served by the Rust runtime's invariant and architecture-fitness tests, not by Python restatements.

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
- Public command-line tools, including `curl`, are permitted inside this
  harness. Real CLI journeys remain subprocess invocations; supporting HTTP
  observations may use a command-line client or a Python client. The choice
  follows the boundary being verified and its timeout, cleanup and diagnostic
  requirements. The general preference for native Python APIs is not a ban on
  subprocess tools here: rejecting a tool requires a concrete correctness or
  operational reason, preserving fidelity to real invocations.
- The allowance includes only the harness, its scenario data, essential execution
  dependencies, and its fast commit/full hosted-CI/release wiring. It does not
  restore a general test corpus, the generic `test` binding, unit tests,
  per-module checks, or markup snapshots. Existing full installation proof
  remains required by the release contract.
- Scenario assertions derive from the public contracts and are independently
  reviewed before implementation. Any unexpected error or wrong observable
  result fails its journey, regardless of error class. Coverage claims name the
  journeys exercised; passing cannot imply that every command works.
- Other verification needs remain changes to this policy rather than one-off
  additions to the corpus.

## See Also

- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why the log-check conclusion is not machine-graded.
- ~/.teleclaude/docs/general/principle/verification-independence.md — why a self-authored check carries no information, and what counts as a standard from outside the session.
- ~/.teleclaude/docs/sdlc/policy/testing.md — the opt-in default this policy declares against.
- docs/local/adr/0100-commit-maintenance-drains-after-hook-return.md — why post-commit maintenance may complete after the agent's log read.
