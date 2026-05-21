---
id: 'project/spec/feature/workflow/drift-detection'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Detect when a Todo''s prepared artifacts and authored doc snippets no longer reflect current truth — code surfaces, upstream artifacts, owned/referenced doc snippets, dependency graph, and age — and force re-grounding before the Todo may reach prepared.'
status: 'target'
delivered_by:
  - drift-detection-consolidation
applies_to: 'both'
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
places (code, sibling artifacts, doc snippets, the roadmap dependency
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
PREPARED terminal script line tells the orchestrator to call
`telec todo work {slug}` next, closing the loop without a human gate on
either cosmetic or substantive verdicts.

## Canonical fields

### Drift classes (taxonomy)

Each tracked artifact is evaluated against every applicable class on every
prepare call. The overall artifact drift status is the **most blocking**
status across its classes (`substantive` > `pending` > `cosmetic` > `fresh`).

| Class                  | Evidence checked                                                                                                | When pending                                                                                                |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **code**               | Artifact's `codebase_sha_at_write` vs current `origin/main` HEAD, scoped to `referenced_paths`.                 | HEAD has moved AND at least one changed path overlaps `referenced_paths`.                                   |
| **upstream-artifact**  | Digest of each upstream artifact (e.g., PRD digest at the time architecture was written) vs current digest.     | Any upstream artifact has been rewritten since this artifact was authored.                                  |
| **owned-snippet**      | Digest of each doc snippet the Todo owns via `delivered_by` (recorded at artifact write time) vs current digest. | An owned snippet was edited outside this prepare flow since the artifact was authored.                      |
| **upstream-snippet**   | Digest of each non-owned doc snippet the artifact references by ID, recorded at write time, vs current digest. | A referenced snippet's content has changed since the reference was recorded.                                |
| **dependency-graph**   | The Todo's immediate `after` set and each direct dep's roadmap status at write time vs current. Shallow — not transitive. | The immediate dep set changed (added/removed) OR any direct dep's roadmap status flipped (e.g., a HELD dep is now DELIVERED). |
| **age** _(policy)_     | Artifact `produced_at` vs configurable freshness window.                                                        | `produced_at` is older than the configured window for the artifact kind.                                    |

Code drift is the existing v1 behavior. The other classes are new in this
spec; their provenance fields are listed below.

### Provenance recorded per artifact

When a tracked artifact is written (`telec todo artifacts write`), the
state-stamping boundary captures all evidence needed for every drift class
that applies to it. Per-artifact provenance:

- `codebase_sha_at_write` — `origin/main` HEAD SHA at write time.
- `referenced_paths` — tracked repo paths mentioned in the artifact body.
- `upstream_artifact_digests` — map of `{upstream_artifact_name: digest}` for
  every artifact this artifact derives from (per artifact-kind table below).
  **Field consolidation:** the existing `ArtifactEntry.upstream_digests`
  field (`teleclaude/types/todos.py:150`) carries the same provenance
  concept today, populated by `_apply_readiness_stamp` and
  `_capture_upstream_digests`. The implementation plan renames it in place
  to `upstream_artifact_digests` (preferred — single canonical field, no
  alias) OR keeps `upstream_digests` as the storage field and treats
  `upstream_artifact_digests` as the spec-side display name (acceptable
  fallback if call-site renames are too widespread to land in one todo).
  The fail-safe drift behavior is unchanged either way: an artifact with
  an empty digest map for an applicable class derives to `pending` and
  routes the analyzer to establish a fresh anchor. The plan picks the
  rename strategy; this spec accepts either as a stable target.
- `owned_snippet_digests` — map of `{snippet_id: digest}` for every snippet
  the Todo owns via its `delivered_by` membership at write time.
- `referenced_snippet_digests` — map of `{snippet_id: digest}` for every
  snippet the artifact references by id (extracted from `@snippet/id`
  references in the body, not by literal path substring).
- `dependency_set_at_write` — list of `{dep_slug, roadmap_status}` tuples
  for the Todo's **immediate** `after` set at write time. Shallow only;
  see the "dependency-graph class is shallow, not transitive" caveat
  below.
- `produced_at` — UTC wall-clock timestamp.

Snippet digests are content hashes of the snippet body (excluding
frontmatter `delivered_by` churn so a target → actual flip on an unrelated
slug does not trigger drift).

### Per-artifact coverage matrix

| Artifact                | code | upstream-artifact      | owned-snippet  | upstream-snippet | dependency-graph | age |
| ----------------------- | :--: | ---------------------- | :------------: | :--------------: | :--------------: | :-: |
| `input`                 |  ✓   | _(none)_               |  _(none)_      |        ✓         |        ✓         |  ✓  |
| `prd`                   |  ✓   | `input`                |       ✓        |        ✓         |        ✓         |  ✓  |
| `architecture` (index)  |  ✓   | `prd`                  |       ✓        |        ✓         |        ✓         |  ✓  |
| `implementation-plan`   |  ✓   | `architecture`, `prd`  |  _(none)_      |        ✓         |        ✓         |  ✓  |

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

On every prepare call, `derive_artifact_drift` first compares **current
evidence** against the stamp's anchor for the same class. If any anchor
field has moved (e.g., HEAD advanced past `head_sha_at_review` AND a new
overlap exists in `referenced_paths`), the stamp is treated as
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
boundary, BEFORE the `prepared → build_started` handoff, BEFORE
`_ensure_worktree_ready`, and BEFORE any origin/main merge into the
worktree. Concretely, the call order in `next_work` becomes:

1. `_resolve_work_slug` — resolve the slug from roadmap or argument.
2. `_validate_work_preconditions` — preconditions that do not require
   a worktree (stash debt check, etc.).
3. **Read state from `todos_db`** (moved earlier — currently this happens
   inside the dispatch loop).
4. **`derive_lifecycle_drift(state, repo_root=cwd)`** — drift pre-check
   against repo-root state, NOT against any worktree (drift derivation
   compares against `origin/main` HEAD and persisted provenance; no
   worktree is required).
5. If any artifact's collapsed drift status is `pending` or
   `substantive`: return the bounce-to-prepare script. **No worktree
   created. No state mutated. No worker dispatched.**
6. Only when every artifact's collapsed drift status is `fresh` or
   `cosmetic` (with a valid anchor): proceed with
   `_ensure_worktree_ready`, the origin/main merge, the
   `_advance_prepared_to_build_started` handoff, and the dispatch loop.

The PRD's "does not create or touch the worktree" constraint requires
this ordering — the existing implementation's `_ensure_worktree_ready`
call happens before any state read, which is incompatible with the
target contract. The implementation plan must move the state read and
drift pre-check ahead of `_ensure_worktree_ready`.

Detail of the call itself:

- The shared function is `derive_lifecycle_drift(model, *, repo_root)` in
  `teleclaude/core/next_machine/lifecycle.py` (renamed from
  `derive_prepare_drift`; signature unchanged). Both the prepare BLOCKED
  branch and the work entry path call it with the same evidence-loading
  rules so there is one source of truth for drift status.
- When `derive_lifecycle_drift` reports any tracked artifact's collapsed
  status as `pending` or `substantive`, work does NOT advance
  `lifecycle_phase`, does NOT create or touch the worktree, and does NOT
  dispatch any worker on the current call. It returns an orchestrator
  script naming the affected artifacts and instructing the orchestrator
  to call `telec todo prepare {slug}` to resolve drift.
- When every tracked artifact's collapsed status is `fresh` or `cosmetic`
  (with a valid evidence anchor), work proceeds with the existing
  `_advance_prepared_to_build_started` handoff, worktree creation, and
  builder dispatch.

The work entry path inherits the same fail-safe defaults as prepare:
missing provenance for an applicable class resolves to `pending` and
forces the bounce, so first-time work entry on a PREPARED todo whose
artifacts pre-date the extended provenance schema reliably routes through
the analyzer to establish fresh evidence anchors.

Continuation across the bounce is the existing orchestrator-script
contract. The prepare BLOCKED branch's drift-analyze dispatch, the
analyzer's stamp, the next prepare call's PREPARED derivation, and the
PREPARED terminal script's `telec todo work {slug}` tail combine into a
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
- The PRD-approved stamp is **not** cleared by drift on the PRD's
  downstream evidence (code/snippets/deps). It IS cleared when the PRD
  itself is rewritten or when the human re-engages with intent-level
  refinement (see `prepare-flow#refinement`).
- The drift-reviewed stamps for X are cleared (so re-derived X earns a
  fresh evidence anchor on its next analyze pass).
- Routing returns to X's **drafting** phase, not its review phase, even
  though X's artifact is still present on disk.

The phase-derivation mechanism that distinguishes "verdict cleared by
substantive drift (needs re-draft)" from "verdict never approved (needs
first review)" or "verdict cleared by reviewer needs_work (needs author
fix inside the existing review loop)" is an explicit marker on the
review state:

- `ReviewVerdictState` (the typed model for `architecture_review` and
  `plan_review`) gains a `cleared_by_substantive_drift: bool` field
  (default `false`). The marker is set in the same `StateWriter` commit
  that clears the verdict due to a substantive `--drift-reviewed`
  stamp.
- `_feature_phase` and `_plan_only_phase` in
  `teleclaude/core/next_machine/lifecycle.py` consult the marker
  before treating an artifact-present + unapproved-verdict state as
  "ready for review." When the marker is `true`, derivation returns the
  corresponding `*_DRAFTING` phase. When `false`, derivation returns
  `*_REVIEW` (existing behavior).
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
  And the plan's referenced_paths include "teleclaude/services/foo.py"
  And origin/main HEAD has advanced past the plan's codebase_sha_at_write
  And the new commits touch "teleclaude/services/foo.py"
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
  And the machine routes back to architecture_drafting via _load_procedure
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
  Given a Todo whose implementation-plan references "@snippet/project/spec/domain/context"
  And the plan recorded referenced_snippet_digests["project/spec/domain/context"] = "<digest-A>"
  And docs/project/spec/domain/context.md has since been edited, producing "<digest-B>"
  When the orchestrator calls "telec todo prepare my-feature"
  Then the machine reports drift.implementation-plan = pending (class: upstream-snippet)
  And dispatches the drift-analyze worker
  And the worker classifies and stamps the verdict
```

```gherkin
Scenario: dependency-graph drift after an upstream dep delivers
  Given a Todo with "after: [feature-X]" and an approved plan
  And the plan recorded dependency_set_at_write = [{feature-X, status: held}]
  And feature-X has since reached roadmap status = delivered
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
  Then derive_lifecycle_drift reports drift.implementation-plan = pending (class: owned-snippet)
  And the work machine returns a script:
    "Drift detected on implementation-plan. Call `telec todo prepare my-feature` to resolve."
  And the work machine does NOT advance lifecycle_phase
  And the work machine does NOT create or touch the worktree
  And the orchestrator follows the script and calls "telec todo prepare my-feature"
  And the prepare BLOCKED branch dispatches the next-drift-analyze worker
  And the analyzer stamps "--drift-reviewed implementation-plan cosmetic '<reason>'"
  And the cosmetic stamp records the current evidence anchor
  And the next "telec todo prepare my-feature" call derives PREPARED
  And the PREPARED terminal script tells the orchestrator to call "telec todo work my-feature"
  And the orchestrator follows that script
  And work re-runs derive_lifecycle_drift, observes fresh/valid-anchor status
  And proceeds with worktree creation and next-build dispatch
  And no human gate fires anywhere in the round-trip
```

```gherkin
Scenario: work entry bounces on substantive drift, re-derivation re-converges
  Given a Todo at lifecycle_phase=prepared with an approved plan and an approved architecture
  And the PRD has been refined since architecture was approved
    (upstream-artifact drift on architecture)
  When the orchestrator calls "telec todo work my-feature"
  Then derive_lifecycle_drift reports drift.architecture = pending
  And work returns the bounce-to-prepare script
  And the orchestrator follows the script
  And the prepare BLOCKED branch dispatches the analyzer
  And the analyzer stamps "--drift-reviewed architecture substantive '<reason>'"
  Then the architecture review verdict is cleared
  And the plan review verdict is cleared
  And the prepare machine routes back to architecture_drafting via _load_procedure
  And the existing prepare chain re-derives architecture and plan, re-reviews each, reaches PREPARED
  And the PREPARED terminal script bounces the orchestrator back to "telec todo work my-feature"
  And work re-runs derive_lifecycle_drift, observes fresh status, and proceeds
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
  via the same `agent_runtime.session.spawn` shape as architecture/plan
  reviewers. Reuse-or-spawn matching applies per
  `prepare-state-machine#reviewer-reuse`.
- `integration` — `origin/main` advances triggered by integration land in
  the SHA comparison used by the code class. The drift contract is
  unaffected by whether the source of the advance is the current
  orchestrator's own work or a sibling delivery.
- `knowledge` — snippet digests are captured against the canonical doc
  layer (`docs/`), the same source `telec docs get` reads. Snippet
  reference extraction uses snippet IDs (`@snippet/<id>` or
  `@<frontmatter-id>` forms), not file paths.
- `session_ledger` — the resolved session principal for each
  `--drift-reviewed` stamp is recorded so the analyzer's verdict can be
  audited and so a non-analyzer session cannot author a drift verdict.

### Implementation pointers (target)

- `teleclaude/core/next_machine/lifecycle.py:_DRIFT_TRACKED_ARTIFACTS` —
  per-artifact coverage table; expanded from a 2-tuple to a 3-tuple
  carrying applicable drift classes.
- `teleclaude/core/next_machine/lifecycle.py:derive_lifecycle_drift` —
  renamed from `derive_prepare_drift`; computes per-(artifact, class)
  status; collapses to the per-artifact overall status via the priority
  rule. Called from BOTH `prepare_steps.py` and `work.py` so the two
  lifecycle entry points share one source of truth for drift derivation.
- `teleclaude/core/next_machine/work.py:next_work` — calls
  `derive_lifecycle_drift` before the `_advance_prepared_to_build_started`
  handoff; returns the bounce-to-prepare script on any pending or
  substantive collapsed status; proceeds with worktree creation and
  dispatch only when every tracked artifact is fresh or cosmetic.
- `teleclaude/core/next_machine/git_ops.py:derive_artifact_drift` —
  remains the per-class derivation for the code class; new sibling
  functions handle upstream-artifact, owned-snippet, upstream-snippet,
  dependency-graph, age.
- `teleclaude/types/todos.py:ArtifactEntry` — extended with the new
  provenance fields. Existing fields preserved for backwards compatibility.
- `teleclaude/types/todos.py:DriftReviewedStamp` — extended with the
  evidence-anchor fields. Existing fields preserved.
- `teleclaude/core/next_machine/state_mutation.py:ApprovalsManager.drift_reviewed`
  — accepts the evidence anchor from the analyzer and persists it.
- `teleclaude/api/todo_routes.py:_sync_artifact_digest_state` — extended
  to capture the new provenance fields at every drift-tracked artifact
  write. **This is the single provenance boundary every write path
  must enter.** Today, four separate code paths touch artifact
  provenance fields and must be consolidated under one boundary:
  - `_sync_artifact_digest_state` at `todo_routes.py:322` — async,
    invoked from the `write_artifact` HTTP route at line 428 with
    SHA + referenced_paths supplied.
  - The same function called from the `dump` route at
    `todo_routes.py:598` (prepped kind, implementation-plan artifact)
    and line 600 (non-bug kind, input artifact), today with EMPTY
    SHA + EMPTY paths. The implementation plan must either populate
    these from the dumped content (extract referenced paths from the
    artifact body; use repo-root HEAD as SHA) or document that dump-
    seeded artifacts are evaluated as `pending` on first prepare,
    relying on the fail-safe path to establish a fresh anchor through
    the analyzer.
  - `_sync_artifact_state` at `state_io.py:90` — synchronous sibling
    used by the internal `sync_artifact_digest` entry point. The
    implementation plan must either fold this into the same boundary
    or document that its callers operate on artifacts not subject to
    drift derivation.
  - `_apply_readiness_stamp` at `stamps.py:139` and
    `_capture_upstream_digests` at `state_io.py:800` — both write
    `upstream_digests` independently of the `_sync_artifact_digest_state`
    boundary. The implementation plan consolidates upstream-digest
    capture into the single provenance boundary so there is exactly
    one place that mutates the extended provenance fields. The
    Should-tier scope item "no parallel provenance write paths" makes
    this consolidation a build-time deliverable; the analyzer's
    fail-safe behavior covers any artifact whose provenance was
    captured through a path that did not populate the new fields.
- `teleclaude/cli/telec/handlers/todo.py:--drift-reviewed` — flag
  signature unchanged; analyzer supplies the evidence anchor implicitly
  from current state at stamp time.

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
  roadmap status. Deep transitive changes (a dep's dep changed) are not
  tracked — the immediate dep's own drift detection is responsible for
  surfacing those upward when it is prepared.
- **Age drift is policy-driven and disabled by default per project until
  the config defaults are set.** Projects that do not configure age
  windows do not pay the age class on their prepare cycles.
- **Drift detection runs on `origin/main`, not on the orchestrator's
  worktree.** Prepare runs on repo-root main with no worktree. The SHA
  compared against `codebase_sha_at_write` is `origin/main` HEAD, not
  local `HEAD` of any sibling worktree.
- **Reference extraction has two distinct mechanisms.** `referenced_paths`
  uses literal path-substring matching against `git ls-files` (current
  behavior, preserved). `referenced_snippet_digests` uses
  `@<snippet-id>` / `@<frontmatter-id>` reference extraction against the
  doc snippet index (new). The two surfaces do not overlap.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/drift-analyze.md
- docs/project/spec/feature/workflow/prepare-state-machine.md
- docs/project/design/architecture/prepare-flow.md
- docs/project/spec/feature/workflow/state-stamping.md
