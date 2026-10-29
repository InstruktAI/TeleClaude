---
visibility: public
number: 96
date: 2026-09-21
description: A claimed todo's artifacts are writable only by the session holding the claim and the sessions it dispatched, across every writable artifact kind.
---

# ADR-0096: Claimed todo artifacts are writable only by the claiming group — ADR

## Status

Superseded in part by ADR-0149: the prepare-author role gate is replaced by the
role catalog's `prepare-artifact-write` capability and a closed-contract
condition; the claiming group and its precedence stand.

## Context

Artifact-write admission reads the caller and not the object. The only guard a
write passes today resolves the caller's job role, and it applies to five of the
fourteen writable artifact kinds. The other nine, `log` among them, have never
been gated on ownership at any point in the write surface's history.

ADR-0067 made ownership a conjunct of workflow-mutation authorization — the
session holds the object's live claim, or the object is unheld — and retired the
prepare-write job allowlist. ADR-0078 subsequently removed ownership from
prepare-artifact admission so that a dispatched prepare author could write
without a lease or a claim handoff, and stated that artifact authorship and
lifecycle ownership are independent responsibilities.

That reasoning is sound about the author it was written for and silent about
every other caller. With ownership absent, a session driving one todo may rewrite
a different todo's `prd`, `architecture`, `implementation-plan`, `diagnosis`, or
`input` while that todo's own workers hold reasoning already formed from the
prior content. `general/principle/trust-and-guardrails` names that interference
as a harm restoring state cannot repair — the stored value returns, the other
agent's reasoning does not — and names the caller's rank as the wrong axis for a
guardrail to read.

The two concerns are separable. What ADR-0078 needed was that a dispatched author
not be blocked by the driver that dispatched it. What it gave up was any
ownership boundary at all.

## Decision

A todo whose `active_runner` names a live session is claimed. Its artifacts —
every writable kind — are writable only by that claim's group: the holding
session and every session it dispatched, transitively through
`initiator_session_id`. A todo with no `active_runner`, or one naming a session
no longer live, is unclaimed and carries no claim gate.

A caller outside the group is refused before any state mutation. The refusal
names the holding session and the door that satisfies the invariant: address that
session, which owns whether the concern changes its work.

The claim is an integrity boundary and composes with, rather than replaces, the
capability boundary already in place. The prepare-author role gate continues to
govern which members may write which artifact class inside the group.

A direct human-identity writer carries no agent session id, is not a session in
the group, and is not gated by the claim. Reads are never gated.

## Consequences

- A dispatched author still writes without a lease, a claim handoff, or an
  expiring authority, because its membership is already recorded in the session
  it was dispatched from. ADR-0078's deadlock-avoidance property survives.
- Nine artifact kinds acquire an ownership boundary for the first time.
- The refusal is a routing surface: a caller with a real concern about another
  session's todo is pointed at that session rather than at a wall.
- Membership resolution walks the ancestry chain from the caller, so its cost is
  the dispatch depth and it reads only records the session registry already
  keeps.
- A holder that dies releases the gate, so a stuck claim never makes a todo
  permanently unwritable; an erroneous live claim is still cleared through the
  unclaim path.

## Alternatives Considered

- **Leave artifact writes claim-free.** Rejected: it leaves the interference harm
  unaddressed for every artifact kind, and leaves a guardrail that reads the
  caller's job as the only thing standing between a foreign session and a
  prepared plan.
- **Admit only the session whose id equals `active_runner`.** Rejected: it
  refuses the dispatched author that ADR-0078 removed the lease substrate to
  admit, reinstating the deadlock that decision eliminated. The delegated write is
  recorded and real — a review-findings write whose dispatching session was the
  holder exactly.
- **Reintroduce a lease or delegated-authority token for dispatched authors.**
  Rejected: ADR-0078 retired that substrate for good reasons, and no replacement
  coordination state is needed. Dispatch ancestry is already durable.
- **Enforce the boundary in the storage layer rather than at the caller-facing
  boundary.** Rejected: the internal producers that write artifacts — lifecycle
  state transitions, kickback, kind migration, creation-time seeding, and the work
  service — carry no external caller identity. They are the owning context acting
  on its own aggregate, not foreign callers, and a storage-layer gate would have
  to invent an identity for them to pass.
