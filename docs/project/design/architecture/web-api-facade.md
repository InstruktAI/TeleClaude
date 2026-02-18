---
description: 'Next.js API facade as the canonical web contract, proxying to daemon APIs during migration.'
id: 'project/design/architecture/web-api-facade'
scope: 'project'
type: 'design'
---

# Web Api Facade — Design

## Required reads

- @docs/project/design/architecture/api-server.md
- @docs/project/design/architecture/cache-system.md
- @docs/project/policy/adapter-boundaries.md

## Purpose

Define the web boundary where Next.js route handlers are the only public API for browser clients.

- Browser calls Next.js API only.
- Next.js routes proxy to daemon endpoints in phase 1.
- Daemon remains source of truth for sessions, cache snapshots, and command execution.
- Migration proceeds route-by-route from proxy to native Next.js logic without changing browser contract.

## Public Contract

The stable public surface is the Next.js API namespace (`/api/*` in frontend app), not daemon URLs.

| Public Route                           | Mode    | Auth Guard             | Upstream                           |
| -------------------------------------- | ------- | ---------------------- | ---------------------------------- |
| `POST /api/chat`                       | `proxy` | auth                   | daemon stream endpoint             |
| `GET /api/people`                      | `proxy` | auth                   | daemon people endpoint             |
| `GET /api/computers`                   | `proxy` | auth                   | daemon computers endpoint          |
| `GET /api/sessions`                    | `proxy` | auth                   | daemon sessions endpoint           |
| `POST /api/sessions`                   | `proxy` | auth                   | daemon create session endpoint     |
| `DELETE /api/sessions/:id`             | `proxy` | auth + ownership       | daemon delete session endpoint     |
| `POST /api/sessions/:id/revive`        | `proxy` | auth + ownership       | daemon revive session endpoint     |
| `POST /api/sessions/:id/agent-restart` | `proxy` | auth + admin           | daemon agent-restart endpoint      |
| `POST /api/sessions/:id/messages`      | `proxy` | auth                   | daemon message ingest endpoint     |
| `GET /api/sessions/:id/messages`       | `proxy` | auth                   | daemon messages list endpoint      |
| `GET /api/projects`                    | `proxy` | auth                   | daemon projects endpoint           |
| `GET /api/todos`                       | `proxy` | auth                   | daemon todos endpoint              |
| `GET /api/agents/availability`         | `proxy` | auth                   | daemon agent availability endpoint |
| `GET /api/settings`                    | `proxy` | auth                   | daemon settings endpoint           |
| `PATCH /api/settings`                  | `proxy` | auth + admin           | daemon settings endpoint           |
| `WebSocket /api/ws`                    | `proxy` | auth (cookie validate) | daemon WebSocket bridge            |

## Data/Transport Strategy

### Chat stream

- Request path: browser -> Next.js `POST /api/chat` -> daemon stream endpoint.
- Next.js forwards request body and streams response through (no full buffering).
- This keeps assistant-ui integration stable while backend internals evolve.

### State snapshots

- Source of truth remains daemon cache snapshots.
- Web clients consume state via websocket path backed by daemon cache updates.
- Preferred integration: Next.js websocket/SSE gateway that relays daemon `/ws` updates, so browser never needs daemon host knowledge.

## Identity Boundary

Only Next.js server code may inject trusted identity metadata.

1. Resolve authenticated web user to normalized identity.
2. Attach trusted identity headers/metadata on upstream daemon calls.
3. Daemon validates and enforces role/visibility.

Browser-provided identity headers are never trusted.

## Migration Model

Per route, use explicit status:

- `proxy`: Next.js forwards to daemon.
- `hybrid`: partial logic moved to Next.js, remainder proxied.
- `native`: fully implemented in Next.js without daemon endpoint dependency.

The route map file in todo artifacts is the migration tracker for current implementation status.

## Invariants

- Web clients never call daemon API directly.
- Daemon remains authoritative for session and command state until explicit migration.
- Cache websocket remains the state distribution mechanism.
- Route contract stability is maintained while internals are replaced.

## Failure modes

- **Upstream daemon unavailable**: Next.js route returns normalized 5xx with request id.
- **Streaming breakage**: route fails fast, preserves upstream status semantics.
- **Identity mismatch**: daemon rejects with authorization error; Next.js does not bypass.
- **Contract drift**: prevented by route-map status tracking (`proxy/hybrid/native`) per endpoint.
