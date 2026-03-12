# Requirements: prepare-pipeline-hardening

> Note: `input.md` currently contains no substantive source text. Unless a
> statement is explicitly attributed to repository artifacts, the substantive
> content below is [inferred] from the slug, current prepare-state docs/code,
> and observed repo history.

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
- Durable lifecycle metadata in state.yaml, rather than inferring lifecycle
  solely from file existence.
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

**Worker re-dispatch context**
- Re-dispatched workers receive per-step `additional_context` with precise
  diffs, not generic "redo this phase" instructions.

**Documentation**
- All affected procedures, policies, specs, and CLI help text updated.

### Out of scope

- Phase B (Work) and Phase C (Integrate) state machines. [inferred]
- The orchestration loop — it still calls `telec todo prepare` and dispatches
  what is returned. [inferred]
- New CLI subcommands. [inferred]
- The machine's routing remains mechanical and free of content judgments.
  [inferred]

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

Findings are recorded as structured entries in state.yaml with stable
identifiers, severity, status, and summaries. The reviewer determines the verdict based on the highest
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
instruction note reports the unresolved count and points to the findings file.
The worker reads the file itself. The machine never reads markdown content to
inject into notes.

The re-reviewer verifies only those findings against the updated artifact. It
does not re-read the full artifact, re-check all policies, or produce new
findings outside the original scope.

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

#### R5: state.yaml as durable lifecycle authority

State.yaml is the durable authority on artifact lifecycle, rather than
inferring lifecycle solely from file existence on disk. Each tracked artifact
(input, requirements, implementation plan) records its current digest in
state.yaml.

**Ghost artifact protection:** If a file exists on disk but its lifecycle
metadata does not show it as produced, the machine treats it as not produced.
Aborted sessions cannot leave phantom artifacts that confuse routing.

**Who writes digests:** Workers use a shared helper after producing an
artifact. The helper computes the SHA and writes it to state.yaml. One
generic helper, applicable to any artifact.

#### R6: Staleness detection and invalidation cascade

On every `telec todo prepare` call, before phase routing, the machine
recomputes the SHA of each tracked artifact on disk and compares it against
the recorded digest in state.yaml. If an artifact's SHA differs from what
was recorded, that artifact has changed and everything downstream is stale.

The cascade order: input → requirements → implementation plan. A change to
input invalidates requirements and plan. A change to requirements invalidates
the plan.

When staleness is detected, the machine routes back to the phase that
corresponds to the earliest changed artifact. The note reports which
artifacts are stale and points to state.yaml.

This is a generic mechanism — one helper that takes any artifact name,
computes its SHA, and compares. The same helper is used both when recording
a digest (after production) and when checking for staleness (before routing).

This check is separate from the existing codebase grounding check, which
runs at the end of prepare and detects whether referenced source files
changed between commits. Both checks are complementary: artifact staleness
detects internal changes to todo files, codebase grounding detects external
changes to the code the plan references.

#### R7: Per-phase audit trail

Each phase has its own audit record with start/end timestamps. Review phases
additionally carry verdict, rounds, and structured finding records.

The machine stamps `started_at` when it produces a dispatch instruction and
`completed_at` when it reads the returned verdict. This is bookkeeping.

The existing `prepare_phase` field remains the routing field. The audit trail is
additional bookkeeping for observability and debugging, not a replacement for
`prepare_phase`. [inferred]

#### R8: Generic helper for artifact digest bookkeeping

