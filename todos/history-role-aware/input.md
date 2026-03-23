# history-role-aware — Input

## Goal

Make telec history commands user/role-aware and add telec history list for progressive disclosure of session history.

## Context

Currently telec history search and telec history show have no concept of caller identity. Admin, member, and customer all get the same unfiltered view. Mirrors already have source_identity field but no role-based filtering.

The help desk agent needs progressive disclosure: list session summaries first (telec history list), pick the relevant one, then show full transcript (telec history show). Same two-phase pattern as telec docs index → telec docs get.

## What needs to happen

### 1. telec history list — new command

New command: telec history list [--identity <email_or_key>] [--project <name>] [--limit <n>]

Returns session summaries from mirrors: session_id, title, timestamp_start, timestamp_end, origin channel (from adapter metadata), short summary, message_count. Ordered by recency.

This is the progressive disclosure entry point. Agent reads the list, picks the relevant session ID, then calls telec history show for the full transcript.

### 2. Channel metadata in mirrors

Flow adapter_metadata from sessions into mirror records at mirror-creation time. The mirror already has source_identity; add origin_channel (web/telegram/discord/whatsapp) and channel-specific identifiers (telegram user_id, discord channel_id, etc.) to the mirror metadata dict.

Mirror creation already fires on AGENT_STOP and SESSION_CLOSED — the session adapter_metadata is available at that point. Just write it through.

### 3. Role-aware filtering

Scope history commands by caller identity:
- Admin: unfiltered, sees all sessions across all computers and projects
- Member: filtered by project membership (from people config). Sees sessions in their registered projects only.
- Customer: filtered by source_identity (their email/channel ID). Sees only their own session history.

The filtering happens at the API level (daemon-side) and CLI level (telec history commands pass caller identity).

### 4. Session summary in mirrors

Mirrors have conversation_text (full cleaned conversation) and title. Add a summary field — a one-paragraph summary of the session generated at mirror creation time. Uses the existing _call_summarizer pattern from teleclaude/core/summarizer.py (Claude Haiku with structured outputs).

This summary is what telec history list shows — the agent reads summaries to decide which session to dig into.

## Architecture

Session close → mirror created with summary + channel metadata
telec history list → reads mirrors, returns summaries (role-filtered)
telec history show → reads mirror conversation_text or raw transcript (role-filtered)
Agent progressive disclosure: list → pick session → show → help customer

## Key files

- teleclaude/cli/telec/handlers/history.py — CLI handlers for history commands
- teleclaude/history/search.py — search implementation (mirrors table queries)
- teleclaude/mirrors/store.py — mirror upsert, MirrorRecord
- teleclaude/mirrors/generator.py — mirror generation from transcripts
- teleclaude/mirrors/event_handlers.py — AGENT_STOP and SESSION_CLOSED handlers
- teleclaude/core/summarizer.py — existing LLM summarizer pattern
- teleclaude/core/models/_session.py — Session with adapter_metadata
- teleclaude/core/models/_adapter.py — SessionAdapterMetadata (Telegram, Discord, WhatsApp)
