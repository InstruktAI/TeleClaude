---
description: This repository authors no tests. The Python test corpus and its toolchain are absent by ruling until the Rust runtime supersedes v1; verification runs against the live daemon.
---

# Test Moratorium — Policy

## Rules

- **What is banned is deciding your own right answer.** A check is banned when the agent that wrote the code also writes down what the correct result is — the code then agrees with itself and proves nothing. A check is allowed when the correct result comes from outside that session: a screenshot the human approved, a requirement the human stated, or the behavior of the real running system. Every rule below follows from this one; a mechanical or committed check is never banned merely for being mechanical or committed.
- **No test is authored in this repository.** There is no `tests/` tree and no test toolchain. Writing a test file, adding a test dependency, or reinstating a test runner is a violation regardless of the test's quality, size, or justification. This covers unit tests, functional tests, and markup-serialization snapshots (`toMatchSnapshot` over component trees) — a serialized render is the code restating itself.
- **This repository declares no authorship, which the global default already assumes.** `software-development/policy/testing` makes test authorship opt-in: no test is authored in a project that has not declared otherwise, and its mandates bind only where a project opts in. This policy is that declaration for this repository, and states the concrete form it takes here. The reasoning it rests on is `general/principle/verification-independence`; the per-language policies stay intact and continue to govern any project that does opt in, and the Rust runtime unchanged.
- **The live daemon is the verification surface.** The `restart` and `log-check` checkpoint obligations carry verification for code changes. An agent cannot write the running system's behavior to agree with its own wrong design.
- **Where the checkpoint obligations reach the change, they are the live verification and they are sufficient.** For a change whose scope binds `restart` and `log-check`, those two obligations discharge the mandate below in full: `restart` boots the daemon carrying the change and `log-check` reads what that running daemon then did. Nothing further is owed, and no per-todo verification step is authored on top of them. Their scope-bound, delta-derived form is deliberate — it keeps the obligation uniform and unforgettable — so the absence of a mechanism for a todo to hand a role a bespoke behavior to verify is the design, not a gap to fill. A plan, review finding, or artifact that treats these obligations as insufficient, or that invents an owner for a supplementary check, is reading this policy wrongly.
- **Live verification is mandated, never banned — the moratorium governs authored artifacts only.** Where the checkpoint obligations above do not reach the changed behavior — a frontend flow, a CLI surface, an API path no bound action exercises — an agent drives the real running system in its own session to prove its change works. CLI invocations, API calls, and a Playwright-driven walk of the changed frontend flow are verification, not tests, and skipping them "because of the moratorium" is a violation of this policy, not compliance with it. For frontend changes the `project/procedure/frontend-verification` procedure (availability check, dev login, Playwright smoke of the changed flow) remains mandatory before claiming the change works. Throwaway in-session probes are likewise permitted — exercised against the running system and deleted before commit.
- **Visual regression is a required mechanical check, not a banned test.** A screenshot baseline is captured from the rendered system and ratified by the human, so what it compares against is recorded reality, not something an agent decided. A committed screenshot-regression harness is therefore required for frontend surfaces, under this contract: a bounded set of key screens, deliberately grown and never accumulated per feature; each captured in **both** color themes, because a hardcoded color renders correctly in the theme its author developed in and silently breaks the other; driven serially against the real browser at page level. The harness emits a per-theme diff report — facts, never verdicts; whether a diff is intended is judged by intelligence per `general/principle/intelligence-boundaries`, and build review reads the diffs for frontend-touching changes.
- **Every visual baseline update is ratified by the human, on every surface.** An agent never blesses a diff its own change produced; an agent-updated baseline is a violation, because a baseline the code's author may rewrite degrades to "whatever the code now renders." The human's approval is what makes the baseline trustworthy.
- **The `test` action is unbound, never removed.** The platform base registry keeps the `test` action; only this repository's `code` scope stops binding it. The unbind is expressed in this repository's own `teleclaude.yml`, and the platform base carries no `test` binding of its own, so no satellite project's contract changes.
- **Review lanes carry no testing gate here.** Plan review, build review, and commit review apply no test-coverage or test-quality lane in this repository.
- **The moratorium expires when the Rust runtime supersedes v1.** The Rust runtime states its own testing doctrine; nothing in this policy constrains it.

## Rationale

Agent-authored tests in this repository carry no verification value, for reasons that are structural rather than remediable by better instruction:

- **The code decides its own right answer.** A test derived from the artifact it checks restates that artifact rather than checking it. When one context window produces both the code and the test, a wrong design yields a test that agrees with the wrong design. This is an information problem, not an intelligence problem: more capable models produce the same tautology.
- **The stance a test requires is trained out.** Writing a valuable test is an act of adversarial distrust toward one's own work. Reinforcement learning from human feedback rewards agreeableness toward context, including code the model just produced. Instruction text cannot restore a stance the fine-tuning objective removes, which is why accumulated guidance never held.
- **Cost is felt in-session; value is not.** A suite's cost lands on the session that runs it; a test's payoff lands after that session ends. Under that asymmetry any agent-maintained suite erodes toward weak-or-absent regardless of doctrine.
- **The substrate makes the worthless path the cheapest one.** Python's runtime patching means faking a collaborator costs one line, so the cheapest route to a green test is a test that asserts nothing. The Rust runtime's corpus carries no mocks at all. That contrast reflects substrate and doctrine together — a different language, a stricter doctrine, and a younger codebase — not the language alone.

Visual regression is the counter-case that fixes the ban's shape, and it earns its keep on two properties agent-written tests lack. Its baseline is captured from the rendered system rather than written, and the human's approval makes that capture trustworthy — so the self-agreement argument above does not reach it. And CSS has no blast-radius graph: an agent's live walk covers the flow it changed, while a shared-style edit breaks screens it never visits. That is the dominant silent failure of frontend work, and pixel diffing is the only detector for it. A theme split doubles the exposure, since a hardcoded color renders correctly in the theme its author developed in and breaks the other unseen.

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

- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why the log-check conclusion is not machine-graded.
- ~/.teleclaude/docs/general/principle/verification-independence.md — why a self-authored check carries no information, and what counts as a standard from outside the session.
- ~/.teleclaude/docs/software-development/policy/testing.md — the opt-in default this policy declares against.
