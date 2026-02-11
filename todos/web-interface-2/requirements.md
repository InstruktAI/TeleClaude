# Requirements: Web Interface — Phase 2 (Next.js Scaffold + Proxy Facade)

## Goal

Stand up the Next.js web app using assistant-ui, with Next.js API routes as the canonical public API. In this phase, those routes are proxy stubs to existing TeleClaude daemon endpoints.

## Architecture Contract

- Canonical design: `docs/project/design/architecture/web-api-facade.md`

## Problem

We need to adopt assistant-ui/Next.js without a risky big-bang backend rewrite. The migration must preserve behavior while moving the public contract from daemon API routes to Next.js route handlers.

## Scope

### In scope

1. Scaffold a frontend workspace using assistant-ui patterns (existing project integration, not throwaway demo).
2. Add assistant-ui runtime wiring in Next.js (`useChatRuntime` + runtime provider + thread UI shell).
3. Implement Next.js API facade routes for chat/session/people, initially forwarding to daemon API.
4. Implement web auth boundary in Next.js and forward normalized identity headers to daemon.
5. Define strict route mapping table: `Next.js route -> daemon endpoint`.
6. Add observability for proxy calls (request id, latency, upstream status, sanitized errors).

### Out of scope

- Removing daemon endpoints in this phase.
- Rebuilding daemon streaming internals.
- Full production role dashboard UX.

## Functional Requirements

### FR1: assistant-ui scaffold is integrated in repo

- Frontend lives under a stable path (for example `frontend/`).
- Uses assistant-ui package stack and runtime provider pattern.
- Uses Next.js App Router and a minimal thread/chat page.

### FR2: Next.js API becomes public entrypoint

- Frontend calls only Next.js API routes (never daemon routes directly from browser).
- Initial proxy routes include:
  - `POST /api/chat`
  - `GET /api/people`
  - `POST /api/sessions`
  - `GET /api/sessions`
  - `POST /api/sessions/:id/messages` (or equivalent chat submit path)

### FR3: Proxy-forward behavior

- Each Next.js route forwards request payload to mapped daemon endpoint.
- Streaming responses are relayed without buffering full output.
- Upstream non-2xx statuses are preserved with normalized error payload.

### FR4: Identity boundary

- Next.js validates user session and resolves identity to normalized values.
- Forwarded headers to daemon include trusted person metadata fields.
- Daemon remains authorization source of truth; Next.js is trusted boundary for web identity injection.

### FR5: Route map and migration hooks

- Maintain explicit mapping doc/table in phase artifacts.
- For each route, mark migration status:
  - `proxy` (forward only)
  - `hybrid` (partial logic moved)
  - `native` (fully implemented in Next.js)

## Non-functional Requirements

1. No browser exposure of daemon base URL.
2. Proxy latency overhead should remain small and measurable.
3. Proxy logs must not leak secrets/tokens.
4. Behavior must remain compatible with existing daemon APIs.

## Acceptance Criteria

1. assistant-ui chat UI loads and can send/receive messages through Next.js API routes.
2. Browser network calls only hit Next.js API routes.
3. Chat streaming works through proxy route.
4. People list and session list resolve via proxy routes.
5. Identity metadata is forwarded and visible in daemon-side request handling.
6. Route mapping table exists and marks all implemented routes as `proxy`.

## Dependencies

- `web-interface-1` completed (daemon SSE plumbing).
- `person-identity-auth` available for trusted identity normalization.

## References

- `~/Workspace/public-repos/github.com/assistant-ui/assistant-ui/README.md`
- `~/Workspace/public-repos/github.com/assistant-ui/assistant-ui/examples/with-ai-sdk-v6`
- `~/Workspace/public-repos/github.com/assistant-ui/assistant-ui/examples/with-assistant-transport`
