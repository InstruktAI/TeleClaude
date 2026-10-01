---
visibility: internal
number: 97
date: 2026-09-22
description: The human-involvement record is resolved from the acting session's observed human-input recency and never refuses the act it annotates.
---

# Involvement Is Observed, Not Adjudicated — ADR

## Context

`--human-involved` is an audit annotation. Both `general/policy/human-involvement-recording`
and `general/principle/trust-and-guardrails` state that it authorizes nothing: it
widens no brief, suspends no ownership, and is never consulted to permit an
operation.

The implementation contradicted that. The declaration was treated as a claim to be
adjudicated against the acting session's transcript, and a claim judged unsupported
aborted the act it described — `telec code commit` exited before committing, and todo
creation returned 400 before the todo existed. A non-authorizing annotation therefore
held a veto over every act it annotated.

The claim's shape is what made adjudication look necessary. `--human-involved` read
"shaped by recent qualified human input", and being shaped by a human does not decay:
the human's direction stays live in an agent's context for the rest of the session,
long after the human has gone. An agent asserting it is telling the truth about its
own state. The platform, grading that assertion against a 90-second window, is
answering a different question, and the agent receives the mismatch as a refusal of
its work rather than as a correction of a term.

The verdict also travelled over `POST /sessions/self/human-involvement`, a route with
exactly one caller. The commit path already holds the database connection the route
reads, in the same module, so the round trip added a daemon-availability dependency
to committing in exchange for nothing.

## Decision

The record is **resolved from observation, never adjudicated from a claim**. The
platform reads the recency of authenticated human input to the acting session and
writes the record from that reading: inside the window `true`, outside it `false`.
The act proceeds either way.

A declaration the observation does not support records `false` — the same value
omission records — and is reported as a discard carrying the observed age and never
the supplied reason, so over-declaration is measured rather than guessed at. A
declaration carrying no reason is still refused, as argument validation over the
invocation rather than a judgement about the human.

The seam is named for what it does: it resolves a record, it does not validate a
claim. Resolution happens in the calling process against the session store it already
holds, and `POST /sessions/self/human-involvement` is removed. An unreadable store
records `false` rather than failing the act, so committing carries no availability
dependency on the daemon for this annotation.

The flag's own description stops asserting that a human shaped the work and states
what the record means: a human was present at this act, measured from their last
input rather than from the agent's continued use of their direction.

## Consequences

The annotation can no longer stop work. The worst outcome of a stale declaration is
the record that silence would have produced, which is what the fail-toward-audit rule
already required of it.

No agent is told its reading of its own conversation is false. The platform records a
narrower, observable fact and leaves the agent's account of the conversation alone.
The divergence between the two is now visible in the discard record, where it can be
counted, instead of arriving as friction at a commit boundary.

The record becomes a weaker claim than it read as before: it reports presence at the
act, not that a human shaped it. That is the only claim the platform can actually
substantiate, and the audit question it answers — which commitments were made in my
name while I was not there — is unchanged.

Committing loses a daemon round trip and the failure mode that came with it.

## Alternatives Considered

**Keep the adjudication and soften only the flag's wording.** Rejected: the wording is
what made agents declare in good faith, but the refusal is what turns the annotation
into a gate. Correcting the term while leaving the veto in place would produce fewer
refusals of the same illegitimate kind.

**Keep the declaration authoritative and drop the recency check entirely.** Rejected:
an unbounded self-assessment records `true` for the rest of every session a human ever
touched, which is exactly the over-selection that empties the record of signal.

**Keep the HTTP route as the resolution seam.** Rejected: it has one caller, crosses no
process boundary the caller does not already cross in-process, and buys the commit path
an availability dependency on the daemon for a value the commit can always default.
