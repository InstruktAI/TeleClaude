---
description: 'Observation map: the plan-carried wiring from each in-scope use case to the runtime evidence that proves it — entry schema, evidence states, observation-record contract, and telemetry-gap semantics.'
---

# Observation Map — Spec

## What it is

The observation map is the section of an implementation plan that wires every
in-scope use case to the runtime evidence that proves it. It exists because a
worktree can produce no runtime evidence: live proof of a delivered behavior
begins only after merge, on the runtime that carries the change. The map is how
a delivery makes that later proof possible without waiting for it.

Three facts about a use case are distinct and never conflated:

1. **Instrumentation exists** — the code contains the observation records the
   map promises, at the right semantic boundaries. Independent build review
   establishes this fact; it is called **armed**, and it is what delivery
   requires. Delivery never waits for runtime observation.
2. **The behavior occurred** — a qualifying opportunity arose and the expected
   outcome records appeared, correlated, within their bound.
3. **The occurrence satisfied the use case** — judgment over the correlated
   records. This is intelligence reading evidence, never code grading it
   (`general/principle/intelligence-boundaries`).

The planner authors the map during prepare. Plan review recomputes the use-case
inventory independently and judges whether each entry's predicate would actually
distinguish compliant from broken behavior. Plan approval freezes the map under
the approved artifact digest. A builder who discovers the map is wrong kicks
preparation back; it never silently revises the map it implements. Build review
verifies the promised records are emitted at their boundaries with the promised
fields. Post-delivery observation evaluates the frozen map against runtime
facts.

## Canonical fields

Each map entry carries a lean core. Facing and acceptance authority are **not**
fields: they derive from the facing-typed actors of the referenced scenario in
its feature spec, and duplicating them here is a defect.

