# Memory Review Job

Periodic job that reads all memories from the Memory API, analyzes patterns, and produces actionable output.

## What it does

- Pulls all memories (or recent window) from `/api/memory/search`
- AI analyzes for: recurring themes, stale entries, contradictions, actionable patterns
- Outputs a digest report (Telegram or file)
- Promotes actionable findings to `ideas/` (not todos — memories are raw signal, not verified work)

## Why

Memories accumulate but nobody reviews them. Patterns emerge over time that aren't visible in individual entries. A periodic review surfaces these patterns and keeps the memory layer healthy.

## Relationship to idea-miner

The idea-miner processes `ideas/` files. This job feeds the memory layer into `ideas/` — they're complementary, not overlapping. Memory review produces ideas; idea-miner evaluates them.

## Implementation

A `jobs/memory_review.py` on the existing cron runner, scheduled weekly or daily.
