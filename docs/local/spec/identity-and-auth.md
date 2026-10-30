---
description: 'Authoritative surface for system-wide identity, authentication, and person management.'
visibility: 'public'
---

# Identity and Auth — Spec

## Required reads

- @docs/local/spec/teleclaude-config.md
- @docs/local/spec/command-surface.md
- @docs/local/spec/session-identity-truth.md

## What it is

TeleClaude uses one identity model across API, TUI, and adapters:

- person identity comes from global `people` config,
- session identity comes from daemon-owned session records,
- authorization is decided in the client process that serves the caller — the CLI
  for a `telec` command, the TUI for its own actions — before any request reaches
  the daemon; the daemon performs what it is asked and records who asked from the
  identity the request carries.

## Canonical fields

### 1) Person source of truth

| Field   | Type   | Description                                                                                                                                                                                                                                  |
| ------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`  | string | Display name used in UI and logs.                                                                                                                                                                                                            |
| `email` | string | Canonical email address used for OTP authentication.                                                                                                                                                                                         |
| `role`  | enum   | Optional platform role — one of `admin`, `member`; absent when the person holds no role at platform scope. A person's authority for an object is their effective role for it (`local/projects/teleclaude/design/architecture/scoped-roles`). |

People are defined in global `~/.teleclaude/teleclaude.yml` under `people`.

### 2) Runtime identity headers

A client that asks the daemon to act carries, on every request, the identity it
resolved for its caller (§6):

- `x-caller-session-id`: the caller's TeleClaude session, when the caller is a
  session. Lineage, initiator linkage, and every act scoped to the caller's own
  session key on it.
- `x-caller-principal`: the caller's principal — `human:<email>` or the carried
  system principal.

- `x-caller-role`: the agent role the caller's session resolves to, when it has
  one. `x-caller-system-role` is still sent beside it, carrying the role's
  legacy projection (`local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`)
  for computers that read only the older name; neither is authority for
  anything beyond the carried identity.
  Within one computer the CLI and the daemon are one installation, so a local
  carried identity carries `x-caller-role` exactly when the session's record
  carries a role: its absence is the session's own rolelessness — a
  conversational, generic-create or desk session — never a legacy gap to
  interpret. Across computers only the principal crosses as authority
  (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`).
  A legacy `x-caller-system-role` is read for provenance alone, and the daemon
  takes carried identity as given, with no confirming lookup, as §2 states.

- `x-caller-human-role`: the person role that authorizes the caller, when the
  caller is a person.
- `x-caller-email`: the person's email, when the caller is a person.
- `x-caller-entry-point`: the door the request came through — an agent session,
  the CLI at a terminal, or the TUI.
- `x-caller-company`: the company recorded on the caller's session, when it has
  one. It carries business context to a daemon action without giving the caller
  a role or credential; the session record remains its source of truth.
- `x-teleclaude-daemon-token`: the daemon's own credential for the calls it makes
  into its request surface. Its value is generated once per daemon process, held
  only in that process's memory, and never persisted or exported, so no other
  process can produce a value that resolves. A caller presenting it resolves to
  the daemon's system principal with no human identity attached, and is subject
  to the same dispatch privilege as any other system-role caller.

The daemon takes the carried identity as given. It performs no lookup to confirm
it, resolves no terminal signal, compares no tmux session, and applies no role
clearance to it; a request that carries none reaches the daemon as a caller with
no identity. Work the daemon runs for a caller after accepting its
request carries that caller's identity on the requests the work makes.

Identity is established once, at the boundary a human crosses to reach the platform,
and carried by everything inside it. A person running a `telec` command from a shell,
or launching the TUI, has no session to identify them, so their terminal login
answers who they are; the TUI then holds that resolved identity for as long as it
runs. Everything already inside carries identity instead of resolving it: an agent
session is identified by its session record, work dispatched for a todo takes its
human root from that todo's creation record, and a standing role resolves to its own
system principal.

A process that is not a human arriving from outside therefore resolves no terminal
login — the daemon and every process it spawns included. Resolving identity from
ambient state deep inside the platform attributes work to whoever last
authenticated on the host rather than to whoever it belongs to, and in a
multi-person installation that is one identity standing in for all of them.

