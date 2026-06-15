---
description: "Detect when a Todo's prepared artifacts and authored doc snippets no longer reflect current truth — code surfaces, upstream artifacts, owned/referenced doc snippets, dependency graph, and age — and force re-grounding before the Todo may reach prepared."
visibility: 'public'
---

# Drift Detection — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/documentation-first-development.md

## What it is

Drift detection is the workflow capability that decides whether a Todo's
prepared artifacts (`prd`, `architecture` index, `implementation-plan`) and
the doc snippets they own or reference still reflect current truth. The
prepare state machine refuses to advance a Todo to `prepared` while drift is
unresolved, so that downstream work always derives from a fresh PRD,
fresh architecture, a fresh plan, and a fresh design surface.

Drift is not a single class — it is a taxonomy. Truth lives in several
places (code, sibling artifacts, doc snippets, the todo-list dependency
graph) and an artifact authored at one moment can fall out of step with any
of them by the time prepare is asked to converge. The feature names each
class explicitly, records the provenance needed to detect it, derives a
status per class on every `telec todo prepare` call, and routes a
`/next-drift-analyze` worker when classification cannot be made
deterministically from evidence alone.

Drift detection is **fail-safe by design**: when provenance is missing,
when the diff cannot be classified, or when an upstream reference cannot be
resolved, the status is `pending` and the lifecycle blocks. A `cosmetic`
verdict from the drift analyzer is **scoped to the evidence anchor at
which it was made** — when a later change exceeds that anchor, the verdict
expires and the artifact re-enters `pending` automatically. There is no
silent acceptance of new drift behind a stale verdict.

The feature integrates with the existing prepare lifecycle without adding
a new phase: drift is derived inside the existing `BLOCKED` branch and
cleared by the existing `--drift-reviewed` stamp surface. It also
participates at the work-entry boundary: `telec todo work` calls the same
shared derivation function before its `prepared → build_started` handoff,
and on `pending` or `substantive` collapsed status returns a script telling
the orchestrator to call `telec todo prepare {slug}` to resolve drift.
Autonomous continuation is the existing orchestrator-script contract — the
PREPARED terminal's lineage-conditioned resume reminder has the bounced work
orchestrator resume `telec todo work {slug}`, closing the loop without a human
gate on either cosmetic or substantive verdicts (a fresh prepare that never
bounced self-ends at the same terminal).

## Canonical fields

### Drift classes (taxonomy)

Each tracked artifact is evaluated against every applicable class on every
prepare call. The overall artifact drift status is the **most blocking**
status across its classes (`substantive` > `pending` > `cosmetic` > `fresh`).

| Class                 | Evidence checked                                                                                                  | When pending                                                                                                          |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **code**              | Artifact's `codebase_sha_at_write` vs current `origin/main` HEAD, scoped to `referenced_paths`.                   | HEAD has moved AND at least one changed path overlaps `referenced_paths`.                                             |
| **upstream-artifact** | Digest of each upstream artifact (e.g., PRD digest at the time architecture was written) vs current digest.       | Any upstream artifact has been rewritten since this artifact was authored.                                            |
| **owned-snippet**     | Digest of each doc snippet the Todo owns via `delivered_by` (recorded at artifact write time) vs current digest.  | An owned snippet was edited outside this prepare flow since the artifact was authored.                                |
| **upstream-snippet**  | Digest of each non-owned doc snippet the artifact references by ID, recorded at write time, vs current digest.    | A referenced snippet's content has changed since the reference was recorded.                                          |
| **dependency-graph**  | The Todo's immediate `after` set and each direct dep's status at write time vs current. Shallow — not transitive. | The immediate dep set changed (added/removed) OR any direct dep's status flipped (e.g., a HELD dep is now DELIVERED). |
| **age** _(policy)_    | Artifact `produced_at` vs configurable freshness window.                                                          | `produced_at` is older than the configured window for the artifact kind.                                              |

Pending drift contract update:

| Class                | Evidence checked                                                                                                                         | When pending                                                                                                                                               |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **code**             | Artifact's `codebase_sha_at_write` vs current `origin/main` HEAD, scoped to the implementation-plan's declared `referenced-paths` block. | HEAD has moved AND at least one changed path overlaps the declared contract. Artifacts that declare no block carry an empty code surface and derive fresh. |
| **dependency-graph** | The Todo's immediate `after` set and each direct dep's normalized status at write time vs current. Shallow -- not transitive.            | The immediate dep set changed (added/removed) OR a direct dep crossed the active/icebox boundary. `active` -> `delivered` is normalized and stays fresh.   |

