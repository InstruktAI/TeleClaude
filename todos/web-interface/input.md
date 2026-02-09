# Web Interface — Input

## Context

TeleClaude currently has three client interfaces: Telegram adapter, TUI (telec), and
MCP (AI-to-AI). The TUI is powerful but intimidating for non-power-users — reasoning
output, tool calls, and terminal aesthetics aren't approachable for everyone. Many
people expect a chat interface they can just type into.

The web interface also solves a harder problem: **authentication**. The planned
multi-person deployment (shared Mac Mini, one OS user, config-based identity) needs a
surface where login flows, email verification, and role-based views can live. A browser
on localhost is the natural home for this.

## Starting Point: ai-chatbot

The existing `ai-chatbot` project (`~/Workspace/morriz/ai-chatbot`) is a production
Next.js 15 app with most of what we need already built.

### What it has (and we keep)

- **NextAuth v5 email OTP auth** — Brevo/nodemailer transport, 6-digit OTP (not a
  clickable magic link — user enters the code manually), 3-minute expiry,
  DrizzleAdapter, database sessions stored in Postgres. The `verificationToken` table
  stores `identifier` (email) + `token` (6 digits) + `expires`.
- **SMTP backend** — `nodemailer-brevo-transport` with `SMTP_KEY` env var. Handlebars
  email templates per tenant with i18n support. This transport is what we adopt.
- **Chat interface** — message list, markdown rendering (react-markdown + remark-gfm),
  tool message rendering with collapsible metadata, `ThinkingMessage` component.
- **Voice** — STT via Whisper, TTS via ElevenLabs, per-tenant voice config.
- **i18n** — next-intl with 5 locales, tenant-specific overrides.
- **Multi-tenancy** — subdomain-based tenant resolution, per-tenant config/theming.
  Can be simplified for single-deployment or repurposed per computer.
- **Rich UI** — shadcn/ui, Tailwind, Framer Motion animations, ProseMirror editor.
- **Drizzle ORM + Postgres** — user, chat, message, session, verificationToken tables.
- **Redis WebSocket bridge** — keyspace notifications → WS server (port 3001) →
  browser clients. External backend writes to Redis, WS server broadcasts.

### What it has that we DON'T keep

- **Custom `useChat` hook** — polls `/api/chat` with SWR (1s interval), sends to n8n
  webhook, no streaming. This gets replaced entirely by Vercel AI SDK `useChat`.
- **n8n integration** — webhook POST to external backend. Replaced by daemon API.
- **SWR polling for messages** — replaced by SSE streaming via AI SDK.

### What changes (the bridge to TeleClaude)

| ai-chatbot currently                        | TeleClaude replacement                                  |
| ------------------------------------------- | ------------------------------------------------------- |
| Custom `useChat` with SWR polling           | Vercel AI SDK v5 `useChat` with `DefaultChatTransport`  |
| POST to n8n webhook                         | POST to daemon SSE endpoint (AI SDK protocol)           |
| Redis keyspace → WS → client                | Daemon SSE stream → `useChat` (fetch streaming)         |
| Chat ID (UUID)                              | TeleClaude session_id                                   |
| n8n erase webhook                           | DELETE /sessions/{id} on daemon API                     |
| NextAuth verify against Postgres user table | Verify against people list from config                  |
| Tool messages from n8n (flat text)          | Structured UIMessage parts (reasoning, tool-call, text) |

## The Bridge Library: Vercel AI SDK v5

The Vercel AI SDK is the key piece. It defines a wire protocol (UIMessage Stream) that
maps perfectly onto what TeleClaude agents produce: thinking blocks, tool calls, and
text responses. The daemon speaks this protocol, and the React frontend consumes it
via `useChat`.

### Wire Protocol: UIMessage Stream (SSE over HTTP POST)

The daemon's streaming endpoint returns Server-Sent Events with header
`x-vercel-ai-ui-message-stream: v1`. Each event is `data: {json}\n\n`.

**Event types that map to TeleClaude output:**

| Agent output                 | AI SDK SSE events                                                                     |
| ---------------------------- | ------------------------------------------------------------------------------------- |
| Thinking/reasoning block     | `reasoning-start` → `reasoning-delta` (chunks) → `reasoning-end`                      |
| Tool call (Read, Bash, etc.) | `tool-input-start` → `tool-input-available` (args) → `tool-output-available` (result) |
| Text response                | `text-start` → `text-delta` (chunks) → `text-end`                                     |
| Session status change        | `data-session-status` (custom part: `{"status":"running","agent":"claude"}`)          |
| Directory change             | `data-directory-change` (custom part)                                                 |
| Process exit                 | `data-process-exit` (custom part)                                                     |
| `send_result` artifact       | `data-send-result` (custom part with markdown/HTML content)                           |
| File path reference          | `file` event (with local URL to daemon file endpoint)                                 |