<!-- planned:local-operator-identity -->

A caller on this computer for which nothing above resolves an identity — no
session, no live terminal login, no identity carried into the TUI — is the
computer's operator: the operating-system user the installation runs as. It
resolves to the system principal `system:operator`. That principal names no
person, so the operator's work is attributed to no human and no person-bound
service acts for it (§8). A session identity document that names no admissible
session is not the operator; that caller stays without identity (§6).

<!-- /planned:local-operator-identity -->

### 3) System-principal sessions

A session with no human origin carries the system principal `system:daemon`, told
apart from other such sessions by its session id. It is identified exactly like a
human-rooted session: by the session record its identity document names, resolved
in the client (§6), and the daemon consumes the identity the request carries (§2).
No token is issued, stored or presented for any session.

<!-- planned:local-operator-identity -->

A session the platform keeps for an agent it did not launch carries
`system:operator` and no person role when no terminal login names a person for
it. It is cleared as the operator, it is a session the system started when it
ends, and no person's conversation memory is drawn from it. How the operator's
commits are attributed is owned by
`local/projects/teleclaude/spec/feature/agent_runtime/sealed-commit`.

<!-- /planned:local-operator-identity -->

**`telec auth whoami`:**
Inside a session and at a terminal alike, `whoami` resolves its caller in the CLI process
through the shared caller resolution in §6 and prints the answer; it sends no request to
the daemon. The answer is the principal (`human:<email>` for a person, whether a session
carries it or a terminal login names them) and the role that authorizes the caller, plus
the person's email and terminal at a terminal. A process whose session identity document
identifies no open session on this computer is told so and is given no terminal identity.
The daemon's `GET /auth/whoami` endpoint answers the same question for clients of its API.
For a session caller, that self-query also returns the session's recorded
configuration subject. A CLI event producer reads it to state the event's origin
home without listing other sessions; it is absent when the caller has no
session or the session has no recorded home.

For a person caller registered on this computer, the self-query also returns
that person's slug, so a UI client addresses the caller's own person subject
without listing people; it is absent for any other caller.

**Principal types:**

<!-- planned-change:local-operator-identity -->

| Format          | When set                                                          | Credential                                                         |
| --------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| `human:<email>` | Session created with a human identity (human_email set)           | None                                                               |
| `system:daemon` | The daemon process itself, and every session with no human origin | Process-local daemon credential for the daemon; none for a session |

<!-- change:local-operator-identity -->

| Format            | When set                                                                                                 | Credential                                                         |
| ----------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `human:<email>`   | Session created with a human identity (human_email set)                                                  | None                                                               |
| `system:daemon`   | The daemon process itself, and every session with no human origin                                        | Process-local daemon credential for the daemon; none for a session |
| `system:operator` | A local caller with no other identity (§2), and a session kept for an agent with no person resolved (§3) | None                                                               |

<!-- /planned-change:local-operator-identity -->

### 4) Terminal + TUI authentication

- `telec auth login <email>` writes a TTY-scoped login file.
- The TUI launcher resolves the operator's identity in the outer terminal before it
  creates the `tc_tui` tmux session, and carries that resolved identity into the
  session alongside the TUI runtime marker.
- The TUI holds the identity it was launched with for as long as it runs. It does
  not re-resolve identity from its own pane, which is a terminal of its own and
  carries no login document.
- That carried identity is honoured only where the TUI runtime marker is present.
  The marker reaches the `tc_tui` session and no other, because it is absent from
  the environment filters that build agent sessions.

### 5) Multi-user enforcement

<!-- planned-change:local-operator-identity -->

- If `people` contains more than one registered person:
  - a terminal that carries no login document of its own presents no terminal-email
    signal, so a person opening a fresh terminal authenticates on it before any
    identity-bearing command succeeds,
  - TUI launch requires prior `telec auth login`,
  - a client refuses a caller that has neither a session identity nor a terminal
    login naming a registered person, before it sends any request, except for a
    command declared for the machine's own account.
