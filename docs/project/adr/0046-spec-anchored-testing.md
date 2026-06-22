---
date: '2026-06-05'
description: 'Testing moves from agent-authored unit tests (1:1 source mapping, TDD iron-law) to spec-anchored behavioral tests that bind human-authored feature-spec scenarios. No agent unit tests where no compiler enforces correctness; functional + smoke levels; coverage measured against the scenario inventory; spec-mirrored test files; fingerprint-based drift detection.'
number: '46'
visibility: 'public'
---

# ADR-0046: Spec-Anchored Behavioral Testing Replaces Agent-Authored Unit Tests — ADR

## Context

The prior model mandated a unit test per source file, a TDD iron-law, and an expected-failure ceremony during prepare. It produced ~5,000 mock-heavy unit tests that hung, leaked resources, dominated cycles, and still let real regressions ship.

The root cause is structural: **when an agent authors both the code and the assertion, it grades its own homework** — it picks an assertion the code already passes, so green stops meaning correct. This is acute in languages without a compiler-grade guarantee (Python, TypeScript). The anchoring observation: agents reliably honor a _specified_ contract but reliably produce poor tests and poor cross-codebase coherence. So the suite's job is not to catch the agent's own bugs — it is to preserve coherence and give a measurable, un-gameable coverage signal against a human-owned contract.

## Decision

- **Tests bind human-authored feature-spec scenarios.** A test names the scenario it realizes and drives the real system to exercise it; agents bind unbound scenarios but never author assertions. The scenario author (human PO) and the test binder (build agent) are distinct roles — the un-gameable property depends on that separation, which is permanent because the human always owns the spec.
- **No agent-authored unit tests where no compiler enforces unit-level correctness** (Python, TypeScript). Rust is the exception: its compiler, types, and ownership provide the guarantee, so colocated unit tests over pure functions are kept.
- **Levels:** functional (primary, contract-verifying) + smoke (machine-checkable wiring); integration by justified exception.
- **Coverage is measured against the scenario inventory** (scenarios bound ÷ total), not source-file mapping; one test file per feature spec, path-mirrored.
- **Spec drift is caught by a per-scenario content fingerprint** — a binding is flagged stale when its scenario's Gherkin changes. Behavior flows spec → test → code.

## Consequences

- Retired: the 1:1-mapping and test-resource-discipline policies and the TDD-iron-law / required-unit / expected-failure doctrine inside the testing policy.
- The testing policy is rewritten to the new doctrine, with per-language variants and the Rust carve-out, and the Definition-of-Done and context gates updated to match.
- The same tech-agnostic scenarios bind to the v2 Rust re-implementation, so the suite doubles as the migration parity oracle.
