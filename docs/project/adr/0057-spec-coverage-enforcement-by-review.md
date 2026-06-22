---
visibility: 'public'
number: '57'
date: '2026-06-23'
description: 'Spec-anchored coverage and structure are enforced by the build-review reviewer and the spec → test → code change process, not by automated tooling. The per-scenario content-fingerprint drift mechanism and an automated spec-structure/coverage gate (a validator wired into telec sync and pre-commit) are not adopted.'
---

# ADR-0057: Spec coverage and structure are enforced by review, not automated tooling — ADR

## Context

ADR-0046 established spec-anchored behavioral testing and named two enforcement mechanisms intended to make the model un-gameable: a **per-scenario content fingerprint** that flags a binding stale when its scenario's Gherkin changes, and an **automated spec-structure/coverage gate** — a validator wired into `telec sync` and pre-commit that rejects non-conforming feature specs and reports orphan/duplicate/stale bindings.

Neither mechanism was built. The repository ships only an on-demand, Python-only coverage report (`tools/lint/spec_coverage.py`) that is wired into no gate, and the testing doctrine, per-language policies, and Definition-of-Done documents drifted to describe the unbuilt automation as if it existed — including pointing reviewers at a "stale" signal nothing computes.

Two forces decide the matter. First, the judgment the gate would perform — is a binding honest, is a test functional rather than a unit test wearing the label, is an unbound scenario actually in this change's scope — is semantic, and the testing doctrine already declares it a review judgment that "no path check or scanner decides." Second, the proposed drift automation is brittle: hashing normalized Gherkin churns on trivial rewording, and storing a fingerprint inside each binding couples every spec edit to a test-file edit.

## Decision

Spec-anchored coverage and structure are enforced by **the build-review reviewer** and **the spec → test → code change process**, not by automated tooling.

- **Drift** is caught by the change process: when a scenario's Gherkin changes, the bound test is re-derived from the new contract before the change is done, and the reviewer verifies it. There is no content-fingerprint mechanism.
- **Structure** (the `### Use cases` section, well-formed and unique `#### UC-` ids, one Gherkin block per id) and **binding completeness** are upheld by authoring discipline and the reviewer. There is no validator gate in `telec sync` or pre-commit.
- `tools/lint/spec_coverage.py` remains an **on-demand report** (bound / unbound / duplicate / orphan, Python bindings only) a reviewer may run. It is not a gate.

The role-separation core of ADR-0046 — the human authors scenarios, the build agent binds them, the reviewer judges — is unchanged. This decision narrows only the enforcement surface ADR-0046 anticipated.

## Consequences

- The testing policy, the per-language testing policies, and the Definition-of-Done documents describe the enforcement that actually exists; the "stale"/fingerprint and sync/pre-commit-validator claims are removed.
- Coverage and structure correctness now depend on reviewer diligence rather than a mechanical gate. The objective completeness signal (orphan/duplicate/unbound) is available only when a reviewer runs the on-demand report, and only for Python bindings; TypeScript and Rust binding completeness rest entirely on review.
- Spec drift has no machine alarm: a scenario can change without an automated flag forcing its binding to be revisited. The guard is the change process and review, which are fallible in a way a fingerprint would not be — accepted as the cost of avoiding the churn and coupling the fingerprint imposes.
- If the manual surface later proves insufficient, a future ADR may re-introduce a narrower mechanical signal with a concrete fingerprint-storage design.

## Alternatives Considered

- **Build the ADR-0046 automation as specified** (fingerprint + sync/pre-commit validator gate). Rejected: the gate's core judgment is non-automatable by design and already owned by review, and the fingerprint mechanism is brittle (churn on rewording, spec-edit/test-edit coupling) for value review already provides.
- **Keep the doctrine's automation claims as documented-but-unbuilt aspiration.** Rejected: doctrine that asserts a running gate and a "stale" signal that does not exist actively misleads reviewers and is a documentation defect, not a roadmap.
- **Wire the existing on-demand report in as a hard gate.** Rejected for now: the `#### UC-` corpus is not uniform (some ids omit the dash, some sit on a `Scenario:` line the parser misses), so a hard gate would false-fire until a corpus-conformance pass lands; the report stays advisory until then.
