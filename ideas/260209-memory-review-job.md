# Memory Review Job

Periodic job that reads all memories from the Memory API, analyzes patterns, and produces actionable output.

## What it does

- Pulls all memories (or recent window) from `/api/memory/search`
- AI analyzes for: recurring themes, stale entries, contradictions, actionable patterns
- Outputs a digest report (Telegram or file)
- Promotes actionable findings directly to `todos/` when concrete and scoped.

## Why

Memories accumulate but nobody reviews them. Patterns emerge over time that aren't visible in individual entries. A periodic review surfaces these patterns and keeps the memory layer healthy.

## Follow-up routing

Memory review should either:

- open a concrete todo when the action is clear, or
- produce no output when findings are too vague.

## Implementation

A `jobs/memory_review.py` on the existing cron runner, scheduled weekly or daily.
