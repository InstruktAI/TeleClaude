# Implementation Plan: Web Interface — Phase 2 (Proxy-First assistant-ui Adoption)

## Objective

Adopt assistant-ui as the web UI while making Next.js API routes the public contract, backed by proxy forwarding to existing daemon endpoints.

## Architecture Contract

- Canonical design: `docs/project/design/architecture/web-api-facade.md`

## Design Principle

"Facade first, migration second":

1. Frontend -> Next.js API only.
2. Next.js API -> daemon API proxy in phase 2.
3. Incrementally replace proxy routes with native Next.js implementations later.

## Tasks

### Task 1: Create frontend scaffold with assistant-ui

**Deliverables**
- `frontend/` Next.js app (App Router).
- assistant-ui runtime wiring and base thread page.

**Notes**
- Use assistant-ui integration patterns from local repo examples.
- Prefer `init` into existing structure if feasible; otherwise scaffold and adapt.

### Task 2: Add runtime provider + chat page

**Deliverables**
- Runtime provider component using assistant-ui runtime hook.
- Chat page rendering thread UI.

**Notes**
- Initial runtime can target `/api/chat` route in frontend app.
- Keep component boundaries clean so thread/session UI can evolve in phase 3/4.

### Task 3: Implement Next.js API facade routes

**Deliverables**
- Route handlers under `frontend/app/api/**` for:
  - chat submit/stream
  - people list
  - session create/list
  - message send

**Implementation contract**
- Build upstream URL from server-side daemon base config.
- Forward body/headers selectively (allowlist).
- Stream response passthrough for chat routes.
- Preserve status code and content type.

### Task 4: Identity normalization at web boundary

**Deliverables**
- Session/auth middleware in Next.js.
- Identity resolver for current user.
- Trusted identity headers attached to forwarded daemon requests.

**Rules**
- Never trust raw browser-provided identity headers.
- Only server-side middleware may attach trusted identity metadata.

### Task 5: Route map + migration status tracking

**Deliverables**
- `todos/web-interface-2/route-map.md` (new).
- Table columns: `public route`, `daemon target`, `mode(proxy/hybrid/native)`, `owner`, `notes`.

### Task 6: Verification and guardrails

**Deliverables**
- Minimal integration checks for proxy route behavior.
- Logging around proxy forwarding with redaction.

**Checks**
- Browser calls only Next.js routes.
- Upstream failure surfaces clear error to UI.
- Streaming path remains functional.

## Proposed File Targets

### New frontend files

- `frontend/app/(chat)/page.tsx`
- `frontend/components/assistant/MyRuntimeProvider.tsx`
- `frontend/components/assistant/ThreadView.tsx`
- `frontend/app/api/chat/route.ts`
- `frontend/app/api/people/route.ts`
- `frontend/app/api/sessions/route.ts`
- `frontend/app/api/sessions/[id]/messages/route.ts`
- `frontend/lib/proxy/daemon-client.ts`
- `frontend/lib/identity/resolve-web-identity.ts`

### Todo artifacts

- `todos/web-interface-2/route-map.md`
- `todos/web-interface-2/verification.md`

## Risks

1. Streaming protocol mismatch between assistant-ui transport and daemon stream payload.
- Mitigation: start with strict passthrough; add adapter only when required.

2. Identity drift between Next.js session and daemon identity expectations.
- Mitigation: centralize header injection in one server-side utility.

3. Contract drift during migration.
- Mitigation: route map file as single source of truth per endpoint.

## Exit Criteria for Phase 2

1. assistant-ui page operational in `frontend/`.
2. Next.js API facade routes operational for chat/session/people.
3. Proxy mode documented per route in `route-map.md`.
4. Frontend traffic does not call daemon API directly.
5. Ready handoff to phase 3 (chat UX and part rendering).
