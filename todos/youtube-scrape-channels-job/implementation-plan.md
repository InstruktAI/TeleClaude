# Implementation Plan: youtube-scrape-channels-job

## Overview

Create a new `youtube_scraper` script job that reads subscriber `youtube.csv`
files, filters channels whose tags match the job's configured `tags` list, and
fetches recent videos for each matching channel using the existing YouTube
helper.

The existing `youtube_sync_subscriptions` tagging job is untouched. It gains
its own schedule entry so it can be scheduled independently.

## Task 1: Create `jobs/youtube_scraper.py`

### What

A new `YouTubeScraperJob` class in `jobs/youtube_scraper.py` that:

1. Loads its own `tags` config from `teleclaude.yml` via
   `load_project_config(...)` → `config.jobs["youtube_scraper"]`.
2. Calls `discover_youtube_subscribers()` to find all subscribers with
   YouTube subscriptions configured.
3. For each subscriber, reads their `youtube.csv` via `read_csv()` from
   `teleclaude/tagging/youtube.py`.
4. Filters rows to those whose `tags` field intersects with the job config's
   `tags` list (intersection-based matching per requirements).
5. For each matching channel, fetches recent videos using
   `youtube_search(channels=handle, query=channel_name, get_transcripts=False, ...)`
   from `teleclaude/helpers/youtube_helper.py` so the scraper stays within the
   metadata-only scope.
6. Collects structured results (channel name, video title, URL, publish time,
   duration) and returns a `JobResult` with accurate counts.

### Why

The `youtube_scraper` config key in `teleclaude.yml` currently points at the
tagging job's script, which is the wrong behavior. This task creates the
intended implementation: a job that uses tag-filtered channel selection to
drive channel scraping, not tagging.

The job follows the existing `Job`/`JobResult` contract from `jobs/base.py`.
It reuses `discover_youtube_subscribers()`, `read_csv()`, and
`youtube_search()` — no new YouTube access logic.

### Key design decisions

- **Tag access**: The `JobScheduleConfig` schema uses `extra="allow"`, so
  `tags` is stored as an extra field. The job reads it via
  `getattr(job_config, "tags", [])`. No schema change needed.

- **Channel identification**: The CSV has `channel_name` and `handle` fields.
  `youtube_search` accepts channel handles (e.g., `@channelname`). The job
  passes handles from matching CSV rows.

- **Search query**: `youtube_search` requires a non-empty `query` argument.
  The job uses the channel name as the query with a configurable
  `period_days` window (default 7). It also disables transcript extraction
  (`get_transcripts=False`) because transcript fetching is explicitly out of
  scope for this todo. This reuses the existing channel search page scraping
  without introducing new YouTube access patterns.

- **Output**: The job logs structured results per subscriber (channels
  evaluated, videos found). It does not persist video data to disk — that is
  a future concern (out of scope per requirements).

- **Tag matching**: A channel matches if `set(channel_tags) & set(job_tags)`
  is non-empty. Channels with empty tags or `n/a` tags are excluded.

### Referenced files

- `jobs/youtube_scraper.py` (create)
- `jobs/base.py` (read — `Job`, `JobResult` contract)
- `teleclaude/cron/discovery.py` (read — `discover_youtube_subscribers`,
  `Subscriber`)
- `teleclaude/tagging/youtube.py` (read — `read_csv`, `ChannelRow`)
- `teleclaude/helpers/youtube_helper.py` (read — `youtube_search`, `Video`)
- `teleclaude/config/loader.py` (read — `load_project_config`)
- `teleclaude/config/schema.py` (read — `JobScheduleConfig`, `ProjectConfig`)

### Verification

- Unit test: tag filtering selects only channels whose tags intersect the
  job's `tags` list. Edge cases: empty tags list (nothing selected), channel
  with no tags (excluded), channel with `n/a` tags (excluded), partial
  overlap (included).
- Unit test: `JobResult` reports correct counts for channels evaluated and
  videos found.
- Pre-commit hooks pass.

---

## Task 2: Update `teleclaude.yml` job wiring

### What

1. Update the `youtube_scraper` entry: add `category: system`, replace
   `script: jobs/youtube_sync_subscriptions.py` with
   `script: jobs/youtube_scraper.py`, and keep the `tags` filter list on the
   same entry.
2. Add a new `youtube_sync_subscriptions` entry for the tagging job so it
   has its own `category: system`, schedule, and
   `script: jobs/youtube_sync_subscriptions.py`.

Config after change:

```yaml
jobs:
  youtube_scraper:
    category: system
    when:
      at: '06:00'
    script: jobs/youtube_scraper.py
    tags:
      - ai
      - devtools

  youtube_sync_subscriptions:
    category: system
    when:
      at: '06:00'
    script: jobs/youtube_sync_subscriptions.py
```

### Why

Currently `youtube_scraper` points to the tagging job script, and the tagging
job has no schedule entry matching its `name` field (`youtube_sync_subscriptions`).
The cron runner matches discovered Python jobs by `JOB.name` against the
`jobs:` mapping, so the tagging job needs its own config key to be addressable.