One generic helper handles artifact digests: compute SHA of a file, write
it to state.yaml under the artifact's entry. Workers call it after producing
an artifact. The machine calls it in check mode (compare, don't write) on
every prepare invocation for staleness detection.

The same helper also serves finding bookkeeping: record a finding, resolve
a finding, each as a structured state.yaml mutation.

#### R9: Schema migration

Existing todos continue to work. Schema versioning and default-merge behavior
handle both the old and new state shapes transparently — no manual migration
step required.

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

### Plan grounding validation

#### R16: Referenced path existence check

After plan drafting completes and `referenced_paths` are written to
`state.yaml.grounding`, the state machine validates that every referenced path
exists on disk. Non-existent paths are a mechanical rejection — the machine
returns the list of missing paths to the drafter for correction, without
advancing to plan review.

This is the same class of mechanical check as ghost artifact protection (R5)
and staleness detection (R6): a fact check on the filesystem, not a content
judgment. The drafter produced paths; the machine verifies they resolve.

### Worker re-dispatch context

#### R17: Additional context for re-dispatched workers

When the machine re-dispatches a worker due to staleness, review findings, or
path validation failure, it computes the most specific context available and
passes it as `additional_context` in the command arguments. The orchestrator
forwards this verbatim to the worker via `telec sessions run`. Workers receive
precise scope rather than generic "redo this phase" instructions, preserving
valuable prior work.

The machine computes context mechanically — git diffs between known SHAs scoped
to specific files. No content judgment, no markdown reading. The same
`_run_git_prepare` helper used for codebase grounding produces the diffs.

Per-step context the machine extracts:

- **Discovery re-dispatch (input stale)**: `git diff {base_sha}..HEAD --
  todos/{slug}/input.md` — exactly what changed in the input since last
  recording.
- **Discovery re-dispatch (review NEEDS_WORK)**: unresolved finding count +
  pointer to findings file + `git diff {baseline_commit}..HEAD --
  todos/{slug}/requirements.md` — what the discovery worker wrote and what the
  reviewer changed.
- **Plan draft re-dispatch (requirements stale)**: `git diff {base_sha}..HEAD
  -- todos/{slug}/requirements.md` — what changed in the approved requirements
  since the plan was grounded.
- **Plan draft re-dispatch (review NEEDS_WORK)**: unresolved finding count +
  pointer to findings file + `git diff {baseline_commit}..HEAD --
  todos/{slug}/implementation-plan.md` — what the drafter wrote and what the
  reviewer changed.
- **Plan draft re-dispatch (path existence failure, R16)**: list of
  non-existent paths from `referenced_paths`.
- **Scoped re-review dispatch**: `git diff {baseline_commit}..HEAD --
  todos/{slug}/{artifact}` + finding IDs to verify — the fix diff scoped to
  the artifact under review.
- **Re-grounding dispatch**: `git diff {base_sha}..HEAD -- {changed_paths}` —
  existing behavior, enriched with the path list.
- **Gate re-dispatch**: `git diff {base_sha}..HEAD -- todos/{slug}/` — full
  todo folder diff showing all artifact changes since last grounding.

First-time dispatches (fresh discovery, first review, first draft, first gate)
carry no `additional_context` — the standard note suffices.

The `additional_context` flows through the existing dispatch surface:
`format_tool_call` includes it in the dispatch instruction, the orchestrator
passes it via `telec sessions run --additional-context`, and worker commands
receive it as part of their startup frontmatter.

### Backward compatibility and documentation

#### R14: Backward compatibility

[inferred] Existing todos without lifecycle fields in state.yaml continue to
work. Older state shapes are handled transparently by the existing default-merge
read path.

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
- [ ] Reviewer that leaves substantive finding unresolved produces NEEDS_WORK.
      Machine note reports unresolved count and points to the findings file.
- [ ] Scoped re-review verifies only the specified findings — does not produce
      new findings outside scope.
- [ ] Architectural finding produces NEEDS_DECISION escalated to orchestrator.
- [ ] Each finding has a severity field (trivial, substantive, architectural).
- [ ] Corrected measurement (input said 20, requirements say 27) is not
      flagged as scope expansion.

### Artifact lifecycle

- [ ] Each tracked artifact (input, requirements, implementation plan) has a
      SHA digest recorded in state.yaml after production.
- [ ] On every prepare call, the machine compares on-disk SHAs against
      recorded digests. Changed artifact → downstream cascade → re-route.
- [ ] Modifying input.md triggers invalidation of requirements and plan.
- [ ] Modifying requirements.md triggers invalidation of plan.
- [ ] requirements.md on disk with no produced lifecycle metadata is treated as
      not produced (ghost artifact protection).
- [ ] One generic digest helper used for both recording and checking.
- [ ] Each phase has start/end audit metadata in state.yaml. Review phases have
      verdict, rounds, and structured findings.
- [ ] Older todos continue to work through schema-version compatibility and
      default-merge behavior.

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

### Plan grounding

- [ ] After plan drafting, `referenced_paths` with non-existent files cause
      mechanical rejection back to drafter — plan review is not entered.
- [ ] Drafter receives the list of missing paths in the machine's instruction.

### Worker re-dispatch context

- [ ] Re-dispatched discovery worker receives `git diff` of input.md changes as
      `additional_context`.
- [ ] Re-dispatched discovery worker (NEEDS_WORK) receives finding count +
      pointer + `git diff` of requirements.md changes.
- [ ] Re-dispatched plan drafter (requirements stale) receives `git diff` of
      requirements.md changes.
- [ ] Re-dispatched plan drafter (NEEDS_WORK) receives finding count + pointer +
      `git diff` of implementation-plan.md changes.
- [ ] Re-dispatched plan drafter (path existence failure) receives list of
      missing paths.
- [ ] Scoped re-review receives `git diff` of artifact changes since review
      baseline + finding IDs.
- [ ] Re-grounding dispatch includes `git diff` of changed source paths.
- [ ] Gate re-dispatch includes `git diff` of full todo folder.
- [ ] First-time dispatches carry no `additional_context`.
- [ ] `format_tool_call` accepts and includes `additional_context` in dispatch
      output.
- [ ] `telec sessions run` accepts `--additional-context` and passes it to
      worker commands.

### Documentation

- [ ] All affected procedures, policies, specs, CLI help text updated.

## Constraints

- The prepare state machine remains stateless — it derives routing from
  durable metadata and current files on disk, with no in-memory state between
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
