# Requirements: prepare-phase-tiering

## Goal

Introduce tiered routing in the prepare state machine so that well-defined inputs
skip unnecessary ceremony while ambiguous inputs still receive full pipeline rigor.
Additionally, fix the split command to inherit parent progress instead of resetting
children to scratch, and harden the review procedure's auto-remediation boundary
to distinguish factual corrections from scope expansions.

## Scope

### In scope

1. **Tier-based routing in the prepare state machine** — an assessment step that
   evaluates input quality and routes to the appropriate pipeline depth.
2. **State tracking for the tier decision** — the tier and its rationale are
   recorded durably so downstream phases and re-entry respect it.
3. **Phase skipping semantics** — phases that are bypassed by a tier record a
   skip status rather than being silently omitted.
4. **Split state inheritance** — when a parent todo is split, children inherit
   the parent's approved artifacts and start at the phase the parent reached,
   not at discovery.
5. **Mandatory independent verification** — the assessment step (or discovery,
   when it runs) independently verifies every measurable claim in the input
   against the live repository before writing requirements.
6. **Review auto-remediation carve-out** — the review procedure distinguishes
   between factual corrections (wrong count, wrong path) that align with stated
   intent and genuine scope expansions that add new intent.
7. **Procedure and policy documentation updates** — the prepare procedure, DOR
   policy, discovery procedure, draft procedure, review procedures, and gate
   procedure are updated to reflect tier-aware routing and the new boundaries.
   [inferred] Relevant `telec` command/help documentation is updated too
   because the behavior of existing `telec todo prepare` and `telec todo split`
   commands changes.

### Out of scope

- Changes to Phase B (Work) or Phase C (Integrate) state machines. [inferred]
- Changes to the orchestration loop itself — the orchestrator still calls
  `telec todo prepare` and dispatches what is returned. [inferred]
- New CLI subcommands — the existing `telec todo prepare` entry point is
  sufficient; tier routing is internal to the machine. [inferred]
- UI/TUI changes for tier visualization. [inferred]

## Requirements

### R1: Input quality assessment

The prepare state machine evaluates input quality at entry and assigns a tier
before dispatching any worker. The assessment determines how much of the "what"
is already known and routes accordingly:

- **Tier 1 (Full Pipeline)**: high-ambiguity or high-impact work where the
  problem statement, constraints, or scope are still forming. All phases run:
  discovery, requirements review, plan drafting, plan review, gate, grounding
  check.
- **Tier 2 (Abbreviated Pipeline)**: input is already concrete and detailed —
  it reads like requirements (exact files, clear constraints, grounded in
  codebase). Discovery is skipped; the input is promoted to serve as the basis
  for requirements. Pipeline starts at plan drafting with a single review pass.
- **Tier 3 (Direct Build)**: mechanical changes with zero ambiguity (renames,
  config updates, formatting fixes). No preparation artifacts are needed.
  Preparation is marked complete and the todo proceeds directly to Phase B.

[inferred] The assessment is deterministic: given the same `input.md` and
codebase state, the same tier is assigned.

### R2: Tier decision persistence

The tier decision and its rationale are recorded in `state.yaml` so that:

- Re-entry via `telec todo prepare` respects the existing tier rather than
  re-assessing.
- Downstream phases can read the tier to adjust their behavior.
- Auditing can trace why a particular pipeline depth was chosen.

### R3: Phase skip semantics

When a tier causes phases to be bypassed, those phases are recorded with a
distinct skip status (not left as "pending" or silently omitted). This
preserves the invariant that every phase has an observable outcome —
completed, skipped, or blocked.

### R4: Tier 2 — input promotion to requirements

For Tier 2 items, the assessment step promotes `input.md` content to serve as
the foundation for `requirements.md`. The discovery step is skipped (recorded
as such). The pipeline advances to plan drafting.

### R5: Tier 3 — direct build routing

For Tier 3 items, all preparation phases are marked as skipped or
not-applicable. The state machine marks preparation complete so Phase B can
claim it immediately. No preparation artifacts are produced.

[inferred] Tier 3 items still go through code review in Phase B — the
review gate is not bypassed. Only preparation ceremony is skipped.

### R6: Mandatory independent verification of measurable claims

