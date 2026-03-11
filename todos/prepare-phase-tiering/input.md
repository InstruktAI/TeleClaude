# prepare-phase-tiering — Input

# Prepare Phase Tiering — Design Discussion

## Context
The current prepare state machine treats all work identically: discovery → review requirements → draft plan → review plan → gate. This is overkill for well-defined inputs and mechanical changes.

## Agreed Direction
Three tiers based on input quality assessment:

### Tier 1: Full Pipeline (current behavior)
- High-ambiguity, high-impact work where the "what" is still forming
- Vague inputs, cross-cutting concerns, new features with unclear scope
- All steps: discovery → requirements review → plan draft → plan review → gate

### Tier 2: Abbreviated Pipeline
- Input is already concrete and detailed (exact files, clear constraints, grounded in codebase)
- Skip discovery — input quality is already at requirements level
- Go straight to plan drafting with a single review pass
- State machine should assess input quality and mark_phase to skip discovery/requirements review

### Tier 3: Direct Build
- Mechanical changes with zero ambiguity (renames, config updates, formatting)
- No preparation artifacts needed — go directly to build + code review
- State machine marks prepare as complete, sets state.yaml accordingly

## Key Discriminator
How much of the "what" is already known. When the input reads like requirements, discovery is transcription overhead. When it reads like a vague wish, discovery earns its keep.

## Implementation Implications
- The state machine (telec todo prepare) needs an assessment step at entry that evaluates input quality
- Assessment updates state.yaml with the tier decision and skips phases accordingly
- mark_phase invocations should reflect the tier — setting appropriate phase states to "skipped" or "not_applicable"
- Policies and procedures need updating to reflect that not all gates are mandatory for all tiers
- The orchestrator instruction output should route differently based on tier

## What Needs Investigation
1. The state machine code in telec todo prepare — how it determines the next instruction
2. state.yaml schema — what fields need to support tier/skip semantics
3. The prepare procedure doc — needs tier-aware language
4. The DOR policy — needs tier-aware gate enforcement (some gates auto-pass for tier 2/3)
5. The discovery, draft, review, and gate procedures — need awareness of when they're skipped
6. Whether the assessment itself should be an inline step in the orchestrator or a dispatched worker

## Design Principle
The assessment should be just like the current state machine output — it evaluates, updates state.yaml, and the next call to `telec todo prepare` returns the right instruction for the tier. No human intervention needed. The machine is smarter about routing, not less rigorous — it just doesn't apply ceremony where evidence shows it's unnecessary.

## Observed Failure: refactor-large-files (2026-03-11)

The `refactor-large-files` todo exposed two systemic failures in the current pipeline that directly motivate this redesign:

### Failure 1: Discovery grounded against input text instead of the live codebase

The input said "20 files over 1,000 lines." The discovery worker transcribed that number into requirements without running its own count. The codebase actually had 27 files over the threshold. This is a trivial verification — `wc -l` and a sort — but the discovery procedure doesn't mandate independent verification of quantitative claims in the input. It says "ground in the codebase" but doesn't enforce "measure before you write."

**Fix:** The assessment step (or discovery, when it runs) must independently verify every measurable claim in the input against the live repo before writing requirements. Numbers, file paths, line counts, import counts — anything that can be checked, must be checked.

### Failure 2: Reviewer treated a factual correction as a scope expansion requiring human approval

When the inventory was corrected from 20 to 27, the reviewer flagged it as "silently expanding scope beyond the human input" and blocked on it with `needs_work`, demanding a human decision. This burned two additional round-trips. Correcting a wrong number to match reality is not scope expansion — it's fixing a defect. The auto-remediation boundary ("don't add new scope") failed to distinguish between "adding new intent" and "correcting a factual error in the input."

**Fix:** The review procedure's auto-remediation rules need a carve-out: when the input contains a verifiably wrong fact (count, file path, line number) and the correction aligns with the stated intent, the reviewer should fix it in-place, not escalate to human. The discriminator: does the correction change the *intent* of the work, or does it correct a *measurement* that supports the same intent?

### Combined cost

These two failures turned what should have been a single discovery pass into three rounds of discovery + two rounds of review, all to establish that "refactor large files" means "all the large files." The tiering system should prevent this by making independent verification mandatory at assessment time, before the pipeline even starts.

### Failure 3: Split reset parent progress instead of distributing it

The parent had approved requirements when the drafter decided to split into 8 children. The draft procedure said to "seed each child's `input.md`" — treating children as new todos starting from scratch. Each child would then go through the full prepare pipeline: discovery → requirements review → plan → review → gate. That's 8x the ceremony on work that was already requirements-approved.

The split should have distributed the parent's approved requirements directly into each child's `requirements.md` with `requirements_review.verdict: approve` already set. The children would then start at plan drafting, not at discovery.

**Fix — Split inherits parent state:** The split is a fan-out at whatever phase the parent has reached. Children start where the parent left off:

- Parent has only `input.md` → children get `input.md` subsets, start at discovery
- Parent has approved `requirements.md` → children get `requirements.md` subsets with approval carried through, start at plan drafting
- Parent has approved `implementation-plan.md` → children get plan subsets with approval, start at build

The `telec todo split` command and the draft procedure both need to respect this. The split command should read the parent's state and scaffold children at the same phase. The procedure should say "seed children at the parent's current phase" not "seed input.md."

This interacts with the tiering design: a child born from an approved parent with concrete, detailed requirements is by definition Tier 2 or Tier 3. The assessment step should recognize inherited approval and route accordingly.