**Message lifecycle wrapper:**

```
data: {"type":"start","messageId":"msg_abc123"}
data: {"type":"reasoning-start","id":"rsn_001"}
data: {"type":"reasoning-delta","id":"rsn_001","delta":"Let me think about..."}
data: {"type":"reasoning-end","id":"rsn_001"}
data: {"type":"text-start","id":"txt_001"}
data: {"type":"text-delta","id":"txt_001","delta":"Here is the answer..."}
data: {"type":"text-end","id":"txt_001"}
data: {"type":"finish"}
data: [DONE]
```

### UIMessage Parts (client-side)

The `useChat` hook parses SSE events into `UIMessage` objects with typed `parts`:

```typescript
interface UIMessage {
  id: string;
  role: 'user' | 'assistant';
  parts: (
    | { type: 'text'; text: string }
    | { type: 'reasoning'; text: string }
    | { type: 'tool-call'; toolCallId: string; toolName: string; args: object }
    | { type: 'tool-result'; toolCallId: string; result: unknown }
    | { type: 'file'; data: string; mediaType: string }
    | { type: `data-${string}`; data: unknown } // custom TeleClaude parts
  )[];
}
```

React components render each part type:

- `reasoning` → collapsible thinking block (collapsed by default)
- `tool-call` + `tool-result` → collapsible tool block with name, args, result
- `text` → full markdown rendering (react-markdown + remark-gfm)
- `data-send-result` → rich card/panel with markdown or HTML content
- `file` → clickable link to daemon file endpoint

### Transport: NOT WebSocket

The AI SDK uses `fetch()` with standard Streams API (ReadableStream) to consume the
SSE response. It is NOT WebSocket and NOT EventSource. The daemon serves a normal HTTP
POST response that streams SSE-formatted data. The connection stays open for the
duration of streaming.

This means the existing WebSocket `/ws` endpoint on the daemon is separate and can
coexist. The SSE endpoint serves the React frontend specifically.

### Client-side wiring

```typescript
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';

const { messages, sendMessage } = useChat({
  transport: new DefaultChatTransport({
    api: '/api/chat/stream', // Next.js API route that proxies to daemon
    headers: { Authorization: `Bearer ${sessionToken}` },
    prepareSendMessagesRequest: ({ messages }) => ({
      body: {
        sessionId: currentSessionId, // TeleClaude session ID
        messages,
      },
    }),
  }),
});
```

## The Plumbing: Daemon SSE Endpoint

### New endpoint on the daemon

`POST /api/chat/stream` — produces AI SDK v5 UIMessage Stream.

Two modes of operation:

1. **History replay** — on connect, read the session's existing JSONL transcript
   (Claude sessions produce structured JSONL with thinking, tool_use, text entries).
   Convert each entry to the appropriate SSE events. Use `since_timestamp` to avoid
   replaying the entire history on reconnect.

2. **Live streaming** — after history replay, subscribe to the session's `OutputChanged`
   events from the output poller via the event bus. Convert real-time output to SSE
   events and stream to the client.

### Transcript-to-SSE conversion

Claude JSONL transcripts already have structured entries that map directly:

| Claude JSONL entry                        | AI SDK SSE events            |
| ----------------------------------------- | ---------------------------- |
| `assistant` with `thinking` content block | `reasoning-start/delta/end`  |
| `assistant` with `tool_use` content block | `tool-input-start/available` |
| `tool_result` message                     | `tool-output-available`      |
| `assistant` with `text` content block     | `text-start/delta/end`       |

For Gemini/Codex sessions (less structured output), the threaded-output experiment
already parses output into blocks. The same parsing feeds the SSE converter.

### Python-side implementation

Option A: Use `fastapi-ai-sdk` library (community, produces AI SDK v5 SSE events).
Option B: Emit raw SSE manually — the format is trivial (`data: {json}\n\n`).

Either way, the endpoint is a `StreamingResponse` with `media_type="text/event-stream"`
and the required `x-vercel-ai-ui-message-stream: v1` header.

### Sending messages back

When the user types a message, `useChat` POSTs to the same endpoint. The daemon:

1. Extracts the user's text from the incoming messages array (last message)
2. Sends it to the TeleClaude session via `send_keys` (tmux bridge)
3. Begins streaming the session's response as SSE events

