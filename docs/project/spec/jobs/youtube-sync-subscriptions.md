---
description: 'YouTube subscription tagger job: nightly AI classification of untagged channels.'
id: 'project/spec/jobs/youtube-sync-subscriptions'
scope: 'project'
type: 'spec'
---

# Youtube Sync Subscriptions — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## What it does

For each person with YouTube subscriptions configured, runs the tagging script
against their `youtube.csv`. The script finds channels with empty tags and
classifies them using AI. Already-tagged channels are skipped. Results are
written back to CSV.

## How it works

The agent supervises the existing tagging pipeline:

1. `teleclaude/cron/discovery.py` scans `~/.teleclaude/people/*/teleclaude.yml`
   for entries with `subscriptions.youtube` configured.
2. For each subscriber, the tagging script `teleclaude/tagging/youtube.py` is
   invoked via `sync_youtube_subscriptions()`.
3. The tagging script reads the CSV, enriches untagged channels with About page
   descriptions, sends batches to AI with the subscriber's allowed tag list,
   validates responses, and falls back to web research for channels tagged `n/a`.
4. Only untagged rows are processed. Tagged rows are never touched unless explicitly
   called with `refresh=True` (not used by the nightly job).
5. The agent writes a run report and stops.

If the tagging script fails, the agent diagnoses the error and fixes forward if
the issue is within this job's scope (the files listed below). Out-of-scope issues
are recorded in the run report.

## Files

| File                                 | Role                                              |
| ------------------------------------ | ------------------------------------------------- |
| `teleclaude/tagging/youtube.py`      | Tagging library — CSV ops, AI tagging, validation |
| `teleclaude/cron/discovery.py`       | Finds subscribers with YouTube config             |
| `jobs/youtube_sync_subscriptions.py` | Job wrapper — discovery + iteration               |

## Configuration

Per-person at `~/.teleclaude/people/{name}/teleclaude.yml`:

```yaml
subscriptions:
  youtube: youtube.csv
interests:
  tags:
    - ai
    - devtools
    - geopolitics
```

## Data

`~/.teleclaude/people/{name}/subscriptions/youtube.csv` with columns:
`channel_id`, `channel_name`, `handle`, `tags`.

## Known issues

- **Duplicate tagging code.** `teleclaude/tagging/youtube.py` and
  `teleclaude/entrypoints/youtube_sync_subscriptions.py` share ~600 lines of
  duplicated prompts, validation, and CSV logic. Consolidation: port the
  entrypoint's unique feature (`_call_youtube_helper()` — YouTube API fetch)
  into the tagging module, reduce entrypoint to a thin CLI wrapper.
- **Legacy wrappers.** `cron/youtube-sync-subscriptions.py` and the standalone
  entrypoint predate the jobs runner. To be cleaned up during consolidation.
- **No onboarding skill.** No skill exists to orchestrate per-person setup
  (YouTube subscription fetch, tag configuration, digest opt-in). The initial
  subscription fetch currently requires the entrypoint CLI with
  `--fetch-subscriptions`.