- If `people` has zero/one person, the legacy fallback role is still allowed for
  tmux callers without session identity, and with exactly one person that person
  answers a terminal that has no document of its own.
- Whichever mode is in force, a login already bound to a live terminal keeps
  answering for that terminal. One person authenticating never unbinds another
  person's open terminals; only the terminal's own disappearance does.
- Whichever mode is in force, a caller outside any session needs no login for a
  command declared for the machine's own account — the installation verbs
  (`local/projects/teleclaude/design/cli-authorization-matrix`), whose caller
  there is the operating-system account the installation belongs to
  (`general/principle/trust-and-guardrails`).

<!-- change:local-operator-identity -->

- If `people` contains more than one registered person:
  - a terminal that carries no login document of its own presents no terminal-email
    signal, so its caller is the operator (§2) until a person logs in on it,
  - a TUI launched without a login carries the operator.
- If `people` has zero/one person, the legacy fallback role is still allowed for
  tmux callers without session identity, and with exactly one person that person
  answers a terminal that has no document of its own.
- Whichever mode is in force, a login already bound to a live terminal keeps
  answering for that terminal. One person authenticating never unbinds another
  person's open terminals; only the terminal's own disappearance does.

<!-- /planned-change:local-operator-identity -->

### 6) Authorization

<!-- planned-change:local-operator-identity -->

Authorization happens once, in the client process that serves the caller, before
the client sends any request:

- the caller resolves from the identity it carries, never from a claim it
  supplies: a caller inside a session resolves from its session record, reached
  through the session id its identity document names, and a principal copied into
  that document is never trusted; an agent running outside the platform resolves
  from the headless session the platform keeps for it, found by the native
  session id its runtime exports to the agent's tool processes
  (`local/projects/teleclaude/spec/session-identity-truth`), and is cleared as
  that session; any other caller outside a session resolves from its terminal
  login, and the TUI from the identity it was launched with,

- a session's principal resolves through the principal-resolution capability; its
  person role for a command is that person's effective role at the command's scope
  (`local/projects/teleclaude/design/architecture/scoped-roles`), read from the people registry and
  company rosters when the command runs, so a changed role applies from the
  session's next command, and a gate grants a session no role its principal does
  not resolve to; a session acting for a person is also bounded by that role,

- a `telec` command executing locally is cleared against its verb band
  (`local/projects/teleclaude/design/cli-authorization-matrix`) once, before the
  first request leaves its process; a command addressed to another computer
  authenticates its caller at the edge and is relayed without sender-side
  authorization, apart from a worker's session-to-session acts, which its own
  computer refuses
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`).
  The owning computer authorizes the relayed principal.
  The TUI follows the same boundary for each action
  (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`),

- a caller that resolves to no person and no system principal is refused before
  any request is sent, unless it is outside any session and the command is
  declared for the machine's own account (§5); a role outside the band is refused
  with the not-permitted failure naming the role and the verb,
- the client carries the identity it resolved on every request (§2); the daemon
  verifies no caller and applies no verb band of its own to a request from its
  own clients; a daemon deciding an act another computer relays to it resolves
  the relayed principal against its own registries and applies that act's person
  band (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`),
- the daemon applies the rules that scope an act to its objects — a session acts
  on no orchestrator that dispatched it, a reminder belongs to its session, a session's result,
  file, and escalation act for that session, a claimed todo is written only by its
  claiming group, a person-bound service acts only for its person — against the
  identity the request carries.

<!-- change:local-operator-identity -->

Authorization happens once, in the client process that serves the caller, before
the client sends any request:

- the caller resolves from the identity it carries, never from a claim it
  supplies: a caller inside a session resolves from its session record, reached
  through the session id its identity document names, and a principal copied into
  that document is never trusted; an agent running outside the platform resolves
  from the headless session the platform keeps for it, found by the native
  session id its runtime exports to the agent's tool processes
  (`local/projects/teleclaude/spec/session-identity-truth`), and is cleared as
  that session; any other caller outside a session resolves from its terminal
  login, and the TUI from the identity it was launched with,

- a session's principal resolves through the principal-resolution capability; its
  person role for a command is that person's effective role at the command's scope
  (`local/projects/teleclaude/design/architecture/scoped-roles`), read from the people registry and
  company rosters when the command runs, so a changed role applies from the
  session's next command, and a gate grants a session no role its principal does
  not resolve to; a session acting for a person is also bounded by that role,

- a `telec` command executing locally is cleared against its verb band
  (`local/projects/teleclaude/design/cli-authorization-matrix`) once, before the
  first request leaves its process; a command addressed to another computer
  authenticates its caller at the edge and is relayed without sender-side
  authorization, apart from a worker's session-to-session acts, which its own
  computer refuses
  (`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`).
  The owning computer authorizes the relayed principal.
  The TUI follows the same boundary for each action
  (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`),

