# Implementation Plan: Web Interface

## Objective

Build a Next.js 15 web application with AI SDK v5 streaming from TeleClaude daemon, email OTP auth, and session management.

## Phase 1: Daemon-side plumbing

### Task 1.1: TCP port binding

**File:** `teleclaude/api_server.py`

Add `localhost:8420` TCP binding alongside existing Unix socket. Both serve the same FastAPI app.

**Verification:** `curl http://localhost:8420/health` returns OK.

### Task 1.2: SSE streaming endpoint

**File:** `teleclaude/api/streaming.py` (new)

`POST /api/chat/stream`:

- Accept `sessionId` and optional `since_timestamp` in request body.
- Return `StreamingResponse` with `media_type="text/event-stream"` and `x-vercel-ai-ui-message-stream: v1` header.
- Two modes: history replay then live streaming.

**Verification:** `curl -X POST` receives SSE events.

### Task 1.3: Transcript-to-SSE converter

**File:** `teleclaude/api/transcript_converter.py` (new)

Convert JSONL transcript entries to AI SDK SSE events:

- `thinking` → `reasoning-start/delta/end`
- `tool_use` → `tool-input-start/available`
- `tool_result` → `tool-output-available`
- `text` → `text-start/delta/end`
- Custom parts for send_result, session status, files.

**Verification:** Unit tests with sample JSONL → expected SSE output.

### Task 1.4: People list endpoint

**File:** `teleclaude/api_server.py`

`GET /api/people` — returns people list from global config (name, email, role). No credentials exposed.

**Verification:** Endpoint returns correct people list.

### Task 1.5: Message ingestion endpoint

Part of `POST /api/chat/stream` — when request includes new user message:

1. Extract text from messages array.
2. Send to session via `send_keys`.
3. Begin streaming response.

**Verification:** Message sent, response streamed.

## Phase 2: Next.js application scaffold

### Task 2.1: Project setup

- Next.js 15 with App Router, standalone output.
- shadcn/ui, Tailwind, react-markdown + remark-gfm.
- Drizzle ORM with SQLite.
- Environment config for daemon URL, auth secret.

### Task 2.2: NextAuth v5 integration

- Email provider with Brevo SMTP transport.
- 6-digit OTP (3-minute expiry).
- `signIn` callback: verify email exists in people config (call daemon `/api/people`).
- `session` callback: enrich with role from config.
- DrizzleAdapter with SQLite.

### Task 2.3: Login page

- People dropdown (fetched from daemon `/api/people`).
- Select name → resolve email → trigger OTP.
- OTP input → verify → session created.

**Verification:** Full login flow works.

## Phase 3: Chat interface

### Task 3.1: useChat integration

```typescript
const { messages, sendMessage } = useChat({
  transport: new DefaultChatTransport({
    api: '/api/chat/stream',
    headers: { Authorization: `Bearer ${sessionToken}` },
    prepareSendMessagesRequest: ({ messages }) => ({
      body: { sessionId: currentSessionId, messages },
    }),
  }),
});
```

Next.js API route proxies to daemon with auth headers.

### Task 3.2: UIMessage part components

- `<ThinkingBlock>` — collapsible reasoning (collapsed by default).
- `<ToolCallBlock>` — tool name, collapsible args/result.
- `<Markdown>` — react-markdown + remark-gfm.
- `<ArtifactCard>` — send_result content.
- `<StatusBadge>` — session status indicator.
- `<FileLink>` — clickable link to daemon file endpoint.

### Task 3.3: Session management sidebar

- Active sessions list with title, agent icon, status.
- Click to switch sessions (reconnects SSE stream).
- "New Session" button with project/agent picker.

## Phase 4: Role-based access

### Task 4.1: Visibility routing

- SSE endpoint checks: does connected person have access to requested session?
- Creator → yes. Admin → yes. Shared + member → yes. Otherwise → 403.

### Task 4.2: Dashboard (admin)

- Computers with status.
- Projects with active session counts.
- Security events from logbook (when available).

## Files Expected to Change

**Daemon:**
| File | Change |
|------|--------|
| `teleclaude/api_server.py` | TCP binding, people endpoint |
| `teleclaude/api/streaming.py` | New — SSE endpoint |
| `teleclaude/api/transcript_converter.py` | New — JSONL → SSE |

**Frontend (new Next.js project):**

- `app/` — App Router pages and layouts
- `components/` — UIMessage part components
- `lib/` — auth, API client, types
- `drizzle/` — schema and migrations

## Risks

1. **Large scope** — phased delivery essential. Phase 1 (daemon) and Phase 2 (scaffold + auth) can be verified independently.
2. **AI SDK wire protocol** — must match v5 spec exactly for `useChat` to parse correctly.
3. **Session proxy** — Next.js API route to daemon proxy adds latency. Keep it thin.
4. **Auth strict rollout** — daemon auth middleware must be in place first (person-identity-auth prerequisite).

## Verification

- Daemon SSE endpoint produces valid AI SDK UIMessage Stream.
- useChat successfully parses and renders stream.
- Full login → session → chat → streaming flow works end-to-end.
