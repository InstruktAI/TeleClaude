---
description: 'Authoritative surface for system-wide identity, authentication, and person management.'
visibility: 'public'
---

# Identity and Auth — Spec

## Required reads

- @docs/project/spec/teleclaude-config.md
- @docs/project/spec/command-surface.md
- @docs/project/spec/session-identity-truth.md

## What it is

TeleClaude uses one identity model across API, TUI, and adapters:

- person identity comes from global `people` config,
- session identity comes from daemon-owned session records,
- authorization is enforced server-side on every protected route.

## Canonical fields

### 1) Person source of truth

| Field   | Type   | Description                                           |
| ------- | ------ | ----------------------------------------------------- |
| `name`  | string | Display name used in UI and logs.                     |
| `email` | string | Canonical email address used for OTP authentication.  |
| `role`  | enum   | One of: `admin`, `member`, `contributor`, `newcomer`. |

People are defined in global `~/.teleclaude/teleclaude.yml` under `people`.

### 2) Runtime identity headers

Protected local API routes use these headers:

- `x-caller-session-id`: TeleClaude session identity (daemon-owned, for lineage and role derivation).
- `x-tmux-session`: tmux server session name for cross-check.
- `x-telec-email`: terminal login identity (`telec auth login`) for a human entering
  the platform from outside it.
- `x-teleclaude-daemon-token`: the daemon's own credential for the calls it makes
  into its request surface. Its value is generated once per daemon process, held
  only in that process's memory, and never persisted or exported, so no other
  process can produce a value that resolves. A caller presenting it resolves to
  the daemon's system principal with no human identity attached, and is subject
  to the same command clearance and dispatch privilege as any other system-role
  caller.

Identity is established once, at the boundary a human crosses to reach the platform,
and carried by everything inside it. A person running a `telec` command from a shell,
or launching the TUI, has no session to identify them, so the terminal-email signal
answers who they are; the TUI then holds that resolved identity for as long as it
runs. Everything already inside carries identity instead of resolving it: an agent
session presents its session token, work dispatched for a todo takes its human root
from that todo's creation record, and a standing role resolves to its own system
principal.

A process that is not a human arriving from outside therefore presents no
terminal-email signal — the daemon and every process it spawns included. Resolving
identity from ambient state deep inside the platform attributes work to whoever
last authenticated on the host rather than to whoever it belongs to, and in a
multi-person installation that is one identity standing in for all of them.


### 3) Agent session token auth

Token-based auth exists exclusively for daemon-spawned agent sessions — sessions
that have no human behind them and therefore cannot authenticate via terminal email
or the dual-factor session-id path.

**Human-initiated sessions never receive a token.** They authenticate via
`x-telec-email` (terminal login) or `x-caller-session-id` (dual-factor tmux
cross-check). The daemon does not issue a token for sessions with a `human:<email>`
principal.

**Who gets a token:**

| Principal type                | Token issued?                  | Auth path                                                   |
| ----------------------------- | ------------------------------ | ----------------------------------------------------------- |
| `human:<email>`               | **No**                         | `x-telec-email` or `x-caller-session-id` + tmux cross-check |
| `system:daemon`               | **Yes**                        | `x-session-token` header                                    |
| Inherited `session.principal` | **Yes** (if system-originated) | Inherits parent's auth path                                 |

**Token lifecycle:**

Each token is bound to exactly one `session_id`. It cannot be used to
authenticate as a different session. Tokens have no time-based expiry. A token
lives exactly as long as its session. The only event that invalidates a token
is session close, which calls `db.revoke_session_tokens(session_id)`. There is
no TTL, no timeout, no background sweep. Session close is the single lifecycle
boundary.

**Flow (system-principal sessions only):**

1. Daemon calls `resolve_session_principal(session)` at bootstrap to derive a principal:
   - `human:<email>` when `session.human_email` is set → **no token issued**.
   - `system:daemon` for every session with no human origin — the platform's own principal,
     shared by those sessions and told apart by session id → **token issued**.
   - Inherited `session.principal` is reused directly for child sessions so the full
     agent chain shares one stable identity.
2. For system principals only: daemon issues a token via
   `db.issue_session_token(session_id, principal, role)` → UUID.
3. Token is injected into the tmux environment as `TELEC_SESSION_TOKEN`.
4. CLI calls from within the session send `x-session-token: <token>` header.
5. `verify_caller()` validates the token first (before the session-id dual-factor path):
   - Calls `db.validate_session_token(token)` — checks `revoked_at` only.
   - Populates `CallerIdentity.principal` and `CallerIdentity.principal_role` from the record.
6. `is_command_allowed()` uses `principal_role` as the effective human role when `human_role`
   is absent — this lets daemon-spawned sessions pass role clearance without a human behind them.
7. On session close, `db.revoke_session_tokens(session_id)` is called and the token cache is
   invalidated so in-flight requests with the stale token are rejected immediately.