<!-- planned:runner-dispatch -->

Prepare dependency ground may be satisfied by a
direct dependency's human-approved PRD before that dependency reaches
`prepared`. This adds a parent-ground drift class so the relaxation is safe:

| Class                 | Evidence checked                                                                                                                                                                                                                                               | When pending                                                                                                                                                                                      |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **parent-prd-ground** | For each direct dependency used as PRD-approved prepare ground: the dependency slug, PRD artifact digest, human PRD approval timestamp/session, and any later parent architecture/implementation-plan digest recorded when the dependent artifact was written. | A dependency loses or changes its human PRD approval, its PRD digest changes, or later parent architecture/plan evidence appears or changes after the dependent prepared against PRD-only ground. |

The class is evaluated for `prd`, `architecture`, and `implementation-plan`
artifacts while the todo is still in prepare, and at the work-entry drift check
before `prepared -> build_started`. A pending or substantive
`parent-prd-ground` result blocks the dependent exactly like existing drift
classes. If every direct dependency is delivered, the class derives fresh
because delivered ground supersedes PRD-only prepare ground.

<!-- /planned:runner-dispatch -->

### Provenance recorded per artifact

When a tracked artifact is written (`telec todo artifacts write`), the
workflow's state-stamping boundary captures all evidence needed for every
drift class that applies to it. Per-artifact provenance:

- `codebase_sha_at_write` — `origin/main` HEAD SHA at write time. Captured
  via a single origin-main-sha helper that is the canonical drift anchor.
  ALL artifact-provenance write paths read from this helper rather than
  local HEAD. The drift derivation compares against the same helper, so
  the write-time anchor and the derivation-time comparison agree on what
  "current main" means even when the local repo's HEAD diverges from
  origin/main between write and derive.
- `referenced_paths` — tracked repo paths mentioned in the artifact body.
- `referenced_paths` — the sorted, de-duplicated file paths declared inside
  the implementation-plan artifact's single ` ```referenced-paths ` fenced
  block. Prose path mentions are not part of the code drift surface. Tracked
  artifacts that do not declare a block record an empty list, so the code
  class derives fresh for them.
- `upstream_artifact_digests` — map of `{upstream_artifact_name: digest}` for
  every artifact this artifact derives from (per artifact-kind table below).
  **Field consolidation (architecture-resolved):** the existing
  `upstream_digests` field on the artifact lifecycle entry is **kept as the
  canonical storage field** under its current name. The spec-side name
  `upstream_artifact_digests` is the spec/documentation display label only;
  persisted state continues to use `upstream_digests`. This avoids any
  persisted-schema migration, alias, or read/write compatibility shim — the
  existing storage is reused with no on-disk change. New per-class provenance
  fields (`owned_snippet_digests`, `referenced_snippet_digests`,
  `dependency_set_at_write`, `produced_at`) are pure additions to the
  artifact lifecycle entry (default-empty) and follow the same
  backward-compat rule: absent values resolve to `pending` per the fail-safe
  contract, so old state loads cleanly.
- `owned_snippet_digests` — map of `{snippet_id: digest}` for every snippet
  the Todo owns via its `delivered_by` membership at write time.
- `referenced_snippet_digests` — map of `{snippet_id: digest}` for every
  snippet the artifact references by id (extracted from the
  validator-accepted inline reference forms — `@<HOME>/.teleclaude/docs/<id-path>.md`
  for global snippets and `@docs/<id-path>.md` for project snippets. The
  extractor maps each accepted reference to its canonical snippet ID and
  the ID is the key into the digest map. Forms outside the validator's
  accepted set are not tracked, by design — references in the body, not
  by literal path substring).
- `dependency_set_at_write` — list of `{dep_slug, status}` tuples for the
  Todo's **immediate** `after` set at write time. Shallow only; see the
  "dependency-graph class is shallow, not transitive" caveat below.
- `produced_at` — UTC wall-clock timestamp.

Snippet digests are content hashes of the snippet body (excluding
frontmatter `delivered_by` churn so a target → actual flip on an unrelated
slug does not trigger drift).

### Per-artifact coverage matrix

| Artifact               | code | upstream-artifact                  | owned-snippet | upstream-snippet | dependency-graph | age |
| ---------------------- | :--: | ---------------------------------- | :-----------: | :--------------: | :--------------: | :-: |
| `input`                |  ✓   | _(none)_                           |   _(none)_    |        ✓         |        ✓         |  ✓  |
| `prd`                  |  ✓   | `input`                            |       ✓       |        ✓         |        ✓         |  ✓  |
| `architecture` (index) |  ✓   | `prd`                              |       ✓       |        ✓         |        ✓         |  ✓  |
| `implementation-plan`  |  ✓   | `architecture`, `prd`, `diagnosis` |   _(none)_    |        ✓         |        ✓         |  ✓  |
| `diagnosis`            |  ✓   | `input`                            |       ✓       |        ✓         |        ✓         |  ✓  |

