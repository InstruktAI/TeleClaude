---
date: '2026-06-09'
description: 'ADRs are immutable historical records; a superseding ADR cites the prior one via a forward supersedes pointer and never mutates it (no adr_status edit on the prior).'
number: '22'
visibility: 'public'
---

# ADR-0022: ADRs are immutable; supersession is forward-only — ADR

## Context

The ADR discipline (`general/policy/adr-discipline`, `general/procedure/adr-authoring`)
previously mandated that when a new ADR supersedes a prior decision, the prior
ADR's `adr_status` is **updated to `superseded`**. That is a mutation of a
historical record: it edits the standing of a decision that was, in fact,
accepted at the time it was made.

This conflicts with what an ADR is — an immutable, point-in-time record of a
decision and its reasoning — and with how the rest of the platform already
handles supersession. Doc-snippet companions never mutate the parent: the index
**derives** a `(superseded by: <slug>)` marker from the companion's existence,
and the parent carries no field. The ADR discipline was the lone surface that
reached back and rewrote prior records.

A wrong (or merely later) decision recorded in an ADR is still a true record of
what was decided then; mutating its status erases that truth and turns the ADR
log into a mutable graph.

## Decision

ADRs are immutable. A later decision NEVER modifies an earlier ADR — not its
body, not its `adr_status`.

Supersession is recorded **forward-only**: the new ADR cites the prior ADR's id
in its own `supersedes` frontmatter, and that pointer is the entire record of the
relationship. Any "superseded by" view is **derived** from the forward pointer —
mirroring how a live snippet's `(superseded by: <slug>)` marker is derived from
its companion rather than stored on the parent.

Scope of this change:

- `general/policy/adr-discipline` and `general/procedure/adr-authoring` are
  updated to forbid mutating a prior ADR and to record supersession forward-only.
- `general/spec/snippet-authoring-schema` notes that `superseded` is a
  derived/legacy `adr_status` value, never hand-set by a superseding ADR.
- The `superseded` enum value is retained (it remains valid for the two
  pre-existing ADRs that carry it and avoids a validation/code change). Those
  legacy records are left exactly as they are — re-mutating them would repeat the
  very act this decision forbids.

Out of scope (separate, code-touching follow-ups, not done here):

- Building index tooling that derives a `(superseded by: <adr>)` marker on a prior
  ADR from later ADRs' `supersedes` pointers (the companion-style derived display).
- Retiring the `superseded` enum value once the legacy records age out.

## Consequences

**Positive:**

- ADRs become a true append-only history; reading an old ADR shows what was
  decided then, never a retroactively edited standing.
- The ADR discipline is now consistent with the companion/derived-supersession
  model the rest of the platform uses.
- Authoring a superseding ADR no longer requires touching another file.

**Negative / costs:**

- Until the derived-display tooling exists, discovering that an ADR was superseded
  requires reading forward (the superseding ADR's `supersedes` pointer); the prior
  ADR carries no local signal. This is an accepted trade for immutability.
- The `superseded` enum value now has a narrower, derived/legacy meaning than its
  name suggests; the schema note disambiguates it until it is retired.
