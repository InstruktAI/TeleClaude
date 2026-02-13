# Roadmap

> Work item state lives in `todos/{slug}/state.json`.
> Delivered items: [delivered.md](./delivered.md) | Parked: [icebox.md](./icebox.md)

---

## Help Desk Platform

- help-desk-whatsapp (after: help-desk)

Implement the WhatsApp adapter and webhook handling, mapping incoming phone numbers to Customer identities and routing them to the Help Desk lobby.

- help-desk-discord (after: help-desk)

Implement the Discord adapter and bot client using discord.py. Leverage Forum Channels (Type 15) to map each customer session to a dedicated thread, mirroring the Telegram "Control Room" model. Map Discord user IDs to Customer identities.

- help-desk-control-room (after: help-desk-whatsapp, help-desk-discord, agent-activity-events)

Implement the Admin Telegram mirroring and intervention logic. Establish the "Admin Supergroup" where Help Desk sessions are mirrored as topics, allowing Admins to monitor and intervene in customer chats.

## Release Automation

- release-automation

A fully automated release pipeline where a dedicated AI inspector analyzes diffs on every main push, decides whether to release (patch/minor) based on contract manifests, and creates releases automatically with generated notes. Features a dual-lane pipeline (Claude Code + Codex CLI) and a consensus arbiter.

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

## Role-Based Notifications

- role-based-notifications

Notification routing subsystem that sends job outputs, reports, and alerts to people based on their role and channel subscriptions in per-person teleclaude.yml. Generalizes the existing personal Telegram script into a multi-person delivery layer.

## Maintenance

- project-aware-bug-routing

- test-suite-ownership-reset

Freeze non-emergency feature changes and reset test ownership to a deterministic one-to-one model (`source file -> owning unit test`) with path-based test gating. Keep functional/integration tests active as the behavior safety net while rewriting brittle unit tests.

Introduce prefix-based bug routing (`bug-*`) with an atomic per-bug loop (fix -> independent review -> retry/needs_human), while keeping bug intake low-friction (no mandatory project-name argument, explicit TeleClaude override available) and enforcing landing safety gates.