- a local caller that resolves to no person and no system principal is the
  operator (§2) and is cleared as `system:operator` is cleared, with every band
  admitting it; a caller whose session identity document names no admissible
  session is refused before any request is sent; a role outside the band is
  refused with the not-permitted failure naming the role and the verb,
- the client carries the identity it resolved on every request (§2); the daemon
  verifies no caller and applies no verb band of its own to a request from its
  own clients; a daemon deciding an act another computer relays to it resolves
  the relayed principal against its own registries and applies that act's person
  band (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`),
- the daemon applies the rules that scope an act to its objects — a session acts
  on no orchestrator that dispatched it, a reminder belongs to its session, a session's result,
  file, and escalation act for that session, a claimed todo is written only by its
  claiming group, a person-bound service acts only for its person — against the
  identity the request carries.

<!-- /planned-change:local-operator-identity -->

### 7) Session lineage invariant (child sessions)

Child worker sessions should be linked to parent orchestrator session identity when a caller session exists.

- `/sessions/run` accepts a terminal or TUI caller, whose carried identity names no session.
- When a caller session identity is present, `initiator_session_id` is written for child-session linkage.
- Requests without caller session identity remain valid, but they create unlinked sessions because terminal/TUI callers do not have a parent TeleClaude session.
- A lifecycle session the runner auto-dispatches for a todo whose `created_by_principal` is a `human:<email>` establishes that human as its root identity: the session row carries the owning human's `principal`/`human_email`, so its resolved principal is `human:<email>` rather than `system:daemon`, and the rest of the chain inherits it through `initiator_session_id`. The session's `system_role` is left untouched, so the attribution does not change what the session is authorized to do.

### 8) Person-bound service identity

Person-bound service access selects its person from the identity the request carries (§2), which the client resolved for its caller (§6):

- A managed human-rooted session resolves from its daemon-owned session record and inherited `human:<email>` principal.
- A terminal or trusted TUI caller resolves from authenticated terminal email and the global person registry.
- A system-only principal has no implicit person, even when it has command clearance, and is denied person-bound service access.
- The resolved email must map to exactly one configured person with a canonical slug before credential lookup begins.
- The session identity marker in `$TMPDIR` is a client-side transport input, not authority for person selection. Person-bound handlers never read it directly and never accept a person from tool arguments.

The protected edge translates `CallerIdentity` into a typed service invocation context. Downstream runtime and credential components receive the resolved person slug or an explicit absence; they do not inspect headers, session files, or identity storage themselves. Failure to resolve a person is a request denial, not a fallback to the sole configured user or to global credentials.

## Known caveats

- Headless/native hook identity follows `session-identity-truth`; it is distinct from terminal login.
- TUI login bridge is read-only runtime context, not a replacement for `telec auth login`.
- The daemon's request surface is not an isolation boundary between local
  processes. Every agent runs as the same operating-system user as the daemon, and
  a process that writes to the local socket directly is performed as whatever
  identity it carries.

## See Also

- docs/local/adr/0101-clients-authorize-and-the-daemon-trusts-carried-identity.md — why clients authorize and the daemon trusts the identity a request carries.

<!-- planned:local-operator-identity -->

- docs/local/adr/0152-an-unidentified-local-caller-is-the-computers-operator.md — why a local caller with no identity acts as the computer's operator.

<!-- /planned:local-operator-identity -->
