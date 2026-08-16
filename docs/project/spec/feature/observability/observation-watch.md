---
description: 'Continuous evaluation of delivered observation maps against runtime evidence: durable-cursor log coverage, exact-identity map retrieval, per-opportunity evidence-state judgment, and bug-lane filing for confirmed contract violations.'
---

# Observation Watch — Spec

## What it is

The observation watch is the platform's retroactive proving loop. Deliveries
never wait for runtime evidence — they land **armed**, with reviewed
instrumentation (`software-development/spec/observation-map`). The watch is
what eats the pudding afterwards: it continuously reads the runtime's
structured records against every active observation map and judges each use
case's evidence state, so a delivered behavior that never actually happens, or
happens wrongly, surfaces as a signal instead of waiting for a human to notice.

The watch observes and files; it never investigates or fixes inline. A
confirmed violation enters the bug lane as a minimal report and the existing
diagnose/fix lifecycle owns it from there.

The intelligence boundary holds throughout
(`general/principle/intelligence-boundaries`): mechanical code parses
structured records, correlates the declared identifier fields, and maintains
cursors; judging whether correlated records satisfy a use case's predicate is
agent judgment, and the capability's design names where that judgment runs.
Code never semantically grades prose predicates.

## Canonical fields

### Use cases

#### UC-OW1: Log coverage is continuous, with no blind windows

```gherkin
Given the watch runs on a recurring schedule
When consecutive runs scan the runtime's structured records
Then no produced record in the retained window is left unexamined between runs
And consecutive scan windows overlap rather than leaving gaps between a run's lookback and the previous run's end
And re-examining an already-judged record after an overlap or an interrupted run is idempotent: it changes no settled evidence state and files no duplicate report
And the scan position is a durable cursor that survives restarts
And a run that cannot complete leaves the cursor where judgment last concluded, never silently skipping ahead
```

#### UC-OW2: Maps are retrieved by exact identity, never by slug

```gherkin
Given a delivered todo's approved implementation plan carries an observation map
When the watch loads that map for evaluation
Then it addresses the plan by the todo's immutable identifier and the approved artifact digest
And a reused or recycled slug can never cause the watch to read a different todo's map
```

#### UC-OW3: A watch entry stays active until superseded or retired

```gherkin
Given a delivered use case's map entry is active
When later deliveries land
Then the entry remains under evaluation regardless of the age of its delivery
And it is deactivated only when a later delivery or use-case revision explicitly supersedes it, or the use case is retired
And an entry whose behavior has never had a qualifying opportunity remains armed-unobserved, which is not a defect
```

#### UC-OW4: A qualifying opportunity demands its outcome within the bound

```gherkin
Given an active map entry's qualifying opportunity is observed in the records
When the entry's completion bound elapses
Then a conforming correlated outcome within the bound marks the use case observed when its acceptance authority is structured evidence
And a human-facing use case's occurrence may be confirmed or contradicted by records, but its acceptance remains awaiting human observation
And an absent outcome marks it missing-after-opportunity and produces a signal
And correlation uses the entry's declared identifier fields, never timestamps alone
```

#### UC-OW5: Wrongful presence is detected, not only absence

```gherkin
Given an active map entry declares cardinality, ordering, field-relationship, or forbidden-outcome constraints
When correlated records violate any declared constraint
Then the use case is marked contradicted and produces a signal
And a duplicate terminal outcome for one correlated opportunity is a cardinality violation even though every individual record looks well-formed
```

#### UC-OW6: Telemetry gaps are never product defects

```gherkin
Given the watch evaluates an entry over a window
When the window is incomplete — records rotated away, the runtime did not carry the delivered change, log level or ingestion was interrupted
Then the entry is marked telemetry-unavailable for that window
And no bug is filed from a gap
And the gap itself is surfaced as an operational signal distinct from any behavioral finding
```

#### UC-OW7: Confirmed violations enter the bug lane, deduplicated

```gherkin
Given an entry is marked missing-after-opportunity or contradicted
When the watch files the finding
Then it emits a minimal bug report into the platform's bug lane naming the use case, the evidence state, and the correlated records
And it does not investigate or fix inline
And a signal matching an active known-issue suppression is not re-filed
And repeated observations of one already-filed violation do not produce duplicate reports
```

## Known caveats

- Retroactive reconstruction is bounded by record retention; the watch proves
  continuously recurring behavior on natural recurrence, not history that
  rotated away before it ran.
- The watch judges evidence states; whether a spec was wise is outside its
  authority. Its findings are facts for the bug lane, not verdicts on design.

## See Also

- ~/.teleclaude/docs/software-development/spec/observation-map.md — the map contract and evidence-state vocabulary this watch evaluates.