## Identity, Metadata, and Routing

### The core pattern

**Identity resolved at boundary → metadata enriched internally → routing by metadata.**

Every entry point resolves to a person. That person's identity becomes metadata on the
session. All messages flowing through carry routing context. Output is delivered only
to authorized recipients.

### Boundary authentication

| Entry Point  | Identity Signal                            | Resolution                                                              |
| ------------ | ------------------------------------------ | ----------------------------------------------------------------------- |
| **Web**      | Session cookie (from email OTP login)      | Cookie → NextAuth session → email → match people config → person + role |
| **Telegram** | `user_id` in message                       | Match `creds.telegram.user_id` in per-person config → person + role     |
| **TUI**      | `TELECLAUDE_USER` env var or `telec login` | Env var or interactive login → match people config → person + role      |
| **MCP**      | `caller_session_id` chain                  | Trace back through session chain to originating person                  |

For web: the unique identifier is the authenticated session cookie. No separate device
fingerprinting needed — the cookie IS the device identifier.

### Session metadata enrichment

When a session is created or a person interacts with one, the daemon stamps internal
metadata — conceptually like JWT claims, but they never leave the system:

```python
session.meta = {
    "person": "Morriz",           # resolved from boundary auth
    "role": "admin",              # from people config
    "origin": "web",              # which adapter/entry point
    "client_id": "cookie_abc",    # unique per client connection
    "visibility": "private",      # who can see this session's output
}
```

This metadata flows with the session. Every output event inherits it. The streaming
endpoint checks it before delivering.

### Visibility and routing

**Default: private.** A session's output goes only to the person who created it.

**Shared sessions:** Admin can mark sessions as shared (visible to members). The
streaming endpoint checks: is the connected client authenticated as a person with
access?

**Routing logic on the SSE endpoint:**

1. Client connects with auth cookie/header
2. Daemon resolves person from auth → people config
3. Daemon checks: does this person have visibility on the requested session?
   - They created it → yes
   - They're admin → yes (can see all)
   - Session is shared + they're member → yes
   - Otherwise → 403
4. Stream only authorized content

**Private messages at the boundary:** If a message is tagged `private` (e.g., a
`send_result` with sensitive content), the SSE stream includes it only for the
session's owner. Other watchers (admin monitoring) see a redacted placeholder.

### What the daemon needs

- **Session-to-person binding** — provided by `person-identity-auth` (`human_email`,
  `human_role`, optional `human_username`).
- **Auth middleware on API** — provided by `person-identity-auth` as a strict
  prerequisite for non-public routes.
- **Visibility filtering on SSE** — the streaming endpoint checks person + role
  before delivering events.
- **People list endpoint** — `GET /api/people` returns the people list from global
  config (for the login page to show available users).

## Authentication — Deep Dive

### What we take from ai-chatbot

- **NextAuth v5** framework with `Email` provider
- **Brevo SMTP transport** (`nodemailer-brevo-transport` + `SMTP_KEY`)
- **6-digit OTP** (not clickable magic link) — generated by NextAuth, sent via email,
  user enters code manually, 3-minute expiry
- **Database sessions** via DrizzleAdapter (session table, verificationToken table)
- **Handlebars email templates** with i18n support and tenant theming

### What we change

- **User table** — ai-chatbot has a standard NextAuth user table (id, email, name,
  emailVerified, image). We keep this structure but the source of truth for who CAN
  log in is the people list in global teleclaude.yml. The Drizzle user table is a
  cache of verification state, not the authority.
- **Verification against people config** — on login, NextAuth's `signIn` callback
  checks: does this email exist in the people config? If not, reject. If yes, proceed
  with OTP flow.
- **Role loading** — after auth, the session callback enriches the NextAuth session
  with the person's role from config. This role drives view access.
- **No self-registration** — unknown emails are rejected. Admin adds people via config.
- **SQLite instead of Postgres** — for localhost, Drizzle can use SQLite (simpler, no
  separate DB process). The schema stays the same.

### Auth flow (concrete)

1. User opens `localhost:3003` → sees login page with people list dropdown
2. User selects their name → frontend resolves email from people config
3. NextAuth `signIn('nodemailer', { email })` → generates 6-digit OTP
4. Brevo sends OTP email using existing SMTP transport
5. User enters 6-digit code → NextAuth verifies against `verificationToken` table
6. Session created in DB, httpOnly cookie set
7. All subsequent requests carry cookie → Next.js API routes read session → resolve
   person + role