These entries also need `category: system`. In the current runner,
`category: subscription` jobs are only considered due when a person has an
enabled `JobSubscription` for that job. This todo is explicitly about
repository-owned schedules in `teleclaude.yml`, so both jobs must be
system-category jobs or their `when:` schedule will not make them run.

After this change:
- `youtube_scraper` matches `YouTubeScraperJob.name` → scheduled correctly.
- `youtube_sync_subscriptions` matches `YouTubeSyncJob.name` → scheduled
  correctly.
- Both jobs run independently at their configured times.

The `script:` field is not just metadata: it selects direct script execution
mode in the runner. The config key still needs to match `JOB.name`, but the
`script:` value must remain accurate because it is the execution-mode
discriminator for these non-agent jobs.

The `tags` list values (`ai`, `devtools`) are placeholders — the user
configures the actual tags they want to filter by.

### Referenced files

- `teleclaude.yml` (modify)

### Verification

- `teleclaude.yml` parses without error via `load_project_config()`.
- Targeted contract test covers the corrected runner wiring: both
  `youtube_scraper` and `youtube_sync_subscriptions` are `category: system`,
  so project-level schedules are evaluated without requiring per-person
  `JobSubscription` entries.
- Pre-commit hooks pass.

---

## Task 3: Write unit tests

### What

Add `tests/unit/test_youtube_scraper.py` with tests for:

1. **Tag filtering logic**: Given a list of `ChannelRow` objects and a set of
   filter tags, verify that only rows with intersecting tags are selected.
   - Matching tags: channel with `"ai,devtools"` matches filter `["ai"]`.
   - No match: channel with `"gaming"` does not match filter `["ai"]`.
   - Empty filter tags: no channels selected.
   - Channel with empty/`n/a` tags: excluded.
   - Partial overlap: channel with `"ai,gaming"` matches filter `["ai"]`.

2. **Job result reporting**: Mock `discover_youtube_subscribers` and
   `youtube_search` to verify the job returns correct counts in `JobResult`
   (channels evaluated, videos found via `items_processed`).

3. **Config access**: The job correctly reads `tags` from a
   `JobScheduleConfig` with extra fields via `extra="allow"`.

4. **Runner schedule contract**: The project config registers both jobs as
   `category: system`, and the runner treats them as independently schedulable
   from `teleclaude.yml` without requiring per-person `JobSubscription`
   entries.

### Why

The tag filtering logic is the core behavioral contract. Without tests,
regressions in channel selection silently break the job. The `JobResult`
counts test ensures the reporting contract is met. Config access tests
verify the `extra="allow"` mechanism works as expected.

### Referenced files

- `tests/unit/test_youtube_scraper.py` (create)
- `tests/unit/test_cron_runner_subscriptions.py` (modify)
- `jobs/youtube_scraper.py` (read — test target)
- `teleclaude/tagging/youtube.py` (read — `ChannelRow`)

### Verification

- All new tests pass:
  `pytest tests/unit/test_youtube_scraper.py tests/unit/test_cron_runner_subscriptions.py`.
- Pre-commit hooks pass.

---

## Task 4: Update config/docs/demo artifacts

### What

Update the affected artifacts so they describe the final wiring consistently:

1. `docs/project/spec/teleclaude-config.md` documents the
   `jobs.youtube_scraper.tags` filter and the system-category project job
   wiring used here.
2. `teleclaude.sample.yml` shows the corrected `youtube_scraper` and
   `youtube_sync_subscriptions` entries.
3. `docs/project/spec/jobs/youtube-sync-subscriptions.md` is corrected to
   describe the existing script-job wiring accurately, including its own
   `youtube_sync_subscriptions` config key rather than the shared
   `youtube_scraper` entry.
4. `docs/project/design/architecture/jobs-runner.md` updates the runner
   examples and execution-mode description that currently imply
   `youtube_sync_subscriptions` is an agent job.
5. `todos/youtube-scrape-channels-job/demo.md` validates the corrected wiring
   and shows both jobs as independently scheduled script jobs.

### Why

The requirements explicitly call out config-surface updates when the
`jobs.youtube_scraper.tags` field becomes part of the supported workflow.
Without a config spec update, runner-design update, sample config update, and
demo refresh, the builder would satisfy the code path while still leaving
repository docs inconsistent about how these jobs are wired and scheduled.

### Referenced files

- `docs/project/spec/teleclaude-config.md` (modify)
- `teleclaude.sample.yml` (modify)
- `docs/project/spec/jobs/youtube-sync-subscriptions.md` (modify)
- `docs/project/design/architecture/jobs-runner.md` (modify)
- `todos/youtube-scrape-channels-job/demo.md` (modify)

### Verification

- `telec sync` validates the updated snippet schema.
- The demo commands and expected observations match the final job wiring.
- Pre-commit hooks pass.

---

## Traceability

| Requirement | Tasks |
|---|---|
| Tag-filtered channel selection | 1, 3 |
| Channel scraping | 1 |
| Job registration | 2 |
| Existing tagging job independence | 2, 4 |
| Per-subscriber operation | 1 |
| Accurate counts reporting | 1, 3 |
| Config surface documentation | 2, 4 |
| Pre-commit hooks pass | 1, 2, 3, 4 |
