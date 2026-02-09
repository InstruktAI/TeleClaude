---
description: 'YouTube subscription tagger job: nightly AI classification of untagged channels.'
id: 'project/spec/jobs/youtube-sync-subscriptions'
scope: 'project'
type: 'spec'
---

# youtube_sync_subscriptions — Spec

## What it does

For each person (and global scope) with YouTube subscriptions configured, reads
their `youtube.csv`, finds channels with empty tags, and classifies them using AI
agents. Already-tagged channels are skipped. Results are written back to CSV.

## Schedule

Configured in `teleclaude.yml`:

```yaml
jobs:
  youtube_sync_subscriptions:
    schedule: daily
    preferred_hour: 6
```

## How it works

1. `teleclaude/cron/discovery.py` scans `~/.teleclaude/people/*/teleclaude.yml`
   for entries with `subscriptions.youtube` configured.
2. For each subscriber, calls `sync_youtube_subscriptions()` from
   `teleclaude/tagging/youtube.py`.
3. The tagging module reads the CSV, enriches untagged channels with About page
   descriptions, sends batches to AI agents with the subscriber's allowed tag list,
   validates responses, and falls back to web research for channels tagged `n/a`.
4. Only untagged rows are processed. Tagged rows are never touched unless explicitly
   called with `refresh=True` (not used by the nightly job).

## Files

| File                                                   | Role                                                                                                                                                    |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `jobs/youtube_sync_subscriptions.py`                   | Job wrapper — discovery + iteration over subscribers                                                                                                    |
| `teleclaude/tagging/youtube.py`                        | Canonical library — CSV ops, AI tagging, validation                                                                                                     |
| `teleclaude/cron/discovery.py`                         | Finds subscribers with YouTube config                                                                                                                   |
| `teleclaude/entrypoints/youtube_sync_subscriptions.py` | Standalone CLI with extra features (fetch subs from YouTube API, max limits, debug mode). Shares ~600 lines of duplicate logic with the tagging module. |
| `cron/youtube-sync-subscriptions.py`                   | Legacy wrapper — predates the jobs runner, calls the entrypoint directly. Dead code.                                                                    |

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

- **Legacy `cron/` directory.** Contains `youtube-sync-subscriptions.py` which routes
  to the entrypoint directly, bypassing the jobs runner. Should be deleted once the
  entrypoint is consolidated with the tagging module.
- **Duplicate tagging code.** `teleclaude/tagging/youtube.py` (modular, used by job)
  and `teleclaude/entrypoints/youtube_sync_subscriptions.py` (standalone CLI) share
  ~600 lines of duplicated prompts, validation, and CSV logic. The entrypoint's
  unique contribution is `_call_youtube_helper()` (fetches subscription list from
  YouTube API using cookies). Consolidation: port that feature into the tagging
  module, reduce entrypoint to a thin CLI wrapper.
- **No onboarding skill.** No skill exists to orchestrate per-person setup
  (YouTube subscription fetch, tag configuration, digest opt-in). The initial
  subscription fetch from YouTube currently requires running the entrypoint CLI
  manually with `--fetch-subscriptions`.
