# Requirements: prepare-pipeline-hardening

## Goal

Fix four concrete problems in the prepare pipeline:

1. Review cycles waste sessions on resolved findings — a reviewer fixes a
   trivial issue inline but still returns NEEDS_WORK, forcing a full
   fix+re-review dispatch.
2. Split resets children to zero — a parent with approved requirements gets
   split and every child restarts from scratch.
3. Artifact tracking relies on file existence — no digests, no consumption
   records, no invalidation cascade. Ghost artifacts from aborted sessions
   confuse routing.
4. Transitions are invisible — no events for phase changes, artifact
   production, review findings, or split inheritance.

## Problem statement

Four observed failures motivate this work:

1. **refactor-large-files: discovery transcribed input instead of verifying.**
   The input said "20 files over 1,000 lines." Discovery wrote that number
   into requirements without checking. The codebase had 27. This burned
   three discovery rounds and two review rounds to establish a fact that
   `wc -l` would have confirmed in seconds.

2. **refactor-large-files: reviewer blocked a factual correction as scope
   expansion.** When the count was corrected from 20 to 27, the reviewer
   flagged it as "silently expanding scope" and demanded human approval.
   Correcting a wrong measurement to match reality is not scope expansion.

3. **refactor-large-files: split reset parent progress.** A parent with
   approved requirements was split into 8 children. Each child started from
   scratch — 8x the ceremony on already-approved work.

4. **prepare-phase-tiering (predecessor todo): review cycles burned 20+
   minutes on trivial findings.** A missing `[inferred]` marker and an
   incomplete acceptance checklist — both trivially fixable — each triggered
   full fix → re-review cycles with 10-minute session startups. The reviewer
   auto-remediated most findings but still returned NEEDS_WORK, forcing
   unnecessary dispatches.

## Scope

### In scope

**Review cycle efficiency**
- Finding severity: trivial, substantive, architectural — each routes differently.
- Auto-remediation closes the loop: all resolved → APPROVE, no re-review.
- Scoped re-reviews: verify specific unresolved findings, not full re-read.
- Auto-remediation boundary: factual corrections vs scope expansions.

**Artifact lifecycle and statefulness**
- state.yaml as sole authority on artifact lifecycle (not file existence).
- Digest-based staleness detection with invalidation cascade.
- Per-phase audit trail with timestamps and structured findings.
- Helper functions for atomic bookkeeping (no raw state writes by agents).
- Schema migration for existing todos.

**Split inheritance**
- Children inherit parent's approved artifacts and start at parent's phase.

**Phase skip observability**
- Any phase that does not execute (e.g. skipped by split inheritance) has an
  observable outcome — not left as "pending" or silently omitted.

**Verification hardening**
- Independent verification of measurable claims before writing requirements.

**Observability**
- Events for every state transition, artifact lifecycle change, and review
  finding action.

**Documentation**
- All affected procedures, policies, specs, and CLI help text updated.

### Out of scope

- Phase B (Work) and Phase C (Integrate) state machines. [inferred]
- The orchestration loop — it still calls `telec todo prepare` and dispatches
  what is returned. [inferred]
- New CLI subcommands. [inferred]
- The machine's routing logic — it continues to route based on file existence
  and state fields. No content judgments added. [inferred]

## Requirements

### Review cycle efficiency

#### R1: Finding severity

Each review finding carries a severity level. The **reviewer** assigns severity
and uses it to determine the verdict:

- **Trivial**: formatting, missing markers, wording. The reviewer
  auto-remediates inline. Resolved immediately. Never triggers a fix cycle.
- **Substantive**: missing coverage, weak criteria, grounding gaps. Enters
  the fix → scoped re-review cycle.
- **Architectural**: contract mismatches, design contradictions, fundamental
  approach problems. Escalates to the orchestrator, who routes to the drafter,
  opens drafter-reviewer conversation, or escalates to human.

Findings are recorded as structured entries in state.yaml (id, severity,
status, summary). The reviewer determines the verdict based on the highest
unresolved severity:
- All trivial and resolved → APPROVE.
- Substantive unresolved → NEEDS_WORK.
- Architectural unresolved → NEEDS_DECISION.

The machine reads the verdict field and routes accordingly — it does not
interpret findings.

#### R2: Auto-remediation closes the loop

When a reviewer resolves all findings inline, the verdict is **APPROVE** — not
NEEDS_WORK. Unresolved finding count determines the verdict, not total finding
count. If `unresolved == 0`, the review passes regardless of how many findings
were auto-remediated. No fix worker is dispatched. No re-review occurs.

This is a **procedure change for reviewers**, not a machine change.

#### R3: Scoped re-reviews

When a review returns NEEDS_WORK with unresolved findings, the machine's
instruction block includes the unresolved finding descriptions from state.yaml.
The re-reviewer verifies only those findings against the updated artifact. It
does not re-read the full artifact, re-check all policies, or produce new
findings outside the original scope.

The machine's role: read structured findings from state.yaml, include them in
the instruction block. Data forwarding, not interpretation.

#### R4: Auto-remediation boundary

