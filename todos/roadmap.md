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

- help-desk-control-room (after: help-desk-discord)

Admin supergroup mirroring and intervention. Establish supergroups on Discord like we have for Telegram where all AI sessions are mirrored as topics/threads. Admins observe and can intervene in such chats. For Telegram, right now we don't have any distinction between help desk and internal sessions. It would be great if we could find a way to make this distinction for Discord because Telegram does not give us these rich primitives to also have sub channels in channels and such. We cannot group threads in supergroups, unfortunately. That's why we wanted to move to Discord for this richer experience. So we have to find out if we can establish this. This is what is important.

## Session Messages API

- session-messages-api — Structured messages endpoint from native session files

Structured `GET /sessions/{id}/messages` endpoint backed by native transcript files. Accumulates transcript file paths per session (chain storage) instead of replacing on rotation. Extracts structured message objects (role, type, text, timestamp) from Claude/Codex/Gemini JSONL/JSON files. Exposes compaction events as first-class system messages. Supports incremental fetch via `since` timestamp. Prerequisite for web-interface SSE plumbing.

## Web Interface

- web-interface (after: help-desk) — **BROKEN DOWN**

Next.js 15 web application bridged to TeleClaude via Vercel AI SDK v5. Daemon produces AI SDK UIMessage Stream (SSE) from session transcripts and live output. Frontend uses `useChat` with `DefaultChatTransport`. Auth via NextAuth email OTP (6-digit code, Brevo SMTP adopted from ai-chatbot). Session-to-person metadata binding with visibility routing. React components for each UIMessage part type (reasoning, tool-call, text, custom data parts for send_result artifacts and file links).

- web-interface-1 (after: session-messages-api, help-desk) — Daemon SSE Plumbing
- web-interface-2 (after: web-interface-1) — Next.js Scaffold & Auth
- web-interface-3 (after: web-interface-2) — Chat Interface & Part Rendering
- web-interface-4 (after: web-interface-3) — Session Management & Role-Based Access

## Rolling Session Titles

- rolling-session-titles

Re-summarize session titles based on the last 3 user inputs instead of only the first. Use a dedicated rolling prompt that captures session direction. Reset the output message on any title change so the telegram title feedback (native client behavior) floats to the top in Telegram.

## Maintenance

- project-aware-bug-routing

- test-suite-ownership-reset

Freeze non-emergency feature changes and reset test ownership to a deterministic one-to-one model (`source file -> owning unit test`) with path-based test gating. Keep functional/integration tests active as the behavior safety net while rewriting brittle unit tests.

Introduce prefix-based bug routing (`bug-*`) with an atomic per-bug loop (fix -> independent review -> retry/needs_human), while keeping bug intake low-friction (no mandatory project-name argument, explicit TeleClaude override available) and enforcing landing safety gates.
