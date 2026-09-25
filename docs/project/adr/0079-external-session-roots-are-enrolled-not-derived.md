---
visibility: public
number: 79
date: 2026-09-03
description: The process instance that anchors an externally hosted agent session is bound by an enrollment in which the enrolling process is itself the connecting peer, because no rule derives that anchor from kernel process evidence alone.
---

# ADR-0079: External session roots are enrolled, not derived — ADR

## Context

Agent sessions the daemon does not launch carry no session identity file and no
per-terminal login, so authenticated session-scoped operations refuse them. The
daemon does hold kernel evidence about local callers: peer user and process
identity on its Unix socket, and that process's ancestry with per-process start
times.

That evidence proves containment — which process tree a caller sits in — and a
session could be authenticated by membership in a tree if one process instance
in it were bound to the session. The question was where that binding comes
from. Deriving it from the same kernel evidence would have required no new
integration point anywhere, and every supported harness would have been covered
by the daemon alone.

## Decision

The anchor is bound by an enrollment in which the enrolling process is itself
the connecting peer. The daemon binds the attested peer instance and accepts no
nominated process id, session identifier, or lineage description. Hooks and
ordinary requests authenticate by membership in an enrolled tree and never
create, select, widen, or replace an anchor.

## Alternatives Considered

**Admit the anchor by executable identity.** Compare each ancestor's executable
against the platform's configured agent binaries and bind the single match.
Rejected on substrate: supported manual invocations resolve to interpreted entry
points, so the kernel executable is an interpreter shared with unrelated
processes on the host. The script identity that would disambiguate is not
readable server-side — inspecting another process's open files returns nothing
on Darwin — leaving only the argument vector, which the caller controls.

**Derive the anchor from a single attested connection.** Choose the correct
ancestor of a hook receiver. Rejected as underdetermined: for a receiver below
processes A and B, the world where A is a per-invocation shell and B hosts the
session presents identical process identity, executable, start time, and
ancestry to the world where A hosts the session and B launched it. Any
deterministic choice is wrong in one admissible world.

**Derive the anchor by intersecting ancestries across several connections.**
Rejected as circular: it presupposes knowing which connections belong to one
session, which is the same question. Two receivers under a shared ancestor fit
one session rooted at that ancestor and two sessions launched beneath it
equally. Merging over-grants to every descendant of the shared ancestor;
separating fragments a session whose per-invocation processes differ. No hook
count, depth rule, or timing window removes the ambiguity — each only adds an
environmental assumption.

**Group connections by the harness's own conversation identifier.** Rejected as
caller-selected: the identifier travels in a payload a caller can write. Under
an intersecting rule, a foreign claimant sharing only a login shell or
multiplexer moves the anchor upward and widens authorization. First-claimant
-wins permits squatting, accepting later claims permits poisoning, rejecting
conflicts permits targeted denial of service, and an unguessable identifier
would be a credential.

**Use liveness to identify the durable host.** Rejected as negative evidence
only. Liveness disqualifies a candidate that dies while its session continues,
and start time prevents a reused process id from impersonating an earlier
instance, but a per-invocation shell may live arbitrarily long and no finite
wait proves a process is the durable host.

## Consequences

Coverage follows the launch path rather than the harness. A session started
through a path the platform or its integrators control enrolls and is
authenticable, with no per-harness knowledge anywhere in the mechanism. An
invocation that passes no such path enrolls nothing: its session stays
observable through the hook route and refuses every session-scoped call.

Enrollment stores an identity binding, not a credential, so nothing is issued
and nothing sits at rest.

The authorization boundary is the enrolled process's complete descendant
subtree. An anchor enrolled at a shared shell or multiplexer would authorize
sibling branches, so enrollment is per session.

Self-enrollment permits a process to create a session rooted at itself. It never
permits impersonating an existing one, because the daemon binds only the peer it
attested.

This follows SPIFFE/SPIRE's separation of registration from attestation:
kernel-attested properties are matched against registration entries that a
trusted act created, rather than inferred from the attested properties
themselves.

## Status

Superseded by ADR-0103

## See Also

- docs/project/design/architecture/local-caller-attestation.md