The review procedure distinguishes between:

- **Factual corrections**: a verifiably wrong measurement corrected to match
  reality while stated intent is unchanged. Fixed in-place, no escalation.
- **Scope expansions**: new intent, new success criteria, new constraints, or
  new architectural decisions not in the original input. Requires `needs_work`
  verdict.

The discriminator: does the correction change the *intent*, or does it correct
a *measurement* that supports the same intent?

This is a **procedure change for reviewers**, not a machine change.

### Artifact lifecycle and statefulness

#### R5: state.yaml as sole lifecycle authority

State.yaml is the sole authority on artifact lifecycle — not file existence on
disk. Each tracked artifact (input, requirements, implementation_plan, demo)
has a lifecycle entry recording:

- **digest**: content hash of the file on disk.
- **consumed_at / consumed_by / consumed_digest**: when a downstream phase
  consumed this artifact, which phase consumed it, and the hash at that time.
- **derived_at / derived_by**: when and by which phase the artifact was produced.
- **invalidated_at**: set when an upstream artifact changed, cascading staleness.

**Ghost artifact protection:** If a file exists on disk but `derived_at` is
null in state.yaml, the machine treats it as not produced. This is a field
check — the same mechanical pattern as file-existence checking, but richer.
Aborted sessions cannot leave phantom artifacts that confuse routing.

**Who writes lifecycle fields:** Workers call helper functions (R8) after
producing or consuming artifacts. The machine never writes lifecycle fields
except for staleness invalidation (R6).

#### R6: Staleness detection and invalidation cascade

On every `telec todo prepare` call, the machine recomputes artifact digests
from disk and compares against recorded digests. If an upstream artifact's
current digest differs from its `consumed_digest`, all downstream artifacts
are marked `invalidated_at`. The machine returns a re-grounding instruction
for the earliest invalidated phase.

The cascade order: input → requirements → implementation_plan → demo. A change
to input invalidates everything downstream. A change to requirements
invalidates the plan and demo but not input.

This is mechanical hash comparison — no content judgment.

#### R7: Per-phase audit trail

Each phase has its own audit record: `started_at` and `completed_at`
timestamps. Review phases additionally carry `verdict`, `rounds`, and
structured `findings` (each with id, severity, status, summary).

The machine stamps `started_at` when it produces a dispatch instruction and
`completed_at` when it reads the returned verdict. This is bookkeeping.

The existing `prepare_phase` field remains the routing field. The `phases`
dict is the audit trail — richer bookkeeping for observability and debugging,
not a replacement for `prepare_phase`. [inferred]

#### R8: Helper functions for atomic bookkeeping

Agents do not write raw lifecycle fields. They call helpers:

- `mark_artifact_produced(slug, artifact_name)` — hashes the file, sets digest
  and derived_at atomically.
- `mark_artifact_consumed(slug, artifact_name, consumed_by)` — records
  consumed_at, consumed_by, consumed_digest.
- `check_artifact_staleness(slug)` — compares current digests against recorded
  digests, returns invalidation cascade if stale.
- `record_finding(slug, phase, severity, summary)` — appends structured finding.
- `resolve_finding(slug, phase, finding_id)` — marks finding as resolved.

These helpers are the mechanical guarantee that bookkeeping happens. Workers
call them. The machine calls `check_artifact_staleness()` on each prepare
invocation.

#### R9: Schema migration

Existing todos with schema_version 1 continue to work. `read_phase_state()`
deep-merges defaults for the new nested structures. A `schema_version: 2`
field distinguishes old from new. The machine handles both schemas
transparently — no manual migration step required.

### Split inheritance

#### R10: Split inherits parent state

When `telec todo split` creates children from a parent, children start at the
phase the parent has reached:

- Parent has only `input.md` → children get `input.md` subsets, start at
  discovery (current behavior).
- Parent has approved `requirements.md` → children get requirements subsets
  with approval carried through, start at plan drafting.
- Parent has approved `implementation-plan.md` → children get plan subsets
  with approval carried through, start at build.

Phases that children skip due to inheritance have an observable `skipped`
status with reason (R11).

#### R11: Phase skip observability

Any phase that does not execute has an observable outcome in state.yaml —
`skipped` status with reason and timestamp. Phases are never left as "pending"
when they will not run. This applies to phases skipped by split inheritance
and any future skip source.

### Verification hardening

#### R12: Independent verification of measurable claims

When the discovery worker processes an `input.md` containing measurable claims
(file counts, line counts, file paths, threshold numbers), those claims are
independently verified against the live repository before being incorporated
into requirements. Discrepancies are corrected to match the codebase — this is
a factual correction, not a scope change, provided the correction aligns with
stated intent.

This is a **procedure change for discovery workers**, not a machine change.

### Observability

#### R13: Event coverage

Every state transition, artifact lifecycle change, and review finding action
emits an event. New events:

- `prepare.phase_skipped` — phase skipped (e.g. by split inheritance), carries
  phase name and reason.
- `prepare.input_consumed` — input.md consumed by discovery, carries phase and
  digest.
