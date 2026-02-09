---
description: 'Memory review job: periodic AI analysis of accumulated memories for patterns, staleness, and actionable insights.'
id: 'project/spec/jobs/memory-review'
scope: 'project'
type: 'spec'
---

# memory_review — Spec

## What it does

Spawns a headless agent session that reads all recent memories from the Memory
API, analyzes them for patterns and staleness, and writes actionable findings
to `ideas/` as new idea files.

## Schedule

Configured in `teleclaude.yml` as an agent-type job:

```yaml
jobs:
  memory_review:
    schedule: weekly
    preferred_weekday: 0
    preferred_hour: 8
    type: agent
    agent: claude
    thinking_mode: fast
    message: >-
      You are running the memory review job. Read @docs/project/spec/jobs/memory-review.md
      for your full instructions.

      1. Search all recent memories via the Memory API (search with a broad query, limit 100).
      2. Analyze for: recurring themes, stale entries, contradictions, actionable patterns.
      3. For each actionable finding, create an ideas/ file (YYMMDD-slug.md format).
      4. Summarize what you found and what you promoted.
```

## How it works

1. The cron runner detects `type: agent` and calls the daemon's `POST /sessions`
   endpoint to spawn a headless agent session.
2. The agent boots with full context (doc snippets, MCP tools, file system).
3. The agent uses `teleclaude__get_context` to load this spec, then calls the
   Memory API's search endpoint via MCP to pull recent observations.
4. The agent analyzes the memories and writes findings to `ideas/` files.
5. The agent session exits on completion.

## No Python module needed

Agent-type jobs are declared entirely in `teleclaude.yml`. The cron runner
handles spawning; the agent handles execution. This is the pattern for any
job where the work IS "an AI doing things with tools."

## Files

| File                                      | Role                                        |
| ----------------------------------------- | ------------------------------------------- |
| `teleclaude.yml`                          | Job schedule and agent configuration        |
| `teleclaude/cron/runner.py`               | Runner with `type: agent` support           |
| `docs/project/spec/jobs/memory-review.md` | This spec — agent reads it for instructions |

## Known issues

- Agent jobs are fire-and-forget; the cron runner does not wait for completion
  or capture the agent's output. Success means the session was spawned, not
  that the review completed without errors.