8. API routes proxy to daemon with `X-TeleClaude-Person: Morriz` and
   `X-TeleClaude-Role: admin` headers (or a signed token)

### Cookie lifetime

- Localhost: 30 days (long-lived, low risk)
- Public exposure: configurable, shorter (7 days with refresh)

## Deployment Model

### Tier 1: Localhost (default, v1)

- **Next.js standalone** on localhost (e.g., `localhost:3003`)
- **TeleClaude daemon API** on localhost TCP port (e.g., `localhost:8420`) alongside
  the existing Unix socket
- **Two processes**: daemon (Python) + web (Node.js). Both on the same machine.
- Binds to `127.0.0.1` or LAN IP
- **Coexists** with TUI, Telegram, and MCP — another adapter, not a replacement

### Tier 2: Public exposure (future)

The web interface may be exposed publicly as a chatbot — same powerful agents, but
accessible over the internet. This changes the security model fundamentally.

**Current network state:**

- API server: Unix socket only (`/tmp/teleclaude-api.sock`). No TCP port.
- MCP server: Unix socket (`/tmp/teleclaude.sock`). No TCP port.
- Redis: TLS (`rediss://`) for cross-computer sync.
- No proxy, no SSL/TLS at the API layer.

**What public exposure requires:**

- TCP binding for daemon API (add `localhost:8420` alongside Unix socket)
- Reverse proxy with SSL passthrough (existing infra supports this)
- Full end-to-end TLS
- Auth on every API endpoint (zero auth today)
- Rate limiting per user/session/IP
- Input sanitization (see Security section)

## Security — Input Sanitization Layer

When the web interface is public-facing, every user message reaches a powerful AI agent.
This is a prompt injection attack surface.

### Current State

**No input validation exists anywhere in the message flow:**

- Telegram: text passes directly from `_handle_text_message()` → `CommandMapper` → session
- API: `SendMessageRequest` has `min_length=1` only — no content validation
- MCP: tool calls pass through without content inspection
- File uploads: filenames from Telegram used as path components without sanitization
  (path traversal risk in `input_handlers.py` — `file_path = session_workspace / file_name`)

### Proposed Sanitization Mechanism

1. **Chunking** — split input into segments analyzed independently
2. **Isolation analysis** — read each chunk in isolation (right-to-left, then
   left-to-right). Ask: "Does this resemble a malicious instruction?"
3. **Classification** — `clean`, `suspicious`, `malicious`. Suspicious gets second pass.
4. **Routing** — clean passes through. Malicious is blocked, flagged, logged to
   the agent logbook (see agent-logbook-observability todo), reported to admins.
5. **Transparency** — user sees blocked message without detection details.

### Where it lives

Hybrid: lightweight check in Next.js (obvious patterns, rate limiting), deep analysis
in daemon middleware (semantic analysis, protects all entry points).

### Existing file path traversal bug

```python
file_name = message.document.file_name  # untrusted!
file_path = session_workspace / file_name  # path traversal if ../
```

Needs fixing regardless of web interface work.

## Output Rendering — React Components

### Part-to-Component mapping

Each UIMessage part type maps to a React component:

| Part type             | Component                   | Behavior                                                                              |
| --------------------- | --------------------------- | ------------------------------------------------------------------------------------- |
| `reasoning`           | `<ThinkingBlock>`           | Collapsed by default. Shows "Thinking..." with chevron. Expand to see reasoning text. |
| `tool-call`           | `<ToolCallBlock>`           | Shows tool name + status. Collapsible args/result. Translated labels per tool.        |
| `tool-result`         | (merged into ToolCallBlock) | Result shown when tool completes.                                                     |
| `text`                | `<Markdown>`                | Full markdown: syntax highlighting, tables, links. react-markdown + remark-gfm.       |
| `data-send-result`    | `<ArtifactCard>`            | Rich card/panel. Renders markdown or HTML content from `send_result` tool.            |
| `data-session-status` | `<StatusBadge>`             | Agent icon + status (running/idle/exited).                                            |
| `file`                | `<FileLink>`                | Clickable link. Resolves to daemon file endpoint. Opens in-browser viewer.            |

### Existing patterns from ai-chatbot to reuse

- `PreviewMessage` — collapsible metadata (same pattern as tool blocks)
- `ThinkingMessage` — "Thinking..." indicator (adapt for reasoning parts)
- `Markdown` component — react-markdown + remark-gfm with custom renderers
- Tool message rendering with translated labels (`tools.${toolName}.active/finished`)

