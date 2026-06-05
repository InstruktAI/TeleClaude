---
id: 'project/adr/0014-spec-anchored-testing'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '14'
date: '2026-06-05'
adr_status: 'accepted'
description: 'Testing moves from agent-authored unit tests (1:1 source mapping, TDD iron-law) to spec-anchored behavioral tests that bind human-authored feature-spec scenarios. No agent unit tests where no compiler enforces correctness; functional + smoke levels; coverage measured against the scenario inventory; spec-mirrored test files; fingerprint-based drift detection.'
---

# ADR-0014: Spec-Anchored Behavioral Testing Replaces Agent-Authored Unit Tests — ADR

## Context

The prior model mandated a unit test per source file (1:1 source-to-test mapping), a TDD iron-law
(the agent writes a failing unit test first), per-tier timeout machinery, and an expected-failure
("xfail") test-spec ceremony during prepare. In practice it produced ~5,000 mock-heavy unit tests
that hung, leaked OS resources, dominated working cycles, and still let real regressions ship.

The root cause is structural, not incidental. **When an agent authors both the code and the
assertion, it grades its own homework** — it picks the assertion the code already passes, so green
stops meaning correct. This is acute in languages without a compiler-grade guarantee (Python,
TypeScript), where the type system does not enforce runtime behavior. The 1:1 mandate compounded it
by manufacturing low-value "satisfy the mapping" tests (logger assertions, shape checks, literal
echoes). The hang/leak machinery (watchdog, subprocess reaper, in-flight tracker, session timeout)
was reactive scaffolding that existed only because tests were allowed to do real I/O.

The operational observation that anchors the new model: **agents reliably honor a specified contract,
but reliably produce poor tests and poor coherence across a codebase.** So the job of the test suite
is not to catch bugs the agent would have made — it is to preserve coherence and provide a
measurable, un-gameable coverage signal against a human-owned contract.

## Decision

- **Tests bind human-authored feature-spec scenarios.** Each test names the scenario it realizes
  (`<spec_id>`, `UC-<area><n>`); the human-authored Gherkin is the contract, the test only drives the
  real system to exercise it. Agents bind unbound scenarios; they never author assertions. The
  scenario author (the human Product Owner, agent-assisted at intake) and the test binder (build) are
  distinct roles — the un-gameable property depends on that separation, which is permanent because the
  human always owns the spec.
- **No agent-authored unit tests where no compiler enforces unit-level correctness** (Python,
  TypeScript). Rust is the documented exception: its compiler, types, and ownership provide the
  guarantee, so colocated `#[cfg(test)]` units over pure functions are kept; Rust's spec-bound
  behavior lives in `crates/<crate>/tests/`.
- **Levels: functional (primary, contract-verifying) + smoke (machine-checkable wiring); integration
  by justified exception.** Each functional test asserts its own boundary contract, so composition is
  trustworthy without broad end-to-end suites.
- **Coverage is measured against the scenario inventory** (scenarios bound ÷ total), not source-file
  mapping. One test file per feature spec, path-mirrored.
- **Spec drift is caught by a per-scenario content fingerprint:** a binding is flagged stale when its
  scenario's Gherkin changes. Behavior changes flow spec → test → code, RED-GREEN by scenario delta.

## Consequences

- **Retired:** `policy/test-structure` (1:1 mapping), `policy/test-resource-discipline` (the deleted
  machinery), and the TDD-iron-law / required-unit-level / expected-failure-marker doctrine inside
  `policy/testing`.
- **New:** `policy/testing` rewritten to the doctrine; per-language `python/testing`,
  `typescript/testing`, and the Rust carve-out; `tools/lint/forbid_unit_tests.py`;
  `tools/lint/spec_coverage.py`. The context gate and `definition-of-done` updated to match.
- **Follow-on build work (separate todos):** extend `spec_coverage.py` with scenario fingerprints,
  stale/file-mapping checks, and TypeScript/Rust binding parsers; add the spec-structure validator;
  restructure `tests/` into `tests/feature/<domain>/`; update the prepare/work state-machine
  formatters to compute and emit the scenario delta.
- The same tech-agnostic scenarios bind to the v2 Rust re-implementation, so the suite doubles as the
  migration parity oracle.