The `code` column is contract-scoped. Matrix membership stays unchanged so the
same class is evaluated for every tracked artifact, but today only the
`implementation-plan` declares a `referenced-paths` contract block. All other
artifacts have an empty code surface unless a future contract explicitly gives
them one, and empty-surface code drift derives fresh.

`owned-snippet` applies to artifacts whose authoring phase writes doc
snippets directly (intake → feature spec; architecture → domain/design
snippets). `implementation-plan` does not author durable snippets, so it
has no owned-snippet class.

### Stamp scoping — the evidence anchor

A `--drift-reviewed <artifact> cosmetic|substantive <reason>` stamp records
the **evidence anchor** at which the verdict was made:

- `head_sha_at_review` — the HEAD SHA when the analyzer ran.
- `upstream_digests_at_review` — the upstream artifact digest map at review.
- `snippet_digests_at_review` — the snippet digest map at review.
- `dep_set_at_review` — the dependency-set snapshot at review.

On every prepare call, the per-artifact drift derivation first compares
**current evidence** against the stamp's anchor for the same class. If any
anchor field has moved (e.g., HEAD advanced past `head_sha_at_review` AND a
new overlap exists in `referenced_paths`), the stamp is treated as
**expired-for-class** and the class re-derives from scratch. A
`substantive` stamp does not expire — it has already routed back to
re-derivation. A `cosmetic` stamp expires lazily, only when new evidence
arrives.

This is the contract that closes the "permanent cosmetic stamp" gap: a
cosmetic verdict at SHA X cannot mask substantive drift introduced at
SHA Y > X.

### State machine integration

Drift is derived inside the existing `BLOCKED` lifecycle phase, not as a
new phase:

- On every `telec todo prepare {slug}` call, after the basic phase
  derivation, the machine computes drift status for every present tracked
  artifact across every applicable class.
- If any artifact's overall drift status is `pending`, the machine routes
  to the BLOCKED branch and emits a `/next-drift-analyze` dispatch
  instruction, listing the artifacts and classes pending review.
- If any artifact's drift status is `substantive`, the machine clears the
  artifact's review verdict (and every downstream artifact's review
  verdict) and routes back to the artifact's drafting phase.
- If every artifact's drift status is `fresh` or `cosmetic`, the machine
  derives `PREPARED` (subject to the other gates) and the chain proceeds.

The `/next-drift-analyze` worker reads the pending classes per artifact,
inspects the appropriate evidence for every pending class, and stamps
**one verdict per artifact** (the per-artifact stamp shape with multi-
dimensional evidence anchor; the CLI signature
`--drift-reviewed <artifact> <verdict> <reason>` is unchanged). The
verdict collapses across all pending classes by the rule "substantive on
any class → substantive overall; otherwise cosmetic." The reason text
names each evaluated class and its per-class finding so the audit trail
preserves the per-class detail. Anchor expiry on the next derivation is
checked per class against the recorded multi-dimensional anchor; any
single dimension moving past its anchor re-pends that class. The
orchestrator re-enters the state machine when the worker idles.

### Work-entry re-derivation

The work state machine calls the same derivation function at its entry
boundary, BEFORE the `prepared → build_started` handoff, BEFORE worktree
preparation, and BEFORE any origin/main merge into the worktree. The call
order in work entry becomes:

1. Resolve the slug from the todo list or argument.
2. Validate work preconditions that do not require a worktree
   (stash debt check, etc.).
3. **Read state from the workflow context** (moved earlier — currently
   this happens inside the dispatch loop).
4. **Call the shared drift derivation against repo-root state, NOT against
   any worktree** (drift derivation compares against `origin/main` HEAD and
   persisted provenance; no worktree is required).
5. If any artifact's collapsed drift status is `pending` or
   `substantive`: return the bounce-to-prepare script. **No worktree
   created. No state mutated. No worker dispatched.**
6. Only when every artifact's collapsed drift status is `fresh` or
   `cosmetic` (with a valid anchor): proceed with worktree preparation,
   the origin/main merge, the `prepared → build_started` handoff, and
   the dispatch loop.

The PRD's "does not create or touch the worktree" constraint requires
this ordering — the state read and drift pre-check happen ahead of any
worktree work.

Detail of the call itself:

