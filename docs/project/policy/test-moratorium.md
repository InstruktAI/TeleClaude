---
description: This repository authors no tests. The Python test corpus and its toolchain are absent by ruling until the Rust runtime supersedes v1; verification runs against the live daemon.
---

# Test Moratorium — Policy

## Rules

- **There is no `tests/` tree and no test toolchain here.** The global default already forbids authoring; this repository additionally holds no corpus and no runner to reinstate. Adding a test file, a test dependency, or a test runner is a violation regardless of quality, size, or justification, and that includes markup-serialization snapshots (`toMatchSnapshot` over component trees) — a serialized render is the code restating itself.
- **The live daemon is the verification surface.** The `restart` and `log-check` checkpoint obligations carry verification for code changes. An agent cannot write the running system's behavior to agree with its own wrong design.
- **Where the checkpoint obligations reach the change, they are the live verification and they are sufficient.** For a change whose scope binds `restart` and `log-check`, those two obligations discharge the mandate below in full: `restart` boots the daemon carrying the change and `log-check` reads what that running daemon then did. This sentence is location-bound: `restart` is a main-only action, and a worktree `log-check` observes the currently running daemon — which does not carry the worktree's delta — so it cannot prove that delta's behavior. A worktree builder therefore delivers code and worktree-sanctioned evidence only; the live semantics of these obligations land where they bind, at the post-merge force-fire on `main`. A plan task that schedules a live behavioral probe for a worktree builder is authoring an act its role cannot legally or physically perform — the executability rule in `software-development/policy/preparation-artifact-quality` governs, and this policy names the location facts that rule needs. For a human-visible UI-adapter outcome — when the change executes on `main`, where the running daemon carries it — performing `log-check` means driving the changed path through the real system and inspecting its structured evidence under `project/procedure/ui-adapter-delivery-verification`; this is the semantic content of the existing obligation, not a supplementary test or per-todo gate. Agents verify TeleClaude's dispatch decisions, while the human separately confirms external-platform rendering. Nothing further is owed, and no bespoke verification step is authored on top of these procedures. Their scope-bound, delta-derived form is deliberate — it keeps the obligation uniform and unforgettable — so the absence of a mechanism for a todo to hand a role an additional behavior to verify is the design, not a gap to fill. A plan, review finding, or artifact that treats these obligations as insufficient, or that invents an owner for a supplementary check, is reading this policy wrongly.
- **Where the checkpoint obligations do not reach, drive the real system here.** For a frontend flow, a CLI surface, or an API path no bound action exercises, the `project/procedure/frontend-verification` procedure (availability check, dev login, Playwright smoke of the changed flow) is mandatory before claiming a frontend change works. Throwaway in-session probes are permitted — exercised against the running system and deleted before commit. That live verification is never banned is the global default's rule, not this one; this rule names the local surfaces it applies to.
- **The screenshot-regression harness is required for frontend surfaces, under this contract:** a bounded set of key screens, deliberately grown and never accumulated per feature; each captured in **both** color themes, because a hardcoded color renders correctly in the theme its author developed in and silently breaks the other; driven serially against the real browser at page level. The harness emits a per-theme diff report — facts, never verdicts; whether a diff is intended is judged by intelligence per `general/principle/intelligence-boundaries`, and build review reads the diffs for frontend-touching changes. That a captured, human-ratified baseline survives a test ban at all is the global default's rule; this is the harness that realizes it here.
- **The `test` action is unbound, never removed.** The platform base registry keeps the `test` action; only this repository's `code` scope stops binding it. The unbind is expressed in this repository's own `teleclaude.yml`, and the platform base carries no `test` binding of its own, so no satellite project's contract changes.
- **The moratorium expires when the Rust runtime supersedes v1.** The Rust runtime states its own testing doctrine; nothing in this policy constrains it.

## Rationale

Why a self-authored check carries no information is `general/principle/verification-independence`, and is not restated here. Two things are specific to this repository.

**The substrate makes the worthless path the cheapest one.** Python's runtime patching means faking a collaborator costs one line, so the cheapest route to a green test is a test that asserts nothing. The Rust runtime's corpus carries no mocks at all. That contrast reflects substrate and doctrine together — a different language, a stricter doctrine, and a younger codebase — not the language alone.

**Why the screenshot harness is required rather than merely permitted.** CSS has no blast-radius graph: an agent's live walk covers the flow it changed, while a shared-style edit breaks screens it never visits. That is the dominant silent failure of frontend work, and pixel diffing is the only detector for it. A theme split doubles the exposure, since a hardcoded color renders correctly in the theme its author developed in and breaks the other unseen.

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

- The `code` overlay block is absent from this repository's `teleclaude.yml`; the equivalent scope is declared through a generic binding carrying `log-check` alone.
- **`telec projects assess` does not author a `code` block for this repository.** The checkpoint overlay is authored at assess-time — `software-development/procedure/code-config-assessment` writes it and feeds `agent_stop` with `test` + `log-check` — and `telec projects onboard` reaches the same path by dispatching assess. A re-authored `code` block silently re-binds `test` and voids this policy. Until a guardrails check enforces this, the absence of that block is a contract, not an oversight — an agent that finds it missing leaves it missing. `telec projects analyze` never touches the overlay and is not a door to this failure.
- **Runtime evidence binds the command, not the conclusion.** The checkpoint gate verifies that the log check ran, not that the logs were clean. That judgement stays with intelligence per `general/principle/intelligence-boundaries`, and the gate is correspondingly softer than a binary exit code. This is a known and accepted limit, not an oversight.
- Reviewers treat a new test file, a reinstated runner, or a new test dependency as a blocking finding.
- Reviewers treat the removal or non-authoring of visual-regression coverage for a changed frontend surface as a blocking finding, and an agent-updated visual baseline as a blocking finding. Citing this moratorium as grounds for either is itself the violation.

## Exceptions

- None while the moratorium stands. A verification need that survives this policy is raised as a change to this policy, never as a one-off test.

## See Also

- docs/project/procedure/ui-adapter-delivery-verification.md — how `log-check` proves daemon-side UI-adapter delivery without claiming external-platform rendering.
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why the log-check conclusion is not machine-graded.
- ~/.teleclaude/docs/general/principle/verification-independence.md — why a self-authored check carries no information, and what counts as a standard from outside the session.
- ~/.teleclaude/docs/software-development/policy/testing.md — the opt-in default this policy declares against.
