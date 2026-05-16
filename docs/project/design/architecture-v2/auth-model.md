---
description: 'v2 auth model: identity crate as resolution authority, principal types, per-service authorization, browser cross-language boundary.'
id: 'project/design/architecture-v2/auth-model'
scope: 'project'
type: 'design'
---

# Auth Model — Design

## Required reads

- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md

## Purpose

Fix how authentication and authorization work in v2 across every binary (CLI,
TUI, daemon, API server, workers, hook receivers). Identity is one crate; every
binary embeds it; authorization happens at the service layer with a resolved
principal.

## Inputs/Outputs

**Inputs:**

- the v1 auth surface (TTY login files, session tokens, three header paths)
- the v2 services-as-crates model
- the browser ↔ frontend ↔ daemon HTTP path (only legitimate cross-language
  auth boundary)

**Outputs:**

- the identity crate's responsibilities
- the principal type model
- the resolution flow per transport
- the authorization flow per service
- the explicit cross-language boundary for browser auth

## Invariants

- **Identity is a crate, not a service process.** Every binary that needs to
  resolve "who is calling" embeds `crates/identity/` and calls into it
  directly.
- **Resolution is centralized; authorization is decentralized.** Identity
  knows how to derive a `Principal` from every source TeleClaude supports.
  Each service decides what its `Principal`-typed callers can do.
- **One `Principal` enum.** Every transport resolves to the same Rust type.
  Services pattern-match on it; they never see raw transport evidence.
- **HTTP auth crosses one boundary only.** Browser ↔ frontend ↔ daemon API.
  All other auth is in-process via the crate.
- **Tokens have one lifecycle boundary.** Session tokens are issued at session
  start, validated by token id, revoked at session close. No time-based
  expiry, no background sweeper.

## Primary flows

### The identity crate's responsibilities

`crates/identity/` exposes:

- `resolve_from_env() -> Principal` — for CLI/TUI/daemon at startup
- `resolve_from_http(&HttpRequest) -> Result<Principal>` — for the HTTP API
  middleware
- `resolve_from_session_token(&Token) -> Result<Principal>` — for agent
  sessions that authenticate via injected token
- `issue_session_token(session_id, principal, role) -> Token` — daemon issues
  at agent session start
- `revoke_session_tokens(session_id)` — daemon calls at session close
- `validate_session_token(&Token) -> Result<Principal>` — every API request
  validates if a token is present

Internal modules (`_resolution.rs`, `_tokens.rs`, `_principals.rs`,
`_storage.rs`) hold the implementation. Other crates never reach inside.

### The Principal type

Rough sketch — final shape lives in `crates/identity/src/models.rs`:

```rust
pub enum Principal {
    Human {
        email: String,
        role: Role,
    },
    AgentSession {
        session_id: SessionId,
        role: Role,
    },
    System {
        service: ServiceName,
    },
    Anonymous,
}
```

Every resolution source converges on this enum. Every service pattern-matches
on it for authorization decisions.

### Per-binary resolution flow

**CLI (`telec`)** — resolves on startup:

```rust
fn main() {
    let principal = identity::resolve_from_env();
    let ctx = Context { principal };
    // dispatch to subcommand handlers, passing ctx
    workflow::list_todos(&ctx, project_id).await?;
}
```

The CLI reads TTY login files or per-shell env vars (`TELEC_SESSION_TOKEN` for
agent sessions). All translation happens inside `resolve_from_env`.

**TUI (`telec-tui`)** — same pattern as CLI. Resolves once at startup, passes
context into every service call.

**Daemon (`telec-daemon`)** — resolves per request when hosting the HTTP API:

```rust
async fn handle_request(req: HttpRequest) -> Response {
    let principal = identity::resolve_from_http(&req)?;
    let ctx = Context { principal };
    // call service, return response
    let todos = workflow::list_todos(&ctx, project_id).await?;
    serialize(todos)
}
```

For internal daemon work that has no human caller (cron-like worker
supervision), the daemon uses `Principal::System { service: "agent_runtime" }`
or similar.

**Worker binaries** — resolve themselves as `Principal::System { service: ... }`
on startup. No human in the loop. Each worker has its own service identity.

**Hook receivers (`telec-hook` or similar)** — receive a typed payload from
Claude Code, including session context. Resolve the originating session via
the session token if present, otherwise `Principal::AgentSession` from the
session metadata in the payload. Emit Redis event with the principal attached.

### Service authorization

Each service decides what a principal can do. Example pattern in workflow:

