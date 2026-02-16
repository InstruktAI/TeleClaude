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

- [x] `frontend/` Next.js 15 app (App Router, standalone output).
- [x] Tailwind CSS + shadcn/ui configured.
- [x] assistant-ui packages installed.
- [x] Base layout with root provider.

**Notes**

- Use assistant-ui integration patterns from local repo examples.
- pnpm as package manager.

### Task 2: Add runtime provider + chat page

- [ ] Runtime provider component using assistant-ui transport runtime.
- [ ] Chat page rendering thread UI at `/(chat)`.
- [ ] Wired to `/api/chat` route.

**Notes**

- Use `useAssistantTransportRuntime` or `useChatRuntime` pattern.
- Keep component boundaries clean so thread/session UI can evolve in phase 3/4.

### Task 3: Implement Next.js API facade routes

- [ ] `frontend/lib/proxy/daemon-client.ts` — daemon HTTP client (Unix socket).
- [ ] `POST /api/chat` — proxy to daemon session message + stream relay.
- [ ] `GET /api/people` — resolve people from config (native mode).
- [ ] `GET /api/sessions` + `POST /api/sessions` — proxy to daemon.
- [ ] `POST /api/sessions/[id]/messages` — proxy to daemon message send.

**Implementation contract**

- Build upstream URL from server-side daemon base config.
- Forward body/headers selectively (allowlist).
- Stream response passthrough for chat routes.
- Preserve status code and content type.

### Task 4: Identity normalization at web boundary

- [ ] NextAuth v5 configuration with email OTP provider.
- [ ] Drizzle ORM + SQLite for auth session storage.
- [ ] signIn callback rejects emails not in people config.
- [ ] Session callback enriches with role from people config.
- [ ] Login page with people selector and OTP flow.
- [ ] Auth middleware protecting routes.
- [ ] Trusted identity headers on daemon proxy requests.

**Rules**

- Never trust raw browser-provided identity headers.
- Only server-side middleware may attach trusted identity metadata.

### Task 5: Route map + migration status tracking

- [ ] `todos/web-interface-2/route-map.md` updated with actual implementation status.

### Task 6: Verification and guardrails

- [ ] Proxy logging with request ID, latency, upstream status.
- [ ] Secret/token redaction in logs.
- [ ] Error normalization for upstream failures.

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