- `prepare.artifact_produced` — artifact written and tracked, carries name and
  digest.
- `prepare.artifact_invalidated` — upstream change cascaded staleness, carries
  artifact name and reason.
- `prepare.finding_recorded` — finding recorded by reviewer, carries severity
  and summary.
- `prepare.finding_resolved` — finding resolved by reviewer, carries resolution
  method.
- `prepare.review_scoped` — scoped re-review dispatched, carries finding ids.
- `prepare.split_inherited` — child inherited parent state, carries parent
  slug, child slug, and inherited phase.

Existing events enriched:
- `prepare.requirements_approved` / `prepare.plan_approved` carry finding
  summary (count by severity).
- `prepare.completed` unchanged.

All events registered in the event vocabulary spec.

### Backward compatibility and documentation

#### R14: Backward compatibility

[inferred] Existing todos without lifecycle fields in state.yaml continue to
work. Schema_version 1 todos are handled transparently by `read_phase_state()`
deep-merging defaults.

#### R15: Documentation updates

All affected procedures, policies, specs, and CLI help text are updated to
reflect review efficiency changes, artifact lifecycle tracking, split
inheritance, and event coverage. This includes: the prepare procedure,
discovery procedure, draft procedure, review procedures, gate procedure,
event vocabulary spec, CLI surface spec, and lifecycle state machine
documentation. [inferred] `telec todo split` help text is updated because
split behavior changes.

## Success Criteria

### Review cycle efficiency

- [ ] Reviewer that auto-remediates all findings produces APPROVE — no fix
      worker dispatched, no re-review.
- [ ] Reviewer that leaves substantive finding unresolved produces NEEDS_WORK
      with finding text in the machine's instruction block for scoped re-review.
- [ ] Scoped re-review verifies only the specified findings — does not produce
      new findings outside scope.
- [ ] Architectural finding produces NEEDS_DECISION escalated to orchestrator.
- [ ] Each finding has a severity field (trivial, substantive, architectural).
- [ ] Corrected measurement (input said 20, requirements say 27) is not
      flagged as scope expansion.

### Artifact lifecycle

- [ ] input.md lifecycle shows `consumed_at` and `consumed_digest` after
      discovery consumes it.
- [ ] Modifying input.md after consumption triggers invalidation cascade —
      requirements, plan, demo marked invalidated, machine routes to
      re-grounding.
- [ ] requirements.md on disk with no `derived_at` in state.yaml is treated
      as not produced (ghost artifact protection).
- [ ] `mark_artifact_produced()`, `mark_artifact_consumed()`,
      `check_artifact_staleness()` helpers exist and are used by all workers.
- [ ] Each phase has started_at, completed_at in state.yaml. Review phases
      have verdict, rounds, structured findings.
- [ ] Schema_version 1 todos continue to work — `read_phase_state()`
      deep-merges defaults.

### Split inheritance

- [ ] Split on parent with approved requirements → children start at plan
      drafting with approval carried through.
- [ ] Split on parent with approved plan → children start at build.
- [ ] Split on parent with only input.md → children start at discovery.
- [ ] Phases skipped by inheritance have observable `skipped` status.

### Verification

- [ ] input.md claiming "20 files over 1000 lines" on a codebase with 27
      produces requirements reflecting 27.

### Observability

- [ ] `prepare.phase_skipped` emitted for each skipped phase.
- [ ] `prepare.finding_recorded` emitted for each finding with severity.
- [ ] `prepare.artifact_invalidated` emitted on cascade.
- [ ] `prepare.split_inherited` emitted when child inherits parent state.
- [ ] All new events registered in event vocabulary spec.

### Documentation

- [ ] All affected procedures, policies, specs, CLI help text updated.

## Constraints

- The prepare state machine remains stateless — it derives routing from
  state.yaml fields and file existence on disk. No in-memory state between
  calls. The richer schema does not change this invariant. [inferred]
- The machine never reads artifact content or judges quality. All content
  decisions belong to workers. [inferred]
- The orchestrator loop is unchanged — it calls `telec todo prepare` and
  dispatches what is returned. [inferred]
- Phase B and Phase C state machines are not modified. [inferred]

## Risks

- **Split inheritance divergence**: children's requirements may diverge from
  parent's approved whole, invalidating inherited approval. Mitigation:
  children's requirements are reviewed independently in their own pipeline
  run. [inferred]
- **Documentation drift**: many procedures need updates. Mitigation: the plan
  enumerates all documents and verifies each. [inferred]
- **Severity misclassification**: architectural finding classified as
  substantive enters fix cycle instead of escalating. Mitigation: severity
  defined by contract-level impact, not effort. Concrete examples provided
  in review procedures.
- **Scoped re-review missing context**: narrow verification may miss that the
  fix introduced a new problem. Mitigation: re-reviewer checks the fix and
  its surrounding section, not just the single paragraph.
- **Schema migration edge cases**: deeply nested defaults may not merge
  cleanly with all existing state.yaml variations. Mitigation: the migration
  is tested against every existing todo's state.yaml in the repo.
