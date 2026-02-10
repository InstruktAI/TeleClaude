---
description: 'Memory review job: periodic AI analysis of accumulated memories for patterns, staleness, and actionable insights.'
id: 'project/spec/jobs/memory-review'
scope: 'project'
type: 'spec'
---

# Memory Review — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## What it does

Reviews all recent memories from the Memory API, analyzes them for patterns and
staleness, and writes actionable findings to `ideas/` as new idea files.

## How it works

1. The cron runner spawns a headless agent session.
2. The agent reads this spec (its complete mandate) and the hygiene procedure.
3. The agent calls the Memory API's search endpoint to pull recent observations.
4. The agent analyzes the memories for: recurring themes, stale entries,
   contradictions, actionable patterns.
5. For each actionable finding, creates an `ideas/` file (YYMMDD-slug.md format).
6. The agent writes a run report and stops.

## Files

| File                                      | Role                                        |
| ----------------------------------------- | ------------------------------------------- |
| `teleclaude.yml`                          | Job schedule and agent configuration        |
| `teleclaude/cron/runner.py`               | Runner — spawns agent session               |
| `docs/project/spec/jobs/memory-review.md` | This spec — agent reads it for instructions |

## Known issues

- Agent jobs are fire-and-forget; the cron runner does not wait for completion
  or capture the agent's output. Success means the session was spawned, not
  that the review completed without errors. The run report is the audit trail.
