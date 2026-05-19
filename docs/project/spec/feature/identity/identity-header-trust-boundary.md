---
id: project/spec/feature/identity/identity-header-trust-boundary
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Reject web-user identity headers at the daemon's HTTP boundary unless the request originates from a trusted loopback host.
---

# Identity Header Trust Boundary — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The transport-level firewall that protects the daemon's HTTP API from forged web identities. The daemon's Next.js frontend authenticates a browser session (NextAuth), then forwards the resolved user to the API as a trio of headers — `x-web-user-email`, `x-web-user-name`, `x-web-user-role`. Those headers are the v1 substitute for a signed web token: downstream code (`verify_caller`, `check_session_access`, the session-visibility filter, the WebSocket listener) trusts them without any further cryptographic check. That trust only holds if the headers cannot be supplied by an outside caller. A FastAPI middleware enforces that constraint at the edge: if any of the three identity headers appears on a request whose client host is not a loopback address, the request is refused with HTTP 403 before any route handler runs. The middleware is what makes the rest of the v1 identity model safe; without it, the headers would be a self-service role escalation.

## Canonical fields

### Use cases

```
Given a request from a non-trusted client host (e.g. 192.0.2.10)
And the request carries header x-web-user-email: maurice@instrukt.ai
When the daemon's `_validate_identity_headers` middleware processes the request
Then the middleware responds 403 with body {"detail": "Identity headers rejected: untrusted source"}
And a warning is logged naming the rejected client host
And no route handler runs
```

```
Given a request from 127.0.0.1
And the request carries header x-web-user-email: maurice@instrukt.ai, x-web-user-role: member
When `_validate_identity_headers` processes the request
Then the middleware passes the request to the next middleware unchanged
And `verify_caller` consumes the headers via the terminal-identity path
And the caller is treated as the named web user
```

```
Given a request over the daemon's Unix socket (request.client is None)
And the request carries the x-web-user-email header
When `_validate_identity_headers` processes the request
Then the empty / None client host is treated as trusted
And the request proceeds
```

```
Given a CLI tool call (no x-web-user-* headers present) from any client host
When `_validate_identity_headers` processes the request
Then the trust boundary does not engage
And the request proceeds to be authenticated by `verify_caller` via session-token or terminal-email paths
```

```
Given a WebSocket upgrade from 127.0.0.1 carrying x-web-user-email / x-web-user-role
When the FastAPI app receives the upgrade
Then the middleware applies on the HTTP upgrade exchange
And the WebSocket session-list listener (`ws_mixin._send_initial_data`) reads the same headers to apply role-based visibility filtering
```

```
Given a request from a non-trusted host carrying only x-web-user-name (with no email and no role)
When `_validate_identity_headers` processes the request
Then the middleware still rejects with 403
Because ANY of the three identity headers triggers the trust check
```

### Implementation pointers (v1)

- Middleware: `teleclaude/api_server.py:432-448` (`_validate_identity_headers`)
- Identity-header set: `teleclaude/api_server.py:417` (`{"x-web-user-email", "x-web-user-name", "x-web-user-role"}`)
- Trusted-host set: `teleclaude/api_server.py:418` (`{"127.0.0.1", "::1", "localhost"}`)
- Header consumer (caller resolution): `teleclaude/api/auth.py:198-222,259-291` — `_build_terminal_identity` accepts `x_telec_email or x_web_user_email` as the terminal-identity path
- Header consumer (session access): `teleclaude/api/session_access.py:32-33` reads `x-web-user-email` and `x-web-user-role`
- Header consumer (session list filter): `teleclaude/api/sessions_routes.py:89-109` (`_filter_sessions_by_role`)
- Header consumer (WebSocket): `teleclaude/api/ws_mixin.py:253-265` reads the same headers from `websocket.headers`

### Cross-context references

- The headers themselves are produced by the local-only Next.js frontend's NextAuth flow described in `identity-and-auth.md` §4 (web identity). The frontend is owned by the `integration` context; the middleware is owned by `identity` and lives on the `agent_runtime` HTTP server.
- Once admitted, the headers feed the terminal-identity path of `feature/identity/caller-verification` (web user) and gate `feature/identity/session-access-visibility` (which sessions that user may touch) and the session-list role filter consumed by the WebSocket session feed.
- The `x-web-user-email` header is an alternative to the CLI's `x-telec-email` header — both produce the same `human_email` on the resolved `CallerIdentity`. The trust boundary is what makes them safe to treat equivalently: only `x-telec-email` is set by trusted local CLI processes, and `x-web-user-email` is gated by this middleware.

## Known caveats

- The trust boundary is HOST-based, not user-based. Any process running on the daemon host that can reach the loopback API can forge any web user identity. The v1 deployment assumption is that the daemon host is single-tenant operator hardware; this assumption is documented in `identity-and-auth.md` and tightened by v2.
- A `client_host` of `None` or empty string is treated as trusted to support Unix-socket transport, where FastAPI does not populate `request.client`. This is correct for the intended Unix-socket case but means any future transport that leaves `request.client` unset will also be treated as trusted — a coupling worth re-checking before adding new transports.
- The middleware fires on the presence of ANY of the three headers, not just `x-web-user-email`. A request that supplies only `x-web-user-name` from an untrusted host is still rejected. This is intentional fail-closed behavior — the trio is treated as a single identity assertion.
- v2 hardens this by introducing a config-driven trust gate (per the v2 identity domain spec's Known caveats) so the trusted-host set is not hard-coded.
- The middleware does not run on WebSocket frames after the upgrade, only on the HTTP upgrade exchange itself. WebSocket consumers that read `x-web-user-email` from `websocket.headers` rely on the upgrade-time check; a WebSocket upgrade from an untrusted host carrying identity headers is rejected at the upgrade, so post-upgrade reads are only ever of headers that passed the boundary.
