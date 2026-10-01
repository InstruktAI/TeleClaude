---
visibility: 'public'
number: '58'
date: '2026-06-23'
description: 'ADRs gain a single mutable ## Status section: the body stays immutable, but Status may be set to Superseded by / Superseded in part by / Deprecated when a later ADR supersedes it. Superseded ADRs are kept and marked, never deleted; the status pointer is the one permitted forward link.'
---

# ADR-0058: ADRs carry a mutable Status with a forward supersession pointer — ADR

## Context

ADR discipline froze ADRs completely: the body was immutable, no supersession field or pointer existed, and references ran backward only. A reversed decision was recorded as a new ADR that back-referenced the old one, but the old ADR carried no marker of its changed standing.

That left two gaps. A reader landing on a superseded ADR — directly or through `telec docs index --areas adr`, which lists each ADR's description — got no signal that the decision had been narrowed or reversed, and no pointer to the ADR that did it. The forward relationship existed only in the newer ADR, which the reader had no reason to have found. The practical failure surfaced when a reversed decision's record kept reading as current.

The opposite failure is worse and is what the freeze correctly prevented: editing an ADR's body to bolt a contradiction onto it produces a self-contradictory record and destroys the decision timeline. Any fix had to preserve body immutability.

## Decision

An ADR's **body** (Context / Decision / Consequences / Alternatives Considered) remains immutable — never edited after authoring. ADRs gain one mutable element: an optional **`## Status`** section.

- A fresh ADR omits `## Status`; absence means live and accepted.
- When a later ADR supersedes an earlier one, the earlier ADR's `## Status` is set to `Superseded by ADR-NNNN`, `Superseded in part by ADR-NNNN` (with a clause naming the superseded part), or `Deprecated`. This is the only change ever made to an existing ADR.
- That status pointer is the sole permitted forward ADR→ADR link; the body still references backward only.
- **ADRs are superseded, never deleted.** A marked-superseded ADR stays on the timeline — both what was decided and that it no longer holds are preserved. Deletion would discard the history; the marker clears the confusion without that cost.

This follows the conventional ADR lifecycle (a mutable status, immutable body) rather than the stricter no-status freeze.

## Consequences

- A reader of a superseded ADR is pointed forward to the ADR that replaced it; the stale-record-reads-as-current failure is closed at the file level.
- Body immutability and the one-decision-per-ADR timeline are preserved; the self-contradiction failure stays prevented because the contradiction lives in a new ADR, never in the old body.
- Removal is no longer the tool for clearing obsolete decisions — `Superseded`/`Deprecated` is — so the ADR folder remains a complete, append-only timeline rather than a register of only-live decisions.
- The status is enforced by authoring discipline and review, not by tooling: nothing yet surfaces an ADR's status in `telec docs index` listings, so a superseded ADR's description still reads as live in the index until that is addressed separately. Closing the index-level gap is a tooling change, out of scope here.
- The snippet schema allows a `## Status` section on the `adr` type; it is optional, so existing ADRs without one remain valid and need no backfill.

## Alternatives Considered

- **Keep the full freeze (no status, backward-reference only).** Rejected: it leaves superseded ADRs indistinguishable from live ones and provides no forward pointer, which is the gap that motivated this change.
- **Allow deletion of obsolete ADRs.** Rejected as the primary mechanism: deletion clears confusion but discards the decision timeline (the "why we once decided X and moved on" that prevents re-litigation). A status marker achieves the clarity while keeping the history. Git retains a deleted file, but the discoverable, in-folder timeline is the point of ADRs.
- **Mutable status as a frontmatter field instead of a body section.** Deferred: a frontmatter field would let the index render status directly (a stronger fix for the discoverability gap), but it requires schema-validation and index-rendering changes. The body `## Status` section is adoptable immediately with no code; the indexed-field option remains open as a later tooling step.
