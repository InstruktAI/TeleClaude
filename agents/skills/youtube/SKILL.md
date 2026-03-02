---
name: youtube
description: Search YouTube channels for videos, browse personal watch history and subscriptions, and extract transcripts. Use when user asks to find YouTube videos, get video transcripts, search specific channels, search personal watch history/subscriptions, analyze YouTube content by topic or date range, or needs video URLs and content for research.
---

# YouTube Search, Watch History & Transcripts

## Required reads

- @~/.teleclaude/docs/general/procedure/youtube-research.md

## Purpose

Provide a single interface to search YouTube channels, retrieve watch history and subscriptions, and extract transcripts and metadata for analysis.

## Scope

- Channel-level video search with date filtering and keyword queries.
- Personal watch history search with title, channel, and result limit filters.
- Subscription feed browsing and subscription channel listing.
- Transcript extraction from any video with captions (auto or manual).
- Parallel async searches across multiple channels.
- Character cap management for LLM context windows.
- Circuit breaker: automatic 10-minute backoff if YouTube returns HTTP 429/403/401.

Limitations: HTML parsing may break if YouTube changes page structure. Channel search is channel-scoped, not global. History mode requires a cookies.txt file exported from a logged-in browser session. Watch timestamps are not available (YouTube doesn't expose them); results are ordered most-recent-first.

## Inputs

- **mode**: `search` (search channels), `transcripts` (extract from video IDs), `history` (personal watch history), or `subscriptions` (subscription feed or channel list).
- **For search mode**: `--query` (required), optional `--channels` (comma-separated handles like `@indydevdan`; omit for global search), `--period-days` (default 30), `--end-date`, `--max-videos` (default 5), `--descriptions`, `--no-transcripts`, `--char-cap`.
- **For transcripts mode**: `--ids` (comma-separated YouTube video IDs).
- **For history mode**: optional `--query` (title/channel filter), `--channel` (channel name filter), `--max-videos` (default 5), `--cookies` (path to cookies.txt, default: `~/.config/youtube/cookies.txt`), `--transcripts`, `--char-cap`.
- **For subscriptions mode (feed)**: optional `--channel` (exact channel name), `--max-videos` (default 5), `--cookies` (path to cookies.txt, default: `~/.config/youtube/cookies.txt`), `--transcripts`, `--char-cap`.
- **For subscriptions mode (channel list)**: `--list-channels` only (uses cookies; ignores `--max-videos`).

## Outputs

- **Search mode**: Video metadata (title, URL, channel, duration, views, publish time) plus full transcripts with `[Ns]` timestamp markers.
- **Transcripts mode**: Full transcript text per video ID with timestamps.
- **History mode**: Video metadata (title, URL, channel, duration, views) from personal watch history, most recent first.
- **Subscriptions mode**: Video metadata from your subscription feed, or subscription channel list when `--list-channels` is set.

## Procedure

Follow the YouTube research procedure. Full mode details, flag reference, and circuit breaker handling are in the required reads above.

## Examples

**Channel search**

**Find recent videos on a topic:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode search --channels "@indydevdan,@swyx" --query "AI agents" --period-days 7
```

**Global search (no channels):**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode search --query "AI agents" --period-days 7 --max-videos 10
```

**Deep analysis with descriptions:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode search --channels "@channelname" --query "Python testing" --period-days 90 --max-videos 10 --descriptions
```

**Transcripts**

**Get transcript from a specific video URL (extract ID from URL):**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode transcripts --ids "p9acrso71KU"
```

**Watch history**

**Browse recent watch history (no filter):**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --max-videos 10
```

**Fetch history:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --query "AI agents" --max-videos 20
```

**Filter to a specific channel:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --channel "Anthropic"
```

**Combine query + channel filter:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --channel "ThePrimeagen"
```

**With transcripts (off by default in history mode — opt in):**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --query "AI agents" --max-videos 5 --transcripts
```

**Use a specific cookies.txt file:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --query "python" --cookies ~/cookies.txt
```

**Cap output size for LLM context windows:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --query "tutorial" --max-videos 10 --char-cap 50000
```

**Subscriptions feed**

**Browse recent subscription feed videos:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode subscriptions --max-videos 20
```

**Filter subscription feed by channel name:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode subscriptions --channel "Anthropic" --max-videos 10
```

**List your subscription channels:**

```bash
~/.teleclaude/scripts/helpers/youtube_helper.py --mode subscriptions --list-channels
```