**Key headers:**

- `x-session-token`: daemon-issued credential for system sessions only
  (takes priority over `x-caller-session-id` when present).

**`telec auth whoami`:**
<!-- planned-change:cli-reads-resolve-in-process -->
Inside a session and at a terminal alike, `whoami` asks the daemon's `GET /auth/whoami`
endpoint and prints its answer. The answer is what caller verification resolved: the
principal (`human:<email>` for a person, whether a session carries it or a terminal
login names them), the role, the person's email, and the session id when the caller is
a session. A process whose session identity document is unusable is told so and asks
nothing. The CLI resolves no identity itself.
<!-- change:cli-reads-resolve-in-process -->
Inside a session and at a terminal alike, `whoami` resolves its caller in the CLI process
through the shared caller resolution in §6 and prints the answer; it sends no request to
the daemon. The answer is the principal (`human:<email>` for a person, whether a session
carries it or a terminal login names them) and the role that authorizes the caller, plus
the person's email and terminal at a terminal. A process whose session identity document
identifies no open session on this computer is told so and is given no terminal identity.
The daemon's `GET /auth/whoami` endpoint answers the same question for clients of its API.
<!-- /planned-change:cli-reads-resolve-in-process -->

**Principal types:**

| Format          | When set                                                                     | Credential                                                    |
| --------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `human:<email>` | Session created with a human identity (human_email set)                      | None                                                          |
| `system:daemon` | The daemon process itself, and every session with no human origin            | Process-local daemon credential; a session token per session |

**Token ledger table:** `session_tokens` — stores token, session_id, principal, role,
issued_at, revoked_at. Token lifetime is controlled exclusively by revocation on
session close.

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

- If `people` contains more than one registered person:
  - a terminal that carries no login document of its own presents no terminal-email
    signal, so a person opening a fresh terminal authenticates on it before any
    identity-bearing command succeeds,
  - TUI launch requires prior `telec auth login`,
  - daemon rejects tmux callers that have no `x-caller-session-id` and no resolvable `x-telec-email`.
- If `people` has zero/one person, the legacy fallback role is still allowed for
  tmux callers without session identity, and with exactly one person that person
  answers a terminal that has no document of its own.
- Whichever mode is in force, a login already bound to a live terminal keeps
  answering for that terminal. One person authenticating never unbinds another
  person's open terminals; only the terminal's own disappearance does.

### 6) Authorization

Role clearance resolves the caller from the identity it carries, never from a
claim the caller supplies:

- a caller inside a session resolves from its session record, reached through the
  session id its identity document names; a principal copied into that document
  is never trusted for clearance,
- a caller outside any session resolves from its terminal login,
- the daemon's protected routes (`verify_caller` + `require_clearance`) and the
  CLI's local gates resolve a session's principal through the same
  principal-resolution capability; a local gate grants a session no role its
  principal does not resolve to,
- on a protected route, unknown/missing identity returns 401 and insufficient
  role returns 403; a local gate treats an unidentified caller as holding no role.

### 7) Session lineage invariant (child sessions)

Child worker sessions should be linked to parent orchestrator session identity when a caller session exists.

- `/sessions/run` accepts terminal/TUI callers whose identity is resolved by `verify_caller` even when `x-caller-session-id` is empty.
- When a caller session identity is present, `initiator_session_id` is written for child-session linkage.
- Requests without caller session identity remain valid, but they create unlinked sessions because terminal/TUI callers do not have a parent TeleClaude session.
- A lifecycle session the runner auto-dispatches for a todo whose `created_by_principal` is a `human:<email>` establishes that human as its root identity: the session row carries the owning human's `principal`/`human_email`, so its resolved principal is `human:<email>` rather than `system:daemon`, and the rest of the chain inherits it through `initiator_session_id`. The session's `system_role` is left untouched, so the attribution does not change what the session is authorized to do.


### 8) Person-bound service identity

Person-bound service access is authorized from the same verified caller identity used by protected API routes:

- A managed human-rooted session resolves from its daemon-owned session record and inherited `human:<email>` principal.
- A terminal or trusted TUI caller resolves from authenticated terminal email and the global person registry.
- A system-only principal has no implicit person, even when it has command clearance, and is denied person-bound service access.
- The resolved email must map to exactly one configured person with a canonical slug before credential lookup begins.
- The session identity marker in `$TMPDIR` is a client-side transport input, not authority for person selection. Person-bound handlers never read it directly and never accept a person from tool arguments.

The protected edge translates `CallerIdentity` into a typed service invocation context. Downstream runtime and credential components receive the resolved person slug or an explicit absence; they do not inspect headers, session files, or identity storage themselves. Failure to resolve a person is a request denial, not a fallback to the sole configured user or to global credentials.

## Known caveats

- Headless/native hook identity follows `session-identity-truth`; it is distinct from terminal login.
- TUI login bridge is read-only runtime context, not a replacement for `telec auth login`.