## Session Management Views

### Session List (sidebar)

- Active sessions with title, agent icon, last activity timestamp
- Click to switch between sessions (changes which session the SSE stream follows)
- "New Session" button → project picker, agent picker, title input
- Session actions: end session, view details

### Session View (main area)

- Chat-like message stream rendered from `useChat` messages with parts
- Input box at bottom (sendMessage → POST to daemon SSE endpoint)
- Session header: title, agent, project, status, computer

### Dashboard (admin/member)

- Computers with status indicators
- Projects with active session counts
- Memory search box
- Recent activity feed
- Security events from logbook (admin only)

## Technology Stack

- **Next.js 15** (App Router, standalone output)
- **Vercel AI SDK v5** (`@ai-sdk/react` for `useChat`, `ai` for `DefaultChatTransport`)
- **NextAuth v5** (email OTP, database sessions, DrizzleAdapter)
- **Brevo SMTP** (`nodemailer-brevo-transport`, adopted from ai-chatbot)
- **Drizzle ORM** (SQLite for localhost, Postgres for production)
- **shadcn/ui + Tailwind** (component library, styling)
- **react-markdown + remark-gfm** (markdown rendering)
- **Framer Motion** (animations)
- **next-intl** (i18n, future-proofing)

**Daemon-side additions:**

- **SSE streaming endpoint** (`POST /api/chat/stream`) producing AI SDK UIMessage Stream
- **Transcript-to-SSE converter** (JSONL → structured SSE events)
- **Auth middleware integration** (consume identity context produced by prerequisite middleware)
- **`fastapi-ai-sdk`** (optional — or raw SSE emission, the format is trivial)

## Architecture

```
Browser (localhost:3003)
  │
  ├── Next.js App
  │     ├── Server: NextAuth, API routes (proxy to daemon with auth headers)
  │     └── Client: useChat (AI SDK) → fetch streaming → SSE from daemon
  │
 └── POST /api/chat/stream ──→ TeleClaude Daemon (localhost:8420)
                                   │
                                   ├── Auth middleware (from person-identity-auth)
                                   ├── Session access check (person + role + visibility)
                                   ├── Transcript replay (JSONL → SSE events)
                                   ├── Live streaming (output poller → SSE events)
                                   ├── Message ingestion (user text → send_keys to tmux)
                                   └── Custom data parts (session status, files, artifacts)
```

## Dependencies

- Config schema validation (PersonEntry with email + role) — prerequisite
- Person identity & auth (session-to-person binding, role resolution) — prerequisite
- API server TCP binding (add localhost:8420 alongside Unix socket) — small daemon change
- People list API endpoint (GET /api/people) — new, simple
- SSE streaming endpoint on daemon — new, medium effort
- Transcript-to-SSE converter — new, maps existing JSONL parsing
- SMTP setup (Brevo API key, email templates) — adopted from ai-chatbot

## Implementation Sequence

1. **Daemon: TCP port** — expose API on localhost:8420 (auth middleware is a prerequisite from `person-identity-auth`)
2. **Daemon: SSE streaming endpoint** — `POST /api/chat/stream` producing AI SDK v5
   UIMessage Stream from session transcripts + live output
3. **Daemon: people list endpoint** — `GET /api/people` from config
4. **Fork/adapt ai-chatbot** — strip n8n/custom useChat, add Vercel AI SDK `useChat`
   with `DefaultChatTransport` pointing at daemon
5. **Auth integration** — NextAuth with email OTP against people config, Brevo SMTP
6. **Output rendering** — React components for each UIMessage part type
7. **Role-based views** — admin dashboard vs. member vs. newcomer onboarding
8. **Session metadata** — person binding, visibility, routing
9. **File serving** — clickable paths resolve to daemon file endpoint

## What We Don't Do (v1)

- No terminal emulator (no xterm.js). Structured parts are richer than raw terminal.
- No TUI command piping. Web exposes actions as buttons/forms.
- No replacing the TUI. Power users keep the terminal.
- No SSR for session content. Real-time via SSE streaming.
- No mobile-first design (localhost = desktop, but responsive is nice).
- No full prompt injection ML model (pattern-based detection in v1).

## Relationship to Other Work

- **config-schema-validation** → shared prerequisite (PersonEntry with email + role)
- **person-identity-auth** → direct prerequisite (session-to-person binding, role
  resolution, auth middleware, JWT claim mapping to internal metadata)
- **agent-logbook-observability** → security events from sanitization need a logbook
- **role-based-notifications** → uses same person + role metadata for routing
