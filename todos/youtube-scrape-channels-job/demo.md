# Demo: youtube-scrape-channels-job

## Validation

```bash
# 1. Verify the new job module is discoverable
python -c "
import sys; sys.path.insert(0, '.')
from jobs.youtube_scraper import JOB
assert JOB.name == 'youtube_scraper', f'Expected youtube_scraper, got {JOB.name}'
print(f'Job discovered: {JOB.name}')
"
```

```bash
# 2. Verify teleclaude.yml parses with both job entries
python -c "
import sys; sys.path.insert(0, '.')
from teleclaude.config.loader import load_project_config
from pathlib import Path
config = load_project_config(Path('teleclaude.yml'))
assert 'youtube_scraper' in config.jobs, 'youtube_scraper not in jobs config'
assert 'youtube_sync_subscriptions' in config.jobs, 'youtube_sync_subscriptions not in jobs config'
scraper_cfg = config.jobs['youtube_scraper']
tags = getattr(scraper_cfg, 'tags', [])
assert isinstance(tags, list) and len(tags) > 0, f'Expected non-empty tags list, got {tags}'
print(f'youtube_scraper tags: {tags}')
print(f'youtube_sync_subscriptions scheduled: yes')
print('Config validated.')
"
```

```bash
# 3. Verify both jobs appear in cron runner listing
python scripts/cron_runner.py --list 2>/dev/null | grep -E 'youtube_scraper|youtube_sync'
```

```bash
# 4. Run unit tests
pytest tests/unit/test_youtube_scraper.py -v
```

## Guided Presentation

### Step 1: Two independent jobs

Show that `teleclaude.yml` now has two distinct entries: `youtube_scraper`
(channel scraping with tag filter) and `youtube_sync_subscriptions`
(AI tagging). The cron runner lists both with their schedules.

**Observe:** Both jobs appear in `--list` output with `script` type and
their configured schedule times.

**Why it matters:** Previously only one config key existed (`youtube_scraper`)
pointing at the wrong job. The tagging job was effectively unscheduled.

### Step 2: Tag filtering

The scraper job reads `youtube.csv` and filters channels to only those whose
tags intersect with the `tags` list in `teleclaude.yml`. Channels with empty
or `n/a` tags are excluded.

**Observe:** Unit tests prove the intersection logic handles all edge cases:
matching, non-matching, empty filter, partial overlap, and `n/a` exclusion.

**Why it matters:** This is the core contract — the tag filter determines
which channels get scraped.

### Step 3: Channel scraping via existing helpers

For each matching channel, the job uses `youtube_search()` to fetch recent
videos. No new YouTube access code — it reuses the existing channel search
page scraping.

**Observe:** The job returns a `JobResult` with correct channel and video
counts.

**Why it matters:** Reusing existing helpers means no new rate-limit exposure
and consistent behavior with other YouTube features.
