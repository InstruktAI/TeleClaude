# Input: history-search-upgrade

<!-- Converged design from AI-to-AI peer conversation (3 breath cycles, sessions f099c0ab + 137c5e46). -->

## Problem

Agent session transcripts contain everything — tool calls, thinking, system metadata. We need a searchable recall layer that captures only the natural conversation: what was discussed, decided, and concluded. This system must work across multiple computers.

## Core Concept

A **mirror** is a purpose-built recall artifact, not a degraded transcript. The transcript records what the agent _did_. The mirror records what was _discussed_. Different documents for different jobs.

**Evidence**: Real transcript analysis (session 1c178904, 813KB, 430 JSONL entries) showed 73 conversation-only messages (17% of entries). The conversation-only view is coherent — decisions, conclusions, and rationale are preserved because agents naturally summarize tool findings in their text responses.

## Two-Tier Architecture

- **Mirrors travel** — lightweight recall index distributed across computers via Redis channels
- **Raw transcripts stay home** — forensic archive on the originating machine

For recall ("what did we discuss about X?") — the mirror answers perfectly.
For forensics ("what was the exact error?") — the raw transcript on the source machine has it.
The mirror tells you WHAT happened and WHERE to look deeper.

## Three Independent Concerns

### Generation (where mirrors are created)

- Mirrors are generated locally, on the machine that ran the session (the only computer with the JSONL)
- **Trigger**: daemon `session_closed` event fires full mirror generation
- **Long-running sessions**: daemon fires periodic `mirror_update` every ~30 minutes of activity
- **Extraction**: `extract_structured_messages(path, agent, include_tools=False, include_thinking=False)` — already exists in `teleclaude/utils/transcript.py`
- **Filtering**: strip empty text blocks (noise entries before tool work) and `<system-reminder>` tags in user messages (metadata, not conversation)
- **Backfill**: one-time agent job processes all existing ~3,660 transcripts. Batch migration, runs once overnight. After that, incremental.

### Distribution (how mirrors reach other computers)

- Published via Redis Streams channels (deployment fanout pattern as template)
- Channel: `mirrors:transcripts` (or scoped per project)
- Remote daemons consume and materialize into their local mirrors table
- Heartbeat + cache for computer discovery (existing infrastructure)
- What travels on the channel is the same regardless of local storage — the protocol is independent of materialization strategy

### Search (history.py upgrade)

- Default: searches local mirrors table via FTS5
- `--computer VALUE`: routes search to remote daemon API
- `--agent VALUE`: filters by agent type (claude, codex, gemini)
- `--show SESSION`: renders mirror content as readable text
- `--show SESSION --raw`: fetches full transcript from source computer via daemon API
- Single entry point for both recall and forensics — routing is hidden from the user

## Storage

- **mirrors table** in daemon SQLite database (not a separate DB file)
- FTS5 for full-text search across thousands of sessions
- Key columns: `session_id`, `computer`, `agent`, `project`, `title`, `timestamp_start`, `timestamp_end`, `conversation_text` (FTS5-indexed), `metadata` (JSON)
- INSERT OR REPLACE by `session_id` enables incremental updates without complexity
- Respects single-database policy: mirrors are a daemon DB table, history.py reads in read-only mode

## Ownership

- **Daemon**: generates mirrors (from transcripts), publishes to channel, consumes remote mirrors, writes to mirrors table
- **history.py**: reads daemon DB in read-only mode. Works even when daemon is down (existing mirrors still searchable, no new generation)
- **Agents**: use the history CLI tool. Never touch SQLite directly.

## What the Mirror Captures

- User text messages (`role=user`, `type=text`)
- Agent text responses (`role=assistant`, `type=text`)

## What the Mirror Filters

- `tool_use` blocks — mechanism, not conversation
- `tool_result` blocks — mechanism, not conversation
- `thinking` blocks — internal reasoning, not output
- Empty text blocks — noise before tool work
- `<system-reminder>` tags in user messages — metadata injected by hooks/CLAUDE.md loading

## What Is Lost (acceptable cost)

- Specific file paths the agent read but didn't mention in text output
- Raw error messages that only appeared in tool results
- Exact command outputs (pytest runs, grep results, etc.)
- The precise sequence of tool operations

These are available via `--show SESSION --raw` drill-down to the source computer.

## Key Existing Infrastructure

- `extract_structured_messages()` in `teleclaude/utils/transcript.py` (line ~2066) — already does text-only filtering
- `_discover_transcripts()` in `teleclaude/utils/transcript.py` — discovers transcripts across agents
- Redis Streams transport for cross-computer messaging (existing)
- Heartbeat-based peer discovery with TTL (existing)
- Hook service with `session_closed` events (existing)
- `telec channels publish/list` CLI (existing)
- Cron job infrastructure for the backfill agent job (existing)

## Design Process

This design was produced through a structured AI-to-AI peer conversation using three breath cycles (inhale/hold/exhale). Round 1 failed due to premature convergence and a fundamental error (designing text-level stripping when the data layer already solves extraction). Round 2 succeeded by: (1) questioning the premise ("agent sessions are not conversations"), (2) grounding in real data, (3) identifying the "recall" frame as primary use case, (4) separating generation/distribution/search as independent concerns, (5) resolving file-vs-SQLite with FTS5 argument, (6) resolving the cost question with the two-tier model.
