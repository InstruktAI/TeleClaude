# Roadmap

> Work item state lives in `todos/{slug}/state.json`.
> Delivered items: [delivered.md](./delivered.md) | Parked: [icebox.md](./icebox.md)

---

## Help Desk Platform

> Architecture: `docs/project/design/architecture/help-desk-platform.md`
>
> Every person gets a persistent personal agent folder. Members/admins are invited via
> private channels; customers discover the system through public-facing channels.
> Admins additionally observe all sessions via supergroups. Notifications arrive through
> the same bot identity as conversations (credential unity).

## Web Interface

- web-interface (after: help-desk) — **BROKEN DOWN**

Next.js 15 web application bridged to TeleClaude via Vercel AI SDK v5. Daemon produces AI SDK UIMessage Stream (SSE) from session transcripts and live output. Frontend uses `useChat` with `DefaultChatTransport`. Auth via NextAuth email OTP (6-digit code, Brevo SMTP adopted from ai-chatbot). Session-to-person metadata binding with visibility routing. React components for each UIMessage part type (reasoning, tool-call, text, custom data parts for send_result artifacts and file links).

- web-api-proxy-completion (after: web-interface-3) — WebSocket bridge, REST proxy expansion, auth enforcement, frontend state integration
- web-interface-4 (after: web-interface-3) — Session Management & Role-Based Access

## Documentation Access Control

- doc-access-control

Role-based `clearance` frontmatter for doc snippets (`public`/`member`/`admin`). Filters `get_context` results by the calling agent's role. Default `member` for backward compatibility. Required for gating admin-only specs (e.g., itsUP API) away from public-facing agents.

## Rolling Session Titles

- rolling-session-titles

Re-summarize session titles based on the last 3 user inputs instead of only the first. Use a dedicated rolling prompt that captures session direction. Reset the output message on any title change so the telegram title feedback (native client behavior) floats to the top in Telegram.

## Maintenance

- project-aware-bug-routing

- test-suite-ownership-reset

Freeze non-emergency feature changes and reset test ownership to a deterministic one-to-one model (`source file -> owning unit test`) with path-based test gating. Keep functional/integration tests active as the behavior safety net while rewriting brittle unit tests.

Introduce prefix-based bug routing (`bug-*`) with an atomic per-bug loop (fix -> independent review -> retry/needs_human), while keeping bug intake low-friction (no mandatory project-name argument, explicit TeleClaude override available) and enforcing landing safety gates.
