---
description: Kernel-attested peer credentials on the daemon Unix socket, and the enrolled-root ancestry membership that derives which session a caller belongs to — the authentication path for agent sessions with no pane on TeleClaude's own tmux server.
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
process's ancestry.

Association is by membership in an enrolled tree. One process instance is bound
to a session by an enrollment act in which that process is itself the connecting
peer, and a caller belongs to the session when the bound instance occurs in the
caller's verified ancestry.

## Inputs/Outputs

**Inputs**

- The connected peer socket for each request on the daemon's Unix socket,
  carrying the peer process identity and peer user.
- The ancestry of that peer process, read through the platform process
  interface as ordered process instances.
- The root bindings the daemon holds for open sessions.

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
- **A root is bound only to the enrolling peer itself.** The daemon binds the
  process instance on the other end of the enrolling connection. It accepts no
  nominated process id, no session identifier, and no lineage description; a
  process can enroll itself and nothing else.
- **A root is immutable once bound**, for the life of the session.
- **Hooks authenticate; they never enroll.** A hook connection may resolve to a
  root already in its ancestry. It never creates a root, selects among
  candidates, widens one, or replaces one. Ordinary requests likewise.
- **Membership is exact and unique.** A caller resolves to a session when that
  session's root process instance occurs in the caller's verified ancestry, and
  exactly one open session matches. Zero matches refuse as unproved. Where
  nested enrolled roots occur, the nearest enrolled ancestor wins because it is
  the narrowest authority; any other multiplicity refuses.
- **What a process is takes no part in any decision.** Executable identity,
  argument vector, process title, working directory, environment, and command
  text are read for nothing. Ancestry proves containment; enrollment supplies
  the boundary.
- **The harness's own session identifier is provider metadata.** It records
  which conversation a hook belongs to. It never selects a session, groups
  evidence, authorizes a rebinding, or recovers a dead root.
- **Attestation authenticates; it does not elevate.** The derived session
  carries the principal and role it already has. No role is granted, no
  clearance widened, no authority minted.
- **No credential is issued and none is stored.** Each call re-derives the
  session from live kernel evidence: no token for these sessions, no identity
  file, no allocated directory, and so no credential at rest.
- **Inheritance is structural.** A descendant of the root is inside the enrolled
  tree, so child processes authenticate with no propagation step.
- **Liveness is established before inspection and revalidated after it.** The
  daemon holds a liveness watch on the peer, then reads ancestry, then confirms
  the peer and the matched root are the same instances before authorizing.
- **Root death ends the association.** Descendants that outlive the root, or are
  re-parented, resolve to nothing. They never fall back to a shallower ancestor
  or to peer-user identity.
- **Failure is refusal.** Absent peer credentials, unreadable ancestry, no
  enrolled root, a start-time mismatch, a peer-user mismatch, a lost liveness
  watch, or a closed session each refuse.

### Coverage boundary

Enrollment is harness-neutral: the entry point enrolls itself and then becomes
whatever agent it was asked to run, so no agent CLI is named anywhere in the
mechanism and none is covered or excluded by being named. It reaches every
session started through a launch path the platform or its integrators control.

An invocation that reaches an agent binary without passing such a path enrolls
nothing. Its session remains observable through the existing hook route and
carries no root, and every session-scoped call from it is refused. Extending
coverage to that case means placing an entry point in the invoking environment,
which is a decision about that environment rather than a property of this
design.

## Primary flows

### 1. Enrolling the root

```mermaid
sequenceDiagram
    participant W as Platform entry point
    participant D as Daemon
    participant S as Session store
    participant A as Agent process (same instance)

    W->>D: enroll over the Unix socket
    D->>D: attest the connecting peer instance
    D->>S: mint the session; bind that instance as its root
    D-->>W: session established
    W->>A: replace this process image with the agent
```

The entry point enrolls itself and then becomes the agent: replacing a process
image preserves its process id and start time, so the bound instance names the
running agent process. No supervisor process is left behind, and the daemon
still did not launch the agent.

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
    I->>I: verify ancestry; find enrolled roots within it
    I->>I: the nearest enrolled root resolves; none or an unresolvable set refuses
    I-->>C: response under that session, or refusal
```

A top-level agent process, a hook receiver, and a subagent several levels down
follow this same path.

### 3. Self-identification

Asking who the caller is answers from the session derived in flow 2. A caller
with no enrolled root receives the terminal answer, and that answer never
carries a session identity.

## Failure modes

| Condition                                                                  | Outcome                                                                |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| No enrolled root in the caller's ancestry                                  | Refuse. No terminal or machine-global identity substitutes.            |
| Enrolled roots in the ancestry that do not resolve to a single nearest one | Refuse as ambiguous.                                                   |
| An enrollment naming a process other than the connecting peer              | Refuse.                                                                |
| A hook or request attempting to establish a root                           | Refuse the establishment; the call itself resolves only by membership. |
| A durable record written outside an attested connection                    | Contributes no evidence toward a root.                                 |
| The harness identifier names a session whose root differs                  | Refuse. The identifier never rebinds.                                  |
| The bound root has exited                                                  | Refuse, including when its process id is live again.                   |
| A start time cannot be read, or changes during resolution                  | Refuse.                                                                |
| A parent edge changes during the ancestry walk                             | Refuse; a new request may retry.                                       |
| Peer credentials unavailable on the platform or transport                  | Refuse.                                                                |
| A descendant is re-parented away from its root                             | Refuse; ancestry no longer proves lineage.                             |
| Daemon restart                                                             | Restore only the bindings whose root instance still validates.         |
| A caller presents a session id                                             | Unchanged for pane-attached callers; establishes nothing here.         |

Process-group membership, POSIX session id, controlling terminal, tmux
membership, working directory, environment, command text, the harness's session
identifier, and the machine-global login are not evidence on this path. Each is
shared, mutable, caller-influenced, or several of those at once.

An entry point enrolls once per session, and never a shared shell or
multiplexer process.

Every descendant of the root is inside the session by construction.
Distinguishing code the session was meant to run from code it was induced to run
is not a session-attribution question and is not answered here.

## See Also

- docs/project/adr/0079-external-session-roots-are-enrolled-not-derived.md — why the anchor is enrolled rather than derived.
- docs/project/spec/feature/identity/headless-session-identity.md — the behavioral contract this design realizes.
- docs/project/spec/feature/identity/caller-verification.md — the resolution precedence this path joins.
- docs/project/spec/feature/integration/headless-session-bootstrap-from-hook.md — the hook route that makes an unenrolled session observable.
- docs/project/spec/session-identity-truth.md — the route classification that names these callers.
