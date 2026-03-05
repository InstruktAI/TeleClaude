---
description: 'YouTube subscription tagger job: nightly AI classification of untagged channels.'
id: 'project/spec/jobs/youtube-sync-subscriptions'
scope: 'project'
type: 'spec'
---

# Youtube Sync Subscriptions — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## What it is

A nightly AI job that classifies untagged YouTube subscriptions per person. For each person with YouTube subscriptions configured, runs the tagging script against their `youtube.csv`. The script finds channels with empty tags and classifies them using AI. Already-tagged channels are skipped. Results are written back to CSV.

## Canonical fields

- `trigger`: nightly cron schedule.
- `input`: per-person `youtube.csv` files at `~/.teleclaude/people/{name}/subscriptions/youtube.csv`.
- `output`: updated `youtube.csv` with AI-classified tags; run report.
- `csv_columns`: `channel_id`, `channel_name`, `handle`, `tags`.

### Per-person configuration

At `~/.teleclaude/people/{name}/teleclaude.yml`:

```yaml
subscriptions:
  youtube: youtube.csv
interests:
  tags:
    - ai
    - devtools
    - geopolitics
```

### Fix-forward boundary

- `teleclaude/tagging/youtube.py`
- `teleclaude/cron/discovery.py`
- `jobs/youtube_sync_subscriptions.py`

### How it works

1. `teleclaude/cron/discovery.py` scans `~/.teleclaude/people/*/teleclaude.yml` for entries with `subscriptions.youtube` configured.
2. For each subscriber, the tagging script `teleclaude/tagging/youtube.py` is invoked via `sync_youtube_subscriptions()`.
3. The tagging script reads the CSV, enriches untagged channels with About page descriptions, sends batches to AI with the subscriber's allowed tag list, validates responses, and falls back to web research for channels tagged `n/a`.
4. Only untagged rows are processed. Tagged rows are never touched unless explicitly called with `refresh=True` (not used by the nightly job).
5. The agent writes a run report and stops.
