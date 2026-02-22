# DOR Report: member-invite

## Draft Assessment

**Assessed by:** Claude (prepare-draft)
**Date:** 2026-02-21

## Readiness Summary

Requirements are comprehensive and cover all 9 functional areas. Implementation plan has 9 phases with specific file references, code patterns, and commit messages. The scope is well-bounded with clear in/out-of-scope delineation.

**Estimated DOR score: 85/100**

## What's Strong

- **Requirements coverage**: All three output channels (Telegram, Discord, WhatsApp) are specified with concrete link formats and binding flows
- **Existing infrastructure**: Identity resolution, notification outbox, adapter metadata, and per-person config all exist — this is extension work, not greenfield
- **Reference implementations**: `teleclaude/notifications/telegram.py` provides a clear pattern for Discord and email senders
- **Edge cases captured**: Token collision, workspace race conditions, DM availability on Discord, credential binding conflicts are all addressed
- **Adapter metadata preservation**: Requirements explicitly state that existing response routing (thread_id, channel_id, topic_id) must not be disrupted

## Assumptions

1. **Brevo SMTP is the email provider** — env vars `BREVO_SMTP_USER`, `BREVO_SMTP_PASS` will be configured before manual testing
2. **Bot tokens are valid and accessible** — `TELEGRAM_BOT_TOKEN` and `DISCORD_BOT_TOKEN` are already in the daemon environment
3. **`aiosmtplib` or `smtplib`** is acceptable for email sending — no existing SMTP dependency in the project
4. **WhatsApp deep link format** (`wa.me/{number}?text={token}`) works at client level without a Business API integration
5. **Person workspace path convention** is `~/.teleclaude/people/{name}/workspace/` — not yet formalized in config schema but implied by architecture doc
6. **Discord bot can open DM channels** with users who share a server — standard Discord bot capability
7. **No time-based token expiry** needed for v1 — tokens are valid until explicitly rotated

## Open Questions

1. **Email template design**: Should the HTML template use InstruktAI branding, or should it be configurable per organization? → **Default: InstruktAI branding, configurable later**
2. **`aiosmtplib` dependency**: Should we add it as a new dependency, or use stdlib `smtplib` via `asyncio.to_thread`? → **Default: `asyncio.to_thread(smtplib)` to avoid new dependency**
3. **Workspace `teleclaude.yml`**: What minimal config does a personal workspace need? → **Default: empty project config with person's name as description**
4. **Rate limiting on private chat handlers**: Should we add rate limiting for `/start` from unknown users? → **Default: yes, basic cooldown per user_id**
5. **Person home folder vs workspace**: Is `~/.teleclaude/people/{name}/` the home and `workspace/` is a subfolder used as project_path? → **Default: yes, per architecture doc**

## Blockers

None identified. All dependencies (identity resolution, notification outbox, adapter infrastructure) exist and are functional.

## Gate Readiness

This draft is ready for formal DOR gate assessment. The requirements are rich, the implementation plan maps to specific files and code locations, and the existing codebase patterns are well-understood. The open questions above have reasonable defaults that won't block implementation.