- The shared function takes the slug, the loaded todo state, the repo
  root, the workflow context handle for dependency lookup, and a
  snippet-digest callable — explicit injection rather than hidden
  imports. Both the prepare BLOCKED branch and the work entry path call
  it with the same evidence-loading rules so there is one source of
  truth for drift status.
- When the shared derivation reports any tracked artifact's collapsed
  status as `pending` or `substantive`, work does NOT advance
  `lifecycle_phase`, does NOT create or touch the worktree, and does NOT
  dispatch any worker on the current call. It returns an orchestrator
  script naming the affected artifacts and instructing the orchestrator
  to call `telec todo prepare {slug}` to resolve drift.
- When every tracked artifact's collapsed status is `fresh` or `cosmetic`
  (with a valid evidence anchor), work proceeds with the existing
  `prepared → build_started` handoff, worktree creation, and builder
  dispatch.

The work entry path inherits the same fail-safe defaults as prepare:
missing provenance for an applicable class resolves to `pending` and
forces the bounce, so first-time work entry on a PREPARED todo whose
artifacts pre-date the extended provenance schema reliably routes through
the analyzer to establish fresh evidence anchors.

Continuation across the bounce is the existing orchestrator-script
contract. The prepare BLOCKED branch's drift-analyze dispatch, the
analyzer's stamp, the next prepare call's PREPARED derivation, and the
PREPARED terminal's lineage-conditioned resume — the bounced work orchestrator
resumes `telec todo work {slug}` — combine into a
single loop: work bounces to prepare, prepare resolves drift, prepare
bounces back to work, work re-derives drift, and the second derivation
either proceeds (cosmetic anchor now valid) or re-pends (genuinely
unresolvable drift, exposed as a hard blocker the human can inspect).

### Re-derivation contract

When the drift analyzer stamps `substantive` for artifact X on any class:

- X's review verdict is cleared (architecture-review or plan-review, as
  applicable).
- Every downstream artifact's review verdict is cleared (a substantive
  PRD drift invalidates architecture and plan; substantive architecture
  drift invalidates plan).
- The PRD-approved gate is **not** re-opened by drift on the PRD's
  downstream evidence (code/snippets/deps). It IS re-opened when the PRD
  artifact itself is rewritten (its live digest diverges from
  `approved_digest`) or when a substantive **upstream-artifact** drift —
  the human re-engaging with intent-level `input` refinement — is stamped
  for the PRD (see `prepare-flow#refinement`). The upstream-drift re-open
  supersedes a legacy approval that bound no `approved_digest` and one that
  recorded no `approved_at`; a re-approval whose `approved_at` is at or
  after the drift stamp resolves it.
- The drift-reviewed stamps for X are cleared (so re-derived X earns a
  fresh evidence anchor on its next analyze pass).
- Routing returns to X's **drafting** phase, not its review phase, even
  though X's artifact is still present on disk.

The phase-derivation mechanism that distinguishes "verdict cleared by
substantive drift (needs re-draft)" from "verdict never approved (needs
first review)" or "verdict cleared by reviewer needs_work (needs author
fix inside the existing review loop)" is an explicit marker on the
review state:

- The verdict-state record (for `architecture_review` and `plan_review`)
  gains a `cleared_by_substantive_drift` boolean (default `false`). The
  marker is set in the same commit that clears the verdict due to a
  substantive `--drift-reviewed` stamp.
- The phase-derivation helpers for the feature and plan-only lanes
  consult the marker before treating an artifact-present + unapproved-verdict
  state as "ready for review." When the marker is `true`, derivation
  returns the corresponding `*_DRAFTING` phase. When `false`, derivation
  returns `*_REVIEW` (existing behavior).
- The marker is cleared automatically when the artifact is rewritten
  (`telec todo artifacts write` — same boundary that re-captures
  provenance and clears drift-reviewed stamps for the artifact). After
  the rewrite, the next prepare call sees a present artifact, a cleared
  verdict, and a cleared marker — which routes to the review phase for
  a fresh review, on the new artifact.

The marker does not affect any existing flow that does not involve
substantive drift; default `false` makes the derivation behavior
identical to the pre-change behavior whenever drift has not fired.

When the drift analyzer stamps `cosmetic`, no downstream invalidation
occurs; the chain continues. The cosmetic stamp remains valid until its
evidence anchor is exceeded.

### Use cases

