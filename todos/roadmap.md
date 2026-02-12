# Roadmap

> **Last Updated**: 2026-02-11
>
> **Status**: `[ ]` Pending | `[.]` Ready (has requirements) | `[>]` In Progress
>
> Delivered items are listed in [delivered.md](./delivered.md). The roadmap focuses on upcoming work and high-level initiatives, while delivered.md serves as a comprehensive changelog of completed tasks. This separation allows the roadmap to remain forward-looking and strategic, while still providing a detailed record of past accomplishments in delivered.md.
>
> **Other lists**:
> [delivered.md](./delivered.md) — completed work |
> [icebox.md](./icebox.md) — parked, no active priority

---

## Help Desk Platform

- [.] help-desk-clients (after: help-desk, agent-activity-events)

Connect external messaging platforms (WhatsApp, Discord) to the Help Desk lobby. Implements "Admin Supergroup" observability where all customer sessions are mirrored to a Telegram Control Room for real-time monitoring and intervention. Updates AdapterClient for multi-destination routing.

## Release Automation

- [.] release-automation

A fully automated release pipeline where a dedicated AI inspector analyzes diffs on every main push, decides whether to release (patch/minor) based on contract manifests, and creates releases automatically with generated notes. Features a dual-lane pipeline (Claude Code + Codex CLI) and a consensus arbiter.

## Session Messages API

- [.] session-messages-api — Structured messages endpoint from native session files

Structured `GET /sessions/{id}/messages` endpoint backed by native transcript files. Accumulates transcript file paths per session (chain storage) instead of replacing on rotation. Extracts structured message objects (role, type, text, timestamp) from Claude/Codex/Gemini JSONL/JSON files. Exposes compaction events as first-class system messages. Supports incremental fetch via `since` timestamp. Prerequisite for web-interface SSE plumbing.

## Web Interface

- [ ] web-interface (after: help-desk) — **BROKEN DOWN**

Next.js 15 web application bridged to TeleClaude via Vercel AI SDK v5. Daemon produces AI SDK UIMessage Stream (SSE) from session transcripts and live output. Frontend uses `useChat` with `DefaultChatTransport`. Auth via NextAuth email OTP (6-digit code, Brevo SMTP adopted from ai-chatbot). Session-to-person metadata binding with visibility routing. React components for each UIMessage part type (reasoning, tool-call, text, custom data parts for send_result artifacts and file links).

- [.] web-interface-1 (after: session-messages-api, help-desk) — Daemon SSE Plumbing
- [ ] web-interface-2 (after: web-interface-1) — Next.js Scaffold & Auth
- [ ] web-interface-3 (after: web-interface-2) — Chat Interface & Part Rendering
- [ ] web-interface-4 (after: web-interface-3) — Session Management & Role-Based Access

## Rolling Session Titles

- [ ] rolling-session-titles

Re-summarize session titles based on the last 3 user inputs instead of only the first. Use a dedicated rolling prompt that captures session direction. Reset the output message on any title change so the telegram title feedback (native client behavior) floats to the top in Telegram.

## Role-Based Notifications

- [.] role-based-notifications

Notification routing subsystem that sends job outputs, reports, and alerts to people based on their role and channel subscriptions in per-person teleclaude.yml. Generalizes the existing personal Telegram script into a multi-person delivery layer.

## Maintenance

- [ ] telegram-adapter-hardening — **BROKEN DOWN**

Harden Telegram routing and fallback behavior by enforcing one delivery funnel, explicit result contracts, bounded invalid-topic cleanup, and stronger delete ownership checks.

- [.] telegram-routing-contract-hardening
- [ ] telegram-topic-cleanup-guards (after: telegram-routing-contract-hardening)
- [ ] telegram-ownership-layering-cleanup (after: telegram-topic-cleanup-guards)
- [ ] fallback-fail-fast-hardening (after: telegram-routing-contract-hardening)

Cross-cutting fail-fast contract hardening sourced from the Telegram fallback audit and follow-up core findings. Removes sentinel coercion for required inputs, removes the erroneous non-role-based `help-desk` reroute while preserving explicit non-admin jailing behavior, makes `get_session_data` availability explicit, and hardens parse-entities/footer + invalid-topic suppression behavior.

- [ ] project-aware-bug-routing

Introduce prefix-based bug routing (`bug-*`) with an atomic per-bug loop (fix -> independent review -> retry/needs_human), while keeping bug intake low-friction (no mandatory project-name argument, explicit TeleClaude override available) and enforcing landing safety gates.
