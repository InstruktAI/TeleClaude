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

## Scope (fix-forward boundary)

- `teleclaude/tagging/youtube.py`
- `teleclaude/cron/discovery.py`
- `jobs/youtube_sync_subscriptions.py`

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