```gherkin
Scenario: code drift detected, classified cosmetic, then re-evaluated after further drift
  Given a Todo at lifecycle_phase=plan_review with an approved plan
  And the plan's referenced_paths include a tracked module
  And origin/main HEAD has advanced past the plan's codebase_sha_at_write
  And the new commits touch the tracked module
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine reports drift.implementation-plan = pending (class: code)
  And dispatches the drift-analyze worker
  And the worker stamps "telec todo stamp my-feature --drift-reviewed implementation-plan cosmetic '<reason>'"
  And the cosmetic stamp records head_sha_at_review = current HEAD
  And the next prepare call advances to PREPARED
  And when origin/main HEAD later advances further AND introduces a new overlapping change
  Then the cosmetic stamp is treated as expired-for-class
  And drift.implementation-plan returns to pending
  And the drift-analyze worker is dispatched again
```

```gherkin
Scenario: upstream-artifact drift invalidates downstream review
  Given a Todo at lifecycle_phase=plan_review with an approved plan and an approved architecture
  And the architecture artifact recorded upstream_artifact_digests[prd] = "<old-prd-digest>"
  When the human refines the PRD via intake re-entry and writes a new PRD
  Then on the next "telec todo prepare my-feature" call
  And the machine reports drift.architecture = pending (class: upstream-artifact)
  And dispatches the drift-analyze worker
  And the analyzer stamps "--drift-reviewed architecture substantive '<reason>'"
  Then the architecture review verdict is cleared
  And the plan review verdict is cleared
  And the machine routes back to architecture_drafting
```

#### UC-WDD1: Implementation-plan upstream derivation is fresh when diagnosis matches

```gherkin
Scenario: implementation-plan upstream derivation is fresh when diagnosis matches
  Given a bug Todo whose implementation-plan recorded upstream_digests[diagnosis] = "<diagnosis-digest>"
  And the current diagnosis artifact digest is "<diagnosis-digest>"
  And the implementation-plan has a cosmetic drift-reviewed stamp whose upstream_digests_at_review matches current upstream digests
  When upstream-artifact drift is derived for implementation-plan
  Then drift derivation reports implementation-plan = fresh
  And implementation-plan has no pending upstream-artifact drift
```

#### UC-WDD2: Diagnosis rewrite drifts the bug implementation-plan

```gherkin
Scenario: diagnosis rewrite drifts the bug implementation-plan
  Given a prepared bug Todo whose implementation-plan recorded upstream_digests[diagnosis] = "<old-diagnosis-digest>"
  When the diagnosis artifact is rewritten and its current digest becomes "<new-diagnosis-digest>"
  Then drift derivation reports drift.implementation-plan = pending
  And the pending class is upstream-artifact
```

#### UC-WDD3: Prepared bug with matching diagnosis upstream stays terminal

```gherkin
Scenario: prepared bug with matching diagnosis upstream stays terminal
  Given a bug Todo at lifecycle_phase=prepared with an approved implementation-plan
  And the implementation-plan recorded upstream_digests[diagnosis] = "<diagnosis-digest>"
  And the current diagnosis artifact digest is "<diagnosis-digest>"
  And the implementation-plan has a cosmetic drift-reviewed stamp whose upstream_digests_at_review matches current upstream digests
  When the orchestrator calls "telec todo prepare my-bug"
  Then drift derivation reports no pending upstream-artifact drift on implementation-plan
  And the prepare machine settles at prepared
  And no drift-analyzer worker is re-dispatched for implementation-plan
```

#### UC-WDD4: Diagnosis upstream derivation detects input rewrites

```gherkin
Scenario: diagnosis upstream derivation detects input rewrites
  Given a bug Todo whose diagnosis recorded upstream_digests[input] = "<old-input-digest>"
  When the input artifact is rewritten and its current digest becomes "<new-input-digest>"
  Then drift derivation reports drift.diagnosis = pending
  And the pending class is upstream-artifact
```

#### UC-WDD5: Upstream topology is shared by provenance, stamps, and drift derivation

```gherkin
Scenario: upstream topology is shared by provenance, stamps, and drift derivation
  Given a bug Todo with input, diagnosis, and implementation-plan artifacts
  When provenance is recorded, a drift-reviewed stamp is anchored, and upstream-artifact drift is derived
  Then all three surfaces evaluate implementation-plan against prd, architecture, and diagnosis
  And all three surfaces evaluate diagnosis against input
```

#### UC-WDD6: Work entry accepts a prepared bug when diagnosis upstream evidence matches

