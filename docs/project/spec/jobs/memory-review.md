---
description: 'Memory review job: periodic AI analysis of accumulated memories for patterns, staleness, and actionable insights.'
id: 'project/spec/jobs/memory-review'
scope: 'project'
type: 'spec'
---

# Memory Review — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## What it is

Reviews all recent memories from the Memory API, analyzes them for patterns and
staleness, and writes actionable findings to `ideas/` as new idea files.

## Canonical fields

- `trigger`: periodic scheduled job.
- `input`: Memory API observations (all types).
- `output`: idea files under `ideas/` (YYMMDD-slug.md format) and a run report.

### How it works

1. Call the Memory API search endpoint to pull recent observations.
2. Analyze for: recurring themes, stale entries, contradictions, actionable patterns.
3. For each actionable finding, create an `ideas/` file (YYMMDD-slug.md format).
4. Write a run report and stop.
