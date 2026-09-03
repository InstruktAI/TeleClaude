---
description: Kernel-attested peer credentials on the daemon Unix socket, and the registered-root ancestry membership that derives which session a caller belongs to — the authentication path for agent sessions with no pane on TeleClaude's own tmux server.
delivered_by:
  - external-session-identity
---

# Local Caller Attestation — Design

## Required reads

- @docs/project/design/architecture/api-server.md

## Purpose

Authenticate a caller that has no pane on TeleClaude's own tmux server, and
determine which session it belongs to without the caller asserting it.

Caller verification's dual-factor path pairs a client-supplied session id with a
tmux session name read from TeleClaude's own server. A caller with no such pane
supplies no second factor. This design supplies one from kernel-held facts: the
identity of the process connected to the daemon's Unix socket, and that
process's ancestry. Association is by membership: the daemon binds one immutable
process instance as a session's root, and a caller belongs to that session when
the root occurs in the caller's verified ancestry. The caller names nothing.

Kernel peer credentials alone do not discover a session. They identify a
process. The binding that gives a process instance a session meaning is minted
by the daemon at session start, from a connection the daemon itself attested.

## Inputs/Outputs

**Inputs**

- The connected peer socket for each request on the daemon's Unix socket,
  carrying the peer process identity and peer user.
- The ancestry of that peer process, read through the platform process
  interface as ordered process instances.
- The session root bindings the daemon holds for open sessions.
- The platform's configured agent binary registry, used at session start to
  admit a root candidate by executable identity.

**Outputs**

- An attested caller fact for the request being served: peer process identity,
  peer user, and the derived session — each distinguishable from every
  client-supplied signal.
- Authorization under the derived session's existing principal and role,
  through the existing clearance path.
- On failure: refusal. No session-scoped operation falls back to machine-global
  terminal identity.

## Invariants

- **A process instance is identified by host, user, process id, and kernel
  start time.** The start time is part of the identity, not metadata about it.
  Every recording and every comparison carries it.
- **Kernel evidence is never client-supplied.** Peer process identity and peer
  user come from the connected socket; ancestry comes from the platform process
  interface. Neither is read from a header, an environment variable, or a
  request body.
- **The session is derived, never claimed.** A caller-supplied session reference
  establishes no binding on this path.
- **A session's root binding is minted by the daemon from a connection it
  attested**, at session start, and is immutable for the life of the session. No
  process reports its own root, and no durable record written outside an
  attested connection can establish one.
- **Membership is exact and unique.** A caller resolves to a session when that
  session's root process instance occurs in the caller's verified ancestry, and
  exactly one open session matches. Zero matches refuse as unproved. More than
  one refuses as ambiguous. Nearest, oldest, newest, and most-plausible are not
  tie-breakers; there is no tie-break.
- **A root candidate is admitted by executable identity**, compared against the
  configured agent binary registry — never by argument vector, process title,
  working directory, environment, command text, or a fixed ancestor depth.
- **The harness's own session identifier is provider metadata.** It may
  corroborate a derived agent; it never selects a session, authorizes a
  rebinding, or recovers a dead root.
- **Attestation authenticates; it does not elevate.** The derived session
  carries the principal and role it already has. No role is granted, no
  clearance widened, no authority minted.
- **No credential is issued and none is stored.** Each call re-derives the
  session from live kernel evidence: no token for these sessions, no identity
  file, no allocated directory, and so no credential at rest.
- **Inheritance is structural.** A descendant of the root is inside the attested
  tree, so child processes authenticate with no propagation step.
- **Liveness is established before inspection and revalidated after it.** The
  daemon holds a liveness watch on the peer, then reads ancestry, then confirms
  the peer and the matched root are the same instances before authorizing.
- **Failure is refusal.** Absent peer credentials, unreadable ancestry, no
  matching root, multiple matching roots, a start-time mismatch, a peer-user
  mismatch, a lost liveness watch, or a closed session each refuse.

### Admission invariant

Each supported harness exposes exactly one long-lived process instance per
top-level session whose executable identity is in the configured agent binary
registry. A harness whose identifiable process exits before its first hook is
unattestable and is refused rather than matched by a weaker signal.

