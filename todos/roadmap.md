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

- [.] help-desk

Universal entry point for external interactions with built-in identity resolution. IdentityResolver maps adapter metadata (telegram user_id, web email, etc.) against people config to determine admin/member/unauthorized. Unauthorized users get jailed to help-desk project with restricted agent profile. Dual-profile agent configuration (`default` vs `restricted`). Filesystem jailing via settings.json denial rules. Human role tool gating parallel to AI role gating.

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

## Role-Based Notifications

- [.] role-based-notifications

Notification routing subsystem that sends job outputs, reports, and alerts to people based on their role and channel subscriptions in per-person teleclaude.yml. Generalizes the existing personal Telegram script into a multi-person delivery layer.

## Maintenance

- [.] tts-fallback-saturation

Fix TTS fallback logic to respect voice saturation. Currently, fallback providers pick random voices without checking availability, leading to voice collisions and "multiple voices" in a single session. The fix ensures fallbacks only select _free_ voices, saturating providers from top to bottom.