| Field          | Content                                                                                                                                |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `uc`           | Use-case reference: `<spec_id>` + `UC-<id>` + revision.                                                                                |
| `scope_reason` | `delivers` (this work delivers the behavior) or `regression_guard` (unchanged behavior placed at risk by this work's blast radius).    |
| `opportunity`  | The qualifying upstream occurrence that makes the outcome due — an observable ingress or decision point, stated as a record predicate. |
| `expects`      | One or more expected outcome records, stated as predicates over record fields — never as literal log text.                             |
| `correlate`    | The identifier fields that tie opportunity to outcome (session id, message id, link id, …). Full identifiers, never truncated.         |
| `within`       | The maximum interval between opportunity and outcome before the outcome counts as missing.                                             |

Optional overrides, present only when the use case requires them:

- `policy` — defaults to `each_opportunity`. Override with `once_after_activation`
  or `periodic` when the behavior's shape demands it.
- Cardinality or ordering constraints — the default is exactly one terminal
  outcome per correlated opportunity.
- Forbidden outcomes — records whose presence violates the use case.

Everything else — activation metadata (todo id, plan digest, delivered commit,
runtime revision), evidence-state vocabulary, record format, privacy — lives in
this contract or in the delivery record, never per entry.

### The denominator is recomputed, never trusted

A map that covers every use case its own plan declares is not complete — it is
self-consistent. Plan review independently recomputes the denominator:

- the use cases the intended delta delivers, derived from the spec delta; and
- the unchanged use cases placed at risk by the change's blast radius, seeded
  mechanically (e.g. `telec code blueprint affected` over the touched
  surfaces) and completed by judgment.

Map coverage is checked against that independently derived inventory. An entry
set that matches the plan's own inventory but omits a blast-radius use case is
a defective map.

### An opportunity the change can suppress is not an opportunity

An entry proves nothing when the change under review can delete the very record
its opportunity is anchored on. Silence then reports as "nothing has happened
yet" while the truth is "nothing can be seen" — and every use case anchored on
that record goes quiet together, unfalsifiable by construction.

So each entry's opportunity is anchored **upstream of what the change can
break**: at a point the change cannot suppress, most reliably at an accepted
ingress rather than at an internal milestone the change itself produces. When
the only available anchor sits downstream of the change, the entry is vacuous
and is replaced by one further upstream, not merely reworded.

Plan review checks this per entry by asking: if this change were wrong in the
way it is most likely to be wrong, would this opportunity record still fire? An
entry that answers no is a **Requirement-Violation** — it is not weak evidence,
it is the absence of evidence wearing evidence's shape.

### Evidence states

| State                       | Meaning                                                                                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `armed`                     | Independent review confirmed the promised instrumentation correctly placed. Delivery may proceed.                                          |
| `armed_unobserved`          | No qualifying opportunity has occurred yet, and the opportunity record is reachable. No defect is inferred.                                |
| `unobservable`              | The opportunity record cannot fire while the delivered change is in force. Silence carries no information; a finding, never a clean state. |
| `observed`                  | A qualifying opportunity and conforming outcome records were correlated within the bound.                                                  |
| `contradicted`              | Records occurred but violated fields, order, cardinality, or a forbidden-outcome rule.                                                     |
| `missing_after_opportunity` | An opportunity occurred; the required outcome did not arrive within its bound.                                                             |
| `telemetry_unavailable`     | Level, retention, runtime identity, or ingestion continuity prevents judgment. Never reported as a product defect.                         |
| `superseded`                | A later delivery or use-case revision replaced this watch.                                                                                 |

A watch stays active until superseded or retired — never expired by the age of
its delivery. A rare path may honestly remain `armed_unobserved` indefinitely;
manufacturing proof for it would require synthetic exercise or human
observation, and the absence of both is an accepted, visible risk — not a
failure to be papered over.

Human-facing use cases follow the same map mechanics, but their acceptance
authority is human observation: at delivery they are `armed`, and they are
truthfully described as delivered-awaiting-observation, never as verified.

### Observation records

The evidence a map points at is a **structured observation record**, not an
incidental log line:

- Emitted through the project's logging framework as structured key/value
  pairs, at **INFO**. Contract-significant decisions are business-relevant
  events, which is what INFO means; proof never depends on raising a global
  level. TRACE is never admissible evidence, and a record that feels too noisy
  for INFO is a sign the semantic boundary is wrong — aggregate or move the
  emission point, never demote required proof below the production level.
- Emitted at the **semantic boundary**: after the platform receipt for a
  delivery, at the moment a suppression or routing decision is committed, after
  a durable cursor advances, at the accepted ingress for an opportunity — never
  before the fact it claims is decided.
- Carrying a stable event token, an outcome enum with a reason token, and the
  full correlation identifiers. No message bodies, no prompts, no tokens, no
  PII.
- **Negative behavior emits affirmatively.** "The notification did not appear"
  is unknowable from silence; a committed decision record
  (`outcome=suppressed reason=visibility_policy`) is observable. A use case
  about something _not_ happening maps to the decision record that chose not
  to do it.
- **A terminal outcome carries proof of terminality.** A record may report a
  work item as finished-unrecoverable only on evidence that the item itself is
  unusable — a durable conflict, an invalid structure, an exhausted contract.
  Failing to find something needed to process it is not that evidence: the
  thing may be late, and the correct outcome is to leave it pending and try
  again. A map entry whose pass condition accepts "could not resolve, therefore
  finished" specifies data loss as success, and plan review rejects it on that
  ground.

An observation record named by a frozen map is a behavioral contract. A
refactor may move its emitter; renaming it, dropping its fields, or weakening
its placement is a behavioral change that re-enters spec/map review — never a
housekeeping edit. Prefer centralized typed emitters over scattered logger
calls.

### Telemetry-gap semantics

Judgment over a map entry is valid only when the queried window is complete and
was produced by a runtime carrying the delivered commit. A gap in level,
retention, ingestion, or runtime identity yields `telemetry_unavailable` —
never `missing_after_opportunity`, and never a filed defect. Retroactive
reconstruction is bounded by trace retention; the watch itself is not.

## Known caveats

- The map proves delivery fidelity to the spec; it does not prove the spec was
  wise. Independence comes from authorized intent, independent derivation
  review, and the running system — not from the map's existence.
- Historical maps are read by todo UUID and approved artifact digest. Slug
  reads are unsafe: delivered slugs may be reused, and slug resolution prefers
  a live row.
- A single record suffices only for a genuinely atomic decision. Delivery,
  suppression, ordering, deduplication, and attribution generally require a
  correlated pair: accepted opportunity plus committed outcome.

## See Also

- ~/.teleclaude/docs/software-development/procedure/feature-spec-authoring.md — the use-case identity and facing conventions map entries bind to.
- ~/.teleclaude/docs/general/principle/verification-independence.md — why the map's authority derives from roles outside the building session.
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why evidence-state judgment is read by intelligence, not graded by code.