```gherkin
Scenario: work entry accepts a prepared bug when diagnosis upstream evidence matches
  Given a bug Todo at lifecycle_phase=prepared with an approved implementation-plan
  And the implementation-plan recorded upstream_digests[diagnosis] = "<diagnosis-digest>"
  And the current diagnosis artifact digest is "<diagnosis-digest>"
  And the implementation-plan has a cosmetic drift-reviewed stamp whose upstream_digests_at_review matches current upstream digests
  When the orchestrator calls "telec todo work my-bug"
  Then work entry does not return WORK_ENTRY_DRIFT
  And work entry does not report PENDING_DRIFT for implementation-plan
  And the work machine proceeds to the normal build-start dispatch path
```

```gherkin
Scenario: owned-snippet drift on a target architecture snippet
  Given a Todo at lifecycle_phase=plan_review with an approved architecture
  And the architecture index recorded owned_snippet_digests["project/spec/domain/workflow"] = "<digest-A>"
  And a sibling delivery has since edited docs/project/spec/domain/workflow.md, producing "<digest-B>"
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine reports drift.architecture = pending (class: owned-snippet)
  And dispatches the drift-analyze worker with the pending class named
  And the analyzer reads the snippet diff and the architecture index
  And classifies the change as substantive or cosmetic
  And stamps "--drift-reviewed architecture <verdict> '<reason>'"
```

```gherkin
Scenario: upstream-snippet drift on a referenced domain spec
  Given a Todo whose implementation-plan references "@docs/project/spec/domain/context.md" (validator-accepted project reference resolving to canonical snippet ID "project/spec/domain/context")
  And the plan recorded referenced_snippet_digests["project/spec/domain/context"] = "<digest-A>"
  And docs/project/spec/domain/context.md has since been edited, producing "<digest-B>"
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine reports drift.implementation-plan = pending (class: upstream-snippet)
  And dispatches the drift-analyze worker
  And the worker classifies and stamps the verdict
```

#### UC-WDD7: Active dependency delivery is not dependency-graph drift

```gherkin
Scenario: dependency-graph does not drift when an active upstream dep delivers
  Given a Todo with "after: [feature-X]" and an approved plan
  And the plan recorded dependency_set_at_write = [{feature-X, status: active}]
  And feature-X has since reached status = delivered
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine reports no pending dependency-graph drift on implementation-plan
  And no drift-analyzer worker is dispatched for the dependency-graph class
```

#### UC-WDD8: Icebox and membership changes remain dependency-graph drift

```gherkin
Scenario: dependency-graph still drifts for icebox status and direct dependency membership changes
  Given a Todo with an approved plan
  And the plan recorded dependency_set_at_write for the Todo's direct dependencies
  When a direct dependency changes between icebox and delivered
  Then the machine reports drift.implementation-plan = pending (class: dependency-graph)
  When a direct dependency is added to or removed from the Todo's immediate after set
  Then the machine reports drift.implementation-plan = pending (class: dependency-graph)
```

#### UC-WDD9: Prepare hydration refreshes stale referenced paths without stamp churn

```gherkin
Scenario: prepare hydration self-heals stale greedy referenced paths
  Given a prepared Todo whose implementation-plan has complete async provenance
  And the stored referenced_paths include stale greedy prose matches
  And the current implementation-plan body declares no referenced-paths contract block
  And the implementation-plan has an existing drift-reviewed stamp
  When the orchestrator calls "telec todo prepare my-feature"
  Then prepare hydration refreshes referenced_paths from the current artifact body
  And referenced_paths becomes empty without changing produced_at, dependency provenance, or drift-reviewed stamps
  And code drift for implementation-plan derives fresh
  And a delivered direct dependency that was recorded active does not create dependency-graph drift
```

```gherkin
Scenario: dependency-graph drift after an upstream dep delivers
  Given a Todo with "after: [feature-X]" and an approved plan
  And the plan recorded dependency_set_at_write = [{feature-X, status: held}]
  And feature-X has since reached status = delivered
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine reports drift.implementation-plan = pending (class: dependency-graph)
  And the drift-analyze worker is dispatched with the dep-graph class named
  And the worker stamps cosmetic or substantive based on whether the dep delivery affects plan tasks
```

```gherkin
Scenario: age drift on a long-paused Todo
  Given a Todo at lifecycle_phase=plan_review approved 90 days ago
  And the configured age window for implementation-plan is 30 days
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine reports drift.implementation-plan = pending (class: age)
  And dispatches the drift-analyze worker
  And the worker re-grounds against current code/snippets/deps and stamps a verdict per class
```

```gherkin
Scenario: missing provenance is fail-safe
  Given a Todo whose architecture artifact pre-dates the provenance schema
  And owned_snippet_digests is empty for that artifact
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine treats owned-snippet drift as pending
  And the drift-analyze worker is dispatched to establish a fresh evidence anchor
  And the analyzer stamps cosmetic only after reading the snippets and grounding the verdict
```