A single process instance hosting two independent top-level sessions has no
sound association under this design: both sessions present identical ancestry
evidence, and no server-side refinement separates them. Such a harness is
refused.

## Primary flows

### 1. Minting the root binding at session start

```mermaid
sequenceDiagram
    participant A as Externally started agent process
    participant R as Hook receiver (its descendant)
    participant D as Daemon
    participant S as Session store

    A->>R: agent session start hook
    R->>D: connect over the Unix socket and deliver the hook
    D->>D: attest the receiver's process instance
    D->>D: walk ancestry; match already-registered roots first
    D->>D: no registered root — admit the single ancestor whose executable identity is in the registry
    D->>S: mint the session and persist its root binding
    D->>D: enqueue the hook event under that session
```

An ancestry that already contains a registered root is a descendant invocation:
it stays owned by that session and mints nothing. An ancestry with no registry
match, or with more than one candidate and no registered ancestor, is refused as
unattestable.

The daemon enqueues the event after minting, so the durable hook record is
written under a session whose root the daemon attested rather than under an
identifier supplied to it.

### 2. Deriving the session on an authenticated call

```mermaid
sequenceDiagram
    participant C as Any process in the session
    participant K as Kernel
    participant D as Daemon request surface
    participant I as Identity context

    C->>D: request over the Unix socket
    D->>D: establish the liveness watch
    D->>K: read peer credentials for this connection
    K-->>D: peer process instance, peer user
    D->>I: request + attested peer fact
    I->>I: verify ancestry; collect open sessions whose root it contains
    I->>I: exactly one — resolve its principal and role; otherwise refuse
    I-->>C: response under that session, or refusal
```

A top-level agent process and a subagent several levels down follow this same
path. Only a session-start hook may mint a binding; an ordinary request that
matches no root is refused rather than bootstrapped.

### 3. Self-identification

Asking who the caller is answers from the session derived in flow 2. A caller
with no attested session receives the terminal answer only when no session was
derived, and that answer never carries a session identity.

## Failure modes

| Condition                                                                 | Outcome                                                        |
| ------------------------------------------------------------------------- | -------------------------------------------------------------- |
| No registered root in the caller's ancestry                               | Refuse. No terminal or machine-global identity substitutes.    |
| More than one registered root in the ancestry                             | Refuse as ambiguous.                                           |
| Ordinary request carrying no binding                                      | Refuse. Only a session-start hook mints one.                   |
| Session-start ancestry with no registry match                             | Refuse as unattestable.                                        |
| Session-start ancestry with several candidates and no registered ancestor | Refuse as ambiguous.                                           |
| A durable hook record is the only evidence                                | Refuse to mint. Its writer was never attested.                 |
| The harness identifier names a session whose root differs                 | Refuse. The identifier never rebinds.                          |
| The bound root has exited                                                 | Refuse, including when its process id is live again.           |
| A start time cannot be read, or changes during resolution                 | Refuse.                                                        |
| A parent edge changes during the ancestry walk                            | Refuse; a new request may retry.                               |
| Peer credentials unavailable on the platform or transport                 | Refuse.                                                        |
| A descendant is re-parented before it is first observed                   | Refuse; ancestry no longer proves lineage.                     |
| Daemon restart                                                            | Restore only the bindings whose root instance still validates. |
| A caller presents a session id                                            | Unchanged for pane-attached callers; establishes nothing here. |

Process-group membership, POSIX session id, controlling terminal, tmux
membership, working directory, environment, command text, the harness's session
identifier, and the machine-global login are not evidence on this path. Each is
shared, mutable, caller-influenced, or several of those at once.

A descendant of the root is inside the session by construction. Distinguishing
code the session was meant to run from code it was induced to run is not a
session-attribution question and is not answered here.

## See Also

- docs/project/spec/feature/identity/headless-session-identity.md — the behavioral contract this design realizes.
- docs/project/spec/feature/identity/caller-verification.md — the resolution precedence this path joins.
- docs/project/spec/feature/integration/headless-session-bootstrap-from-hook.md — the bootstrap that mints the root binding.
- docs/project/spec/session-identity-truth.md — the route classification that names these callers.
