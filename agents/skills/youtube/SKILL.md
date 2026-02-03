---
name: youtube
description: Search YouTube channels for videos, browse personal watch history, and extract transcripts. Use when user asks to find YouTube videos, get video transcripts, search specific channels, search personal watch history, analyze YouTube content by topic or date range, or needs video URLs and content for research.
---

# YouTube Search, Watch History & Transcripts

Search YouTube channels for videos, browse personal watch history via InnerTube API, and extract full transcripts with timestamps for analysis.

## Purpose

Provide agents with the ability to search YouTube channels for videos, query personal watch history, and extract full transcripts with timestamps. Channel search uses HTML parsing (no API key). Watch history uses YouTube's InnerTube browse API with exported cookies for live, authenticated access. The helper script uses PEP 723 inline dependencies and runs via `uv run`.

## Scope

- Channel-level video search with date filtering and keyword queries.
- Personal watch history search with title, channel, and result limit filters.
- Transcript extraction from any video with captions (auto or manual).
- Parallel async searches across multiple channels.
- Character cap management for LLM context windows.
- Circuit breaker: automatic 10-minute backoff if YouTube returns HTTP 429/403/401.

Limitations: HTML parsing may break if YouTube changes page structure. Channel search is channel-scoped, not global. History mode requires a cookies.txt file exported from a logged-in browser session. Watch timestamps are not available (YouTube doesn't expose them); results are ordered most-recent-first.

## Inputs

- **mode**: `search` (search channels), `transcripts` (extract from video IDs), or `history` (personal watch history).
- **For search mode**: `--channels` (comma-separated handles like `@indydevdan`), optional `--query`, `--period-days` (default 30), `--end-date`, `--max-videos` (default 5), `--descriptions`, `--no-transcripts`, `--char-cap`.
- **For transcripts mode**: `--ids` (comma-separated YouTube video IDs).
- **For history mode**: optional `--query` (title/channel filter), `--channel` (channel name filter), `--max-videos` (default 5), `--cookies` (path to cookies.txt, default: `~/.config/youtube/cookies.txt`), `--transcripts`, `--char-cap`.

## Outputs

- **Search mode**: Video metadata (title, URL, channel, duration, views, publish time) plus full transcripts with `[Ns]` timestamp markers.
- **Transcripts mode**: Full transcript text per video ID with timestamps.
- **History mode**: Video metadata (title, URL, channel, duration, views) from personal watch history, most recent first.

## Procedure

1. Export YouTube cookies to `~/.config/youtube/cookies.txt` in Netscape format (use a browser extension like "Get cookies.txt LOCALLY"). The helper script auto-detects this path.
2. Run the helper script via `uv run` from the skill's `scripts/` directory.
3. Choose a mode: `search`, `transcripts`, or `history` and pass the relevant flags.
4. Circuit breaker: if YouTube returns HTTP 429/403/401, the script enforces a 10-minute backoff using `~/.config/youtube/.backoff`.

Channel handles must use `@` prefix. Multiple channels are comma-separated. Timestamps in transcripts use `[123s]` format. Use `--char-cap` to limit total output size for LLM context management.

## Examples

**Channel search**

**Find recent videos on a topic:**

```bash
uv run scripts/youtube_helper.py --mode search --channels "@indydevdan,@swyx" --query "AI agents" --period-days 7
```

**Deep analysis with descriptions:**

```bash
uv run scripts/youtube_helper.py --mode search --channels "@channelname" --query "Python testing" --period-days 90 --max-videos 10 --descriptions
```

**Transcripts**

**Get transcript from a specific video URL (extract ID from URL):**

```bash
uv run scripts/youtube_helper.py --mode transcripts --ids "p9acrso71KU"
```

**Watch history**

**Browse recent watch history (no filter):**

```bash
uv run scripts/youtube_helper.py --mode history --max-videos 10
```

**Search by keyword (matches title + channel name, case-insensitive):**

```bash
uv run scripts/youtube_helper.py --mode history --query "AI agents" --max-videos 20
```

**Filter to a specific channel:**

```bash
uv run scripts/youtube_helper.py --mode history --channel "Anthropic"
```

**Combine query + channel filter:**

```bash
uv run scripts/youtube_helper.py --mode history --query "coding" --channel "ThePrimeagen"
```

**With transcripts (off by default in history mode — opt in):**

```bash
uv run scripts/youtube_helper.py --mode history --query "AI agents" --max-videos 5 --transcripts
```

**Use a specific cookies.txt file:**

```bash
uv run scripts/youtube_helper.py --mode history --query "python" --cookies ~/cookies.txt
```

**Cap output size for LLM context windows:**

```bash
uv run scripts/youtube_helper.py --mode history --query "tutorial" --max-videos 10 --char-cap 50000
```