```gherkin
Scenario: cross-class drift collapses to the most blocking status
  Given an architecture artifact with code drift = cosmetic (stamped, anchor current)
  And upstream-artifact drift = substantive (PRD was rewritten)
  When the orchestrator calls "telec todo prepare my-feature"
  Then the overall architecture drift status is substantive
  And the architecture review verdict is cleared
  And the plan review verdict is cleared
  And the machine routes back to architecture_drafting
```

```gherkin
Scenario: work entry bounces to prepare on pending drift, then resumes autonomously
  Given a Todo at lifecycle_phase=prepared with an approved implementation-plan
  And the plan's owned_snippet_digests no longer match current truth
    (a sibling delivery edited a referenced domain spec)
  When the orchestrator calls "telec todo work my-feature"
  Then drift derivation reports drift.implementation-plan = pending (class: owned-snippet)
  And the work machine returns a script:
    "Drift detected on implementation-plan. Call `telec todo prepare my-feature` to resolve."
  And the work machine does NOT advance lifecycle_phase
  And the work machine does NOT create or touch the worktree
  And the orchestrator follows the script and calls "telec todo prepare my-feature"
  And the prepare BLOCKED branch dispatches the next-drift-analyze worker
  And the analyzer stamps "--drift-reviewed implementation-plan cosmetic '<reason>'"
  And the cosmetic stamp records the current evidence anchor
  And the next "telec todo prepare my-feature" call derives PREPARED
  And the PREPARED terminal's lineage-conditioned reminder resumes the bounced work orchestrator at "telec todo work my-feature"
  And the orchestrator follows that script
  And work re-runs drift derivation, observes fresh/valid-anchor status
  And proceeds with worktree creation and next-build dispatch
  And no human gate fires anywhere in the round-trip
```

```gherkin
Scenario: work entry bounces on substantive drift, re-derivation re-converges
  Given a Todo at lifecycle_phase=prepared with an approved plan and an approved architecture
  And the PRD has been refined since architecture was approved
    (upstream-artifact drift on architecture)
  When the orchestrator calls "telec todo work my-feature"
  Then drift derivation reports drift.architecture = pending
  And work returns the bounce-to-prepare script
  And the orchestrator follows the script
  And the prepare BLOCKED branch dispatches the analyzer
  And the analyzer stamps "--drift-reviewed architecture substantive '<reason>'"
  Then the architecture review verdict is cleared
  And the plan review verdict is cleared
  And the prepare machine routes back to architecture_drafting
  And the existing prepare chain re-derives architecture and plan, re-reviews each, reaches PREPARED
  And the PREPARED terminal's lineage-conditioned reminder resumes the bounced work orchestrator at "telec todo work my-feature"
  And work re-runs drift derivation, observes fresh status, and proceeds
  And no human gate fires in the substantive round-trip (intent-level PRD refinement is the only human-gated path and is orthogonal)
```

```gherkin
Scenario: re-writing an artifact clears its drift stamps
  Given an artifact with a cosmetic drift-reviewed stamp on the code class
  When the artifact is rewritten via "telec todo artifacts write"
  Then the artifact's provenance fields are re-captured at the new write
  And all drift-reviewed stamps for that artifact are cleared
  And drift derivation starts from scratch on the next prepare call
```

### Cross-context references

- `agent_runtime` — the `/next-drift-analyze` worker session is dispatched
  via the same `agent_runtime.session.started` event shape as
  architecture/plan reviewers. Reuse-or-spawn matching applies per
  `prepare-state-machine#reviewer-reuse`.
- `integration` — `origin/main` advances triggered by integration land in
  the SHA comparison used by the code class. The drift contract is
  unaffected by whether the source of the advance is the current
  orchestrator's own work or a sibling delivery.
- `knowledge` — snippet digests are captured against the canonical doc
  layer (`docs/`), the same source `telec docs get` reads. Snippet
  reference extraction recognizes the validator-accepted inline forms
  (`@<HOME>/.teleclaude/docs/<id-path>.md` for global and
  `@docs/<id-path>.md` for project) and maps each to its canonical
  snippet ID. The ID is the key into the digest map.
- `session_ledger` — the resolved session principal for each
  `--drift-reviewed` stamp is recorded so the analyzer's verdict can be
  audited and so a non-analyzer session cannot author a drift verdict.

## Allowed values

- **Drift class:** `code`, `upstream-artifact`, `owned-snippet`,
  `upstream-snippet`, `dependency-graph`, `age`.
