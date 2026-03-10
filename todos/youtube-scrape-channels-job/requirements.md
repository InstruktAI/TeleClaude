# Requirements: youtube-scrape-channels-job

## Goal

Repurpose the `youtube_scraper` job entry in `teleclaude.yml` so that it uses
its configured tag filter to select channels from subscribers' `youtube.csv`
data and perform channel scraping, rather than invoking the existing
subscription-tagging flow.

The existing subscription-tagging behavior remains intact and independently
schedulable. `[inferred]`

## Problem Statement

The `youtube_scraper` job config in `teleclaude.yml` currently invokes the
subscription-tagging flow rather than a channel-scraping flow. That means the
configured `tags` filter does not control which subscribed channels are scraped,
and the intended `youtube_scraper` behavior does not exist.

## In Scope

1. **Tag-filtered channel selection** — The job reads each subscriber's
   `youtube.csv`, selects only rows whose tags match the `tags` list configured
   on the job entry in `teleclaude.yml`, and operates on that subset.

2. **Channel scraping** — For each selected channel, use the existing YouTube
   search/scraping capability to fetch recent videos. `[inferred]` The output is
   a structured collection of recent video metadata (title, URL, channel,
   publish time, duration) per channel. `[inferred]`

3. **Job registration** — The job is registered in `teleclaude.yml` under a
   config key (currently `youtube_scraper`) with a `tags` field for channel
   filtering and a schedule.

4. **Existing tagging job independence** — The existing subscription-tagging
   behavior continues to work after `youtube_scraper` is repointed to the new
   behavior. `[inferred]`

5. **Per-subscriber operation** — Like the tagging job, the scraper discovers
   subscribers through the existing YouTube-subscriber discovery flow and
   processes each subscriber's `youtube.csv` independently. `[inferred]`

## Out of Scope

- Transcript extraction (can be added later as an option).
- Content ingestion into downstream systems (digests, knowledge base). `[inferred]`
- Changes to the tagging pipeline logic.
- Changes to the youtube.csv schema or the tag taxonomy.
- Changes to the cron runner engine or job discovery mechanism.

## Success Criteria

- [ ] `youtube_scraper` is backed by a distinct scheduled job implementation
      instead of the existing subscription-tagging implementation.
- [ ] The job reads subscriber youtube.csv files and filters rows to those
      whose tags intersect with the job config's `tags` list.
- [ ] For each matching channel, recent videos are fetched via the existing
      YouTube search/scraping capability. `[inferred]`
- [ ] The job reports accurate counts of channels evaluated and videos found.
      `[inferred]`
- [ ] The `teleclaude.yml` `youtube_scraper` entry accepts a `tags` filter list.
- [ ] The existing subscription-tagging behavior remains functional and
      independently schedulable. `[inferred]`
- [ ] If supporting `jobs.youtube_scraper.tags` expands the documented config
      surface, the TeleClaude config spec and sample config are updated in the
      same change. `[inferred]`
- [ ] Pre-commit hooks pass (tests, lint, type-check).

## Constraints

- Must follow the existing script-job contract defined by the jobs runner.
- Must use existing YouTube search/scraping helpers rather than reimplementing
  YouTube access logic.
- The job must not require the daemon to be running, consistent with existing
  script jobs. `[inferred]`
- Tag matching is intersection-based: a channel matches if any of its tags
  appear in the job's `tags` list.

## Risks

- **Config collision**: The `youtube_scraper` key currently points to the
  tagging job implementation. Changing it to point to the new scraper may
  remove the existing tagging behavior unless that behavior keeps an independent
  registration path. `[inferred]`
- **YouTube rate limiting**: Scraping multiple channels may trigger backoff.
  Existing helper backoff behavior should be respected. `[inferred]`

## Verification

- Unit test: tag filtering logic (channels with matching tags selected,
  non-matching excluded, empty tags handled).
- Unit test: job result/reporting includes correct counts for channels evaluated
  and videos found. `[inferred]`
- Integration: `teleclaude.yml` config with `jobs.youtube_scraper.tags` parses
  without error.
- Integration or contract test: repointing `youtube_scraper` does not remove
  separate scheduling of the existing subscription-tagging behavior. `[inferred]`
- Documentation check: if `jobs.youtube_scraper.tags` is treated as a new config
  field, the TeleClaude config spec and sample config are updated in the same
  change. `[inferred]`
- Pre-commit hooks pass.
