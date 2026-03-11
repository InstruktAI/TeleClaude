# Requirements Review Findings: prepare-phase-tiering

## Auto-remediated (resolved)

### 1. Tier 2 routing contradicted the agreed direction — Important (resolved)

`requirements.md` said Tier 2 goes straight to plan drafting with a single review
pass, then added an inferred paragraph sending the promoted requirements back
through requirements review. That conflicted with the input's explicit
"skip discovery/requirements review" direction. The contradictory paragraph was
removed, and the Tier 2 success criterion was tightened so it now proves
discovery and requirements review are both skipped before the item reaches
`PREPARED`.

### 2. Inference transparency and review-awareness gaps — Suggestion (resolved)

Several inferred statements were presented as if they came directly from the
input. Added `[inferred]` markers to the out-of-scope items, backward
compatibility behavior, constraints, and risks. Also tightened the skipped-phase
success criterion so "skipped" cannot be satisfied by leaving a phase as
`pending`, and made the documentation-update implication explicit for the
changed `telec todo prepare` / `telec todo split` behavior.

## Unresolved

### 3. Split inheritance still lacks a verification path for the approved-plan case — Important

R8 defines three parent states:

- input only -> child starts at discovery
- approved requirements -> child starts at plan drafting
- approved implementation plan -> child starts at build

The success criteria only verify the first two cases. There is no acceptance
check proving that a child scaffolded from an approved parent plan bypasses
prepare and enters build at the parent's phase. As written, a builder can miss
the approved-plan inheritance path and still satisfy the checklist.
