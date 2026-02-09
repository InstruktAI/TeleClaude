---
id: 'project/spec/jobs/merge-runner'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Agent job spec for serialized merge promotion of approved todos from worktree branches into main.'
---

# Merge Runner — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@~/.teleclaude/docs/general/procedure/maintenance/merge-runner.md

## What it is

A maintenance job that performs merge-only promotion into `main` using a single,
serialized runner in an isolated merge workspace.

It exists to prevent concurrent integration races when multiple worker sessions
finish in parallel.

## Canonical fields

### Schedule

Configured in `teleclaude.yml`:

```yaml
jobs:
  merge_runner:
    schedule: hourly
    type: agent
    job: merge-runner
    agent: claude
    thinking_mode: med
```

### Merge gate

A slug is eligible only when `todos/{slug}/state.json` indicates:

- `build == complete`
- `review == approved`
- `docstrings == complete`
- `snippets == complete`
- `deferrals_processed == true` if deferrals exist

### Execution boundaries

- Merge execution is the only responsibility.
- Merge execution happens in isolated merge workspace, never in the user's live main workspace.
- One merge operation at a time.
- On conflict, stop immediately and report.

### Artifacts touched

- `todos/roadmap.md`
- `todos/delivered.md`
- `~/.teleclaude/jobs/merge-runner/runs/{YYMMDD-HHMMSS}.md`

## Allowed values

- `agent`: `claude`, `gemini`, `codex`
- `thinking_mode`: `fast`, `med`, `slow`
- `schedule`: `hourly`, `daily`, `weekly`, `monthly`
- `preferred_hour`: integer `0..23` (for non-hourly schedules)

## Known caveats

- This job does not resolve semantic conflicts; it reports and stops on first merge conflict.
- This job assumes branch naming for slugs is stable and deterministic.
- This job does not replace review/build/doc phases; it only promotes work already approved.
- Current scheduler granularity is hourly; sub-hour cadence requires scheduler enhancement.
