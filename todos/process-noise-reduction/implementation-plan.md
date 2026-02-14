# Implementation Plan: process-noise-reduction

## Phase 1: Engine Hardening (Python)

- [ ] Refactor `mark_phase` in `core.py` to include a `pre_flight_check` that scans Markdown for unchecked boxes.
- [ ] Update `next_work` to use this check to block transitions to `complete` or `approved` if clerical evidence is missing.
- [ ] Remove `check_review_status` and `parse_impl_plan_done` from the "Worker awareness" path and make them Orchestrator-internal validators.

## Phase 2: Mandate Simplification (Markdown)

- [ ] Refactor `agents/commands/next-review.md`: Remove checkbox auditing steps.
- [ ] Refactor `agents/commands/next-finalize.md`: Remove checkbox auditing steps.
- [ ] Refactor `agents/commands/next-fix-review.md`: Remove redundant verification.

## Phase 3: Cultural Alignment (Primers & Global Docs)

- [ ] Update `agents/CLAUDE.primer.md` (and others): Enforce "Contract Trust" (Treat dispatch as authoritative).
- [ ] Update global lifecycle docs (build, review, finalize) to shift verification responsibility to the Orchestrator.

## Phase 4: Verification

- [ ] Run `telec sync` to distribute new mandates.
- [ ] Verify that a `teleclaude__mark_phase` call fails if boxes are unchecked.