- **Drift status:** `fresh`, `pending`, `cosmetic`, `substantive`. Priority
  for collapse to per-artifact status: `substantive` > `pending` >
  `cosmetic` > `fresh`.
- **Drift-reviewed verdict (stamp):** `cosmetic`, `substantive`.
- **Age window:** configurable per artifact kind in project config.
  **Architecture-resolved default: disabled per project until explicit
  config is set.** The age class is opt-in — projects that do not
  configure an age window for an artifact kind pay no age cost on their
  prepare/work cycles. When a project opts in, the recommended starting
  values are `30 days` for `implementation-plan` and `architecture`,
  `60 days` for `prd`, `90 days` for `input`; the project owner chooses
  the actual values. `0` or unset is the disabled state. This avoids
  surprising all in-flight todos with an age-pending sweep on first
  prepare/work after this delivery merges; teams enable the class
  deliberately when they want freshness pressure.

## Known caveats

- **Fail-safe is the contract, not the exception.** Missing provenance,
  unreadable referenced paths, unresolvable upstream snippets, or rename
  detection failures all produce `pending`, not `fresh`. The analyzer is
  the only path back to a `cosmetic` verdict.
- **Cosmetic stamps are scoped, not permanent.** A cosmetic verdict is
  only valid against the evidence anchor it was made at. When evidence
  moves past the anchor in a way that introduces NEW drift, the verdict
  expires and the class re-pends. The analyzer must be re-run.
- **Substantive stamps do not "carry over" to a re-derived artifact.**
  When substantive drift forces re-derivation, the rewrite clears the
  drift stamps. The next analyze pass establishes a fresh anchor against
  current evidence.
- **Snippet digests exclude `delivered_by` frontmatter churn.** When a
  sibling delivery flips a snippet's `delivered_by` (`target` → `actual`
  bookkeeping), the body digest is unchanged and no drift fires. This
  prevents lifecycle-bookkeeping edits from invalidating unrelated
  artifacts.
- **The dependency-graph class is shallow, not transitive.** It detects
  changes to the Todo's immediate `after` set and each direct dep's
  status. Deep transitive changes (a dep's dep changed) are not tracked
  — the immediate dep's own drift detection is responsible for surfacing
  those upward when it is prepared.
- **Delivered direct deps normalize to active.** In the dependency-graph
  class, a direct dependency moving from `active` to `delivered` is expected
  forward progress and does not register drift; any code impact from that
  delivery is covered by the code class scoped to the plan's declared
  `referenced-paths` contract. Status changes involving `icebox` and direct
  dep add/remove still register drift.
- **Age drift is policy-driven and disabled by default per project until
  the config defaults are set.** Projects that do not configure age
  windows do not pay the age class on their prepare cycles.
- **Drift detection runs on `origin/main`, not on the orchestrator's
  worktree.** Prepare runs on repo-root main with no worktree. The SHA
  compared against `codebase_sha_at_write` is `origin/main` HEAD, not
  local `HEAD` of any sibling worktree.
- **Reference extraction has two distinct mechanisms.** `referenced_paths`
  uses literal path-substring matching against the project's tracked
  files (current behavior, preserved). `referenced_snippet_digests` uses
  reference extraction against the doc snippet index that recognizes the
  validator-accepted inline forms (`@<HOME>/.teleclaude/docs/...` and
  `@docs/...`) and resolves them to canonical snippet IDs (new). The two
  surfaces do not overlap.
- **Reference extraction has two distinct mechanisms.** `referenced_paths`
  is a pure projection of the implementation-plan artifact body: the
  sorted, de-duplicated path lines inside its single
  ` ```referenced-paths ` contract block. It does not scan prose and does
  not validate paths against tracked files, so generated-path warnings or
  grounding notes are not drift surfaces unless the plan declares them in the
  block. `referenced_snippet_digests` still uses reference extraction against
  the doc snippet index that recognizes the validator-accepted inline forms
  (`@<HOME>/.teleclaude/docs/...` and `@docs/...`) and resolves them to
  canonical snippet IDs. The two surfaces do not overlap.
- **`referenced_paths` refreshes on prepare hydration.** Because the field is
  now derived only from the artifact body, prepare hydration refreshes that
  projection without rewriting the artifact's other provenance. Extractor
  semantics changes self-heal stale stored values on the next prepare call
  without resetting `produced_at`, snippet/dependency provenance, or drift
  review stamps.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/drift-analyze.md
- docs/project/spec/feature/workflow/prepare-state-machine.md
- docs/project/design/architecture/prepare-flow.md
- docs/project/spec/feature/workflow/state-stamping.md
