# Requirements Review Findings: mirror-runtime-isolation

## Round 2 — Disposition of Round 1 Findings

| R1 Finding | Severity | Status | Notes |
|---|---|---|---|
| F1: Unmarked inferences | Important | Downgraded to Suggestion | Plan explicitly acknowledges inferences as grounded codebase facts. Requirements unchanged but risk is low. |
| F2: Conditional DB split config surface | Suggestion | Closed | Plan Task A6 specifies config key and wizard path. |
| F3: Storage decision measurement gap | Suggestion | Closed | Plan Task A5 defines concrete gate criteria. |

---

## Finding 1: Inference markers still absent (carried from R1F1)

**Severity: Suggestion**

The Canonical Transcript Contract paths/shapes, Lane A/B sequencing, and measurement
gate metrics are inferred from codebase analysis rather than explicitly stated in
`input.md`. The requirements still carry no `[inferred]` markers.

The implementation plan explicitly acknowledges this ("inferred items are treated as
grounded codebase facts"), which reduces the practical risk. The inferences are
mechanical facts (filesystem paths, existing monitoring capabilities) rather than
architectural assumptions, making surprise unlikely.

Downgraded from Important because the full artifact set (requirements + plan)
addresses the transparency gap, even though the requirements artifact alone does not.

**Remediation (optional):** Add `[inferred]` markers to the Canonical Transcript
Contract section and the measurement gate metrics. This is no longer blocking.