```rust
pub async fn list_todos(ctx: &Context, project_id: ProjectId) -> Result<Vec<Todo>> {
    authorize_project_read(&ctx.principal, project_id)?;
    // ... query Postgres ...
}

fn authorize_project_read(principal: &Principal, project_id: ProjectId) -> Result<()> {
    match principal {
        Principal::Human { role, .. } if role.can_read_project(project_id) => Ok(()),
        Principal::AgentSession { session_id, .. } if session_owns_project(session_id, project_id) => Ok(()),
        Principal::System { .. } => Ok(()),  // system principals have full access
        _ => Err(Error::Forbidden),
    }
}
```

The pattern: identity tells the service WHO. The service decides WHETHER.
Identity has no opinion on workflow-specific authorization; workflow has no
opinion on how the principal was resolved.

### Browser auth — the one HTTP boundary

Browser auth is the only place auth crosses a language boundary (Rust ↔
JavaScript). This is the legitimate HTTP path:

```
[browser]
  ↓ (NextAuth email OTP flow, session cookie issued)
[frontend custom server (Next.js)]
  ↓ (validates session cookie locally; constructs identity header)
[daemon HTTP API (Rust)]
  ↓ (identity::resolve_from_http())
[service crate call]
```

1. Browser logs in via NextAuth (frontend handles, session cookie issued).
2. Browser hits `/api/...` on the frontend.
3. Frontend's custom server validates the NextAuth cookie locally (Node
   code, no daemon roundtrip).
4. Frontend forwards request to daemon's HTTP API with an auth header
   carrying resolved identity (signed JWT, or `x-telec-email` if the trust
   boundary between frontend and daemon is sufficient).
5. Daemon's HTTP middleware uses `identity::resolve_from_http()` to translate
   the header into a `Principal`.
6. Service call proceeds with the resolved principal.

The frontend is a trusted intermediary because it lives on the same machine
and is operated by the same person. Trust boundary between frontend and
daemon is local-only.

### Agent session token lifecycle

Daemon-spawned agent sessions (workers that have no human behind them)
authenticate via session token. The lifecycle:

1. Daemon spawns agent session.
2. Daemon calls `identity::issue_session_token(session_id, principal, role)`.
3. Token is injected into the tmux environment as `TELEC_SESSION_TOKEN`.
4. CLI invocations inside the session pick up the env var, present it as the
   auth source.
5. `identity::resolve_from_env()` recognizes the token and resolves to
   `Principal::AgentSession`.
6. On session close, daemon calls `identity::revoke_session_tokens(session_id)`.
7. Subsequent token use returns `Err(Revoked)`.

Tokens have no time-based expiry. Revocation is the lifecycle boundary.
Session close revokes; nothing else does.

### Postgres schema

Identity owns `identity` schema:

- `principals` — people, system service identities
- `session_tokens` — issued tokens, revoked_at marker
- `roles` — role definitions (or hardcoded in the Rust enum, depending on
  how much flexibility the project warrants)

Other services never query this schema. They call identity functions.

### Single-user MVP

For Week 1 MVP (single human, single machine), identity starts as a thin
stub:

```rust
pub fn resolve_from_env() -> Principal {
    Principal::Human {
        email: "maurice@instrukt.ai".into(),
        role: Role::Owner,
    }
}
```

That's the minimum identity needs to be for the workflow MVP. Real
multi-source resolution (TTY login, session tokens, header validation) lifts
in when other services come online and need to distinguish principal types.
The crate structure is right from day one; the implementation grows
incrementally.

## Failure modes

- **"Auth service running on a port."** Reintroduces the auth-as-process
  anti-pattern. Auth is a crate. If you propose a separate auth process,
  you're proposing the wrong thing.
- **Per-transport principal resolution scattered.** CLI deriving identity its
  way, daemon deriving its way, hooks deriving theirs. The whole point of
  the identity crate is to centralize this. Every transport's evidence is an
  input to `resolve_from_*` functions in identity.
- **Services interpreting raw transport evidence.** Workflow inspecting
  `x-telec-email` header directly, or reading the session token. Services
  see only `Principal`; they never see headers or tokens.
- **Authorization in middleware.** Putting "can this principal read project
  X?" in HTTP middleware instead of in the workflow service. Authorization
  is domain-specific; it lives with the service that owns the resource.
  Middleware authenticates (resolves principal); services authorize.
- **Time-based token expiry without explicit need.** v1's tokens have no
  TTL; revocation is the lifecycle. v2 should keep it that way unless a
  genuine need emerges. TTL adds background sweepers and complexity.
- **Trusting unauthenticated headers from the frontend bridge.** The
  frontend bridge is trusted only because it's local. If/when the bridge
  runs remotely, the header trust evaporates and we need signed JWTs or
  similar. Don't blur this — when the deployment topology changes, the trust
  boundary changes.

## See Also

- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md
  services.
- docs/project/spec/identity-and-auth.md
  reference.
