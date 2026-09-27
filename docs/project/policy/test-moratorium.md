---
description: This repository authors no tests. The Python test corpus and its toolchain are absent by ruling until the Rust runtime supersedes v1; the integrator judges runtime logs after activation.
---

# Test Moratorium — Policy

## Rules

- **There is no `tests/` tree and no test toolchain here.** The global default already forbids authoring; this repository additionally holds no corpus and no runner to reinstate. Adding a test file, a test dependency, or a test runner is a violation regardless of quality, size, or justification, and that includes markup-serialization snapshots (`toMatchSnapshot` over component trees) — a serialized render is the code restating itself.
- **The live daemon supplies operational signals.** The main-only restart action reports its health-checked terminal outcome. After activation, the standing integrator reads the delivery's log window under `sdlc/procedure/lifecycle/integrate` and uses its judgment to investigate anomalies and fix forward. The log bug hunter remains a later anomaly backstop. A regular committer's validation and independent commit-review obligations remain governed by `sdlc/policy/commits`.
<!-- planned-change:agent-home-clone-provisioning -->
- **The CLI help smoke runs in the worktree.** A CLI-touching builder exercises each affected help path once through its worktree's own `bin/telec`, which runs the worktree's code against a temporary home it creates and removes itself, and the independent reviewer repeats that targeted smoke the same way; the global `telec` runs installed code and cannot exercise the change, and worktree code never runs against the live home (`project/design/architecture/cli-invocation-boundary`). A shared command-surface change may traverse its affected help paths in one batch of those wrapper calls; routine lint never performs or substitutes for this check. Throwaway in-session probes are permitted — driven the same way and deleted before commit. An agent never sets, exports, or removes `TELECLAUDE_HOME` or `HOME`, and never removes a directory named by a variable: a shell variable does not survive from one tool call to the next, so a home set in one call and removed in another resolves to the live home. This smoke covers behavior inside the CLI process; commands that write project state or act through the daemon are outside its scope.
<!-- change:agent-home-clone-provisioning -->
- **The CLI help smoke runs in the worktree.** A CLI-touching builder exercises each affected help path once through its worktree's own `bin/telec`, and the independent reviewer repeats that targeted smoke the same way. The wrapper runs the worktree's code against the home repository clone the platform provisions with the worktree, and the global `telec` runs installed code against the live platform (`project/spec/feature/agent_runtime/isolated-home`); neither agent assembles home files or sets the variable. A shared command-surface change may traverse its affected help paths in one batch of those wrapper calls; routine lint never performs or substitutes for this check. Throwaway in-session probes are permitted — driven the same way and deleted before commit. An agent never sets, exports, or removes `TELECLAUDE_HOME` or `HOME`, and never removes a directory named by a variable: a shell variable does not survive from one tool call to the next, so a home set in one call and removed in another resolves to the live home. This smoke covers behavior inside the CLI process; commands that write project state or act through the daemon are outside its scope.
<!-- /planned-change:agent-home-clone-provisioning -->
- **The `test` action is unbound, never removed.** The platform base registry keeps the `test` action; only this repository's `code` scope stops binding it. The unbind is expressed in this repository's own `teleclaude.yml`, and the platform base carries no `test` binding of its own, so no satellite project's contract changes.
- **The moratorium expires when the Rust runtime supersedes v1.** The Rust runtime states its own testing doctrine; nothing in this policy constrains it.

## Rationale

Why a self-authored check carries no information is `general/principle/verification-independence`, and is not restated here. Two things are specific to this repository.

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

- The `code` overlay block is absent from this repository's `teleclaude.yml`; the equivalent scope remains a generic binding carrying `log-check` alone. The binding identifies which changed paths owe integrator judgment, and the overlay assigns `log-check` to the standing integrator (`project/design/architecture/checkpoint-system`), so the ordinary committing session's file-based checkpoint does not surface that action. A re-authored overlay keeps that assignment.
- **The quality-configuration assessment does not author a `code` block for this repository.** The checkpoint overlay is authored at assess-time — `sdlc/procedure/code-config-assessment` writes it and feeds `agent_stop` with `test` + `log-check` — and every session started with `/projects-assess-config` reaches that path. A re-authored `code` block silently re-binds `test` and voids this policy. Until a guardrails check enforces this, the absence of that block is a contract, not an oversight — an agent that finds it missing leaves it missing. The project-analysis procedure (`/projects-analyze`) never touches the overlay and is not a door to this failure.
- **Log judgment is the integrator's.** The `log-check` action records that the integrator read the activated delivery's log window. Its assessment and recovery remain intelligence work per `general/principle/intelligence-boundaries`.
- Reviewers treat a new test file, a reinstated runner, or a new test dependency as a blocking finding.

## Exceptions

- None while the moratorium stands. A verification need that survives this policy is raised as a change to this policy, never as a one-off test.

## See Also

- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why the log-check conclusion is not machine-graded.
- ~/.teleclaude/docs/general/principle/verification-independence.md — why a self-authored check carries no information, and what counts as a standard from outside the session.
- ~/.teleclaude/docs/sdlc/policy/testing.md — the opt-in default this policy declares against.
- docs/project/adr/0100-commit-maintenance-drains-after-hook-return.md — why post-commit maintenance may complete after the agent's log read.