When the assessment or discovery processes an `input.md` that contains
measurable claims (file counts, line counts, file paths, import counts,
threshold numbers), those claims are independently verified against the live
repository before being incorporated into requirements. Discrepancies between
the input's claims and reality are corrected to match the codebase — this is
a factual correction, not a scope change, provided the correction aligns with
the stated intent.

### R7: Review auto-remediation boundary refinement

The review procedure's auto-remediation rules distinguish between:

- **Factual corrections**: a verifiably wrong measurement (count, path, line
  number) is corrected to match reality while the stated intent is unchanged.
  Reviewers fix these in-place without escalating to the human.
- **Scope expansions**: new intent, new success criteria, new constraints, or
  new architectural decisions that were not in the original input. These
  require `needs_work` verdict and human review.

The discriminator: does the correction change the *intent* of the work, or
does it correct a *measurement* that supports the same intent?

### R8: Split inherits parent state

When `telec todo split` creates children from a parent, children start at
the phase the parent has reached:

- Parent has only `input.md` → children get `input.md` subsets, start at
  discovery (current behavior).
- Parent has approved `requirements.md` → children get requirements subsets
  with the approval verdict carried through, start at plan drafting.
- Parent has approved `implementation-plan.md` → children get plan subsets
  with approval carried through, start at build.

Children born from an approved parent with concrete, detailed requirements
are assessed as Tier 2 or Tier 3 by the assessment step — the inherited
approval is a strong signal for tier routing.

### R9: Backward compatibility

[inferred] Existing todos with no tier in `state.yaml` continue to work. The
state machine treats the absence of a tier decision as "not yet assessed" and
falls back to the full prepare pipeline until the tier is recorded.

## Success Criteria

- [ ] `telec todo prepare` on a Tier 1 input runs the full pipeline
      (discovery → requirements review → plan → plan review → gate →
      grounding check) — identical to current behavior.
- [ ] `telec todo prepare` on a Tier 2 input skips discovery and requirements
      review, records those skips, advances to plan drafting, and reaches
      PREPARED after the single remaining review pass.
- [ ] `telec todo prepare` on a Tier 3 input marks all preparation phases
      as skipped and reaches PREPARED state without dispatching any workers.
- [ ] Re-calling `telec todo prepare` after a tier is assigned respects
      the existing tier and does not re-assess.
- [ ] `telec todo split` on a parent with approved requirements creates
      children that start at plan drafting, not at discovery.
- [ ] `telec todo split` on a parent with only `input.md` creates children
      that start at discovery (unchanged behavior).
- [ ] An `input.md` claiming "20 files over 1000 lines" on a codebase with
      27 such files produces requirements reflecting the actual count (27),
      not the input's claim.
- [ ] A reviewer encountering a corrected count (input said 20, requirements
      say 27) does not flag it as scope expansion.
- [ ] [inferred] Existing todos without a tier field in `state.yaml` continue
      to function — the state machine defaults to full pipeline.
- [ ] All skipped phases have a non-pending observable status in `state.yaml`
      — no phase is silently omitted or left as pending.
- [ ] [inferred] Procedure, policy, and relevant `telec` command/help
      documentation reflect tier-aware routing.

## Constraints

- [inferred] The prepare state machine remains stateless — it derives routing
  from `state.yaml` and artifact existence on disk. No in-memory state between
  calls. (Existing invariant, preserved.)
- [inferred] The orchestrator loop is unchanged — it calls `telec todo prepare`
  and dispatches what is returned. Tier routing is internal to the machine.
- [inferred] Phase B and Phase C state machines are not modified.
- [inferred] The assessment must be deterministic: same inputs → same tier.

## Risks

- [inferred] **Tier misclassification**: an ambiguous input classified as Tier 2
  or 3 could skip necessary discovery, producing weak requirements. Mitigation:
  the assessment errs toward higher tiers (more ceremony) when uncertain.
  Tier 3 requires zero-ambiguity confidence.
- [inferred] **Split inheritance complexity**: carrying parent approval through
  to children introduces a new invariant (children's requirements are subsets
  of an approved whole). If a child's requirements diverge significantly from
  the parent's, the inherited approval may be invalid. Mitigation: the
  assessment step on children re-evaluates tier independently.
- [inferred] **Documentation drift**: seven procedure/policy documents need
  updates. If any is missed, agents following stale procedures may not respect
  tiers. Mitigation: the implementation plan should enumerate all documents and
  verify each is updated.
