---
description: 'Access YouTube channels, personal watch history, subscriptions, and video transcripts for research and information gathering using the youtube_helper script.'
id: 'general/procedure/youtube-research'
scope: 'global'
type: 'procedure'
---

# YouTube Research — Procedure

## Goal

Retrieve YouTube content (videos, transcripts, watch history, subscriptions) for research and analysis using the `youtube_helper.py` script.

## Preconditions

- `~/.teleclaude/scripts/helpers/youtube_helper.py` is available.
- For `history` and `subscriptions` modes: `~/.config/youtube/cookies.txt` exists (Netscape format, exported from a logged-in browser session using a browser extension such as "Get cookies.txt LOCALLY").
- For `search` and `transcripts` modes: no cookies required.

## Steps

1. **Choose a mode** based on the research goal:
   - `search` — find videos by keyword across channels or globally.
   - `transcripts` — extract full transcripts from specific video IDs.
   - `history` — browse personal watch history with optional filters.
   - `subscriptions` — browse subscription feed or list subscribed channels.

2. **Run the helper** with the selected mode and relevant flags:
   - Always use the global helper path: `~/.teleclaude/scripts/helpers/youtube_helper.py`
   - Pass `--mode <mode>` and the mode-specific flags (see Inputs in the skill wrapper).

3. **Handle rate limits** — if YouTube returns HTTP 429/403/401, the script enforces a 10-minute backoff using `~/.config/youtube/.backoff`. Wait for the backoff to expire before retrying.

4. **Manage context size** — use `--char-cap <N>` to limit total output when results need to fit within an LLM context window.

## Outputs

- **Search mode**: video metadata (title, URL, channel, duration, views, publish time) plus full transcripts with `[Ns]` timestamp markers.
- **Transcripts mode**: full transcript text per video ID with timestamps.
- **History mode**: video metadata from personal watch history, most recent first.
- **Subscriptions mode**: video metadata from subscription feed, or channel list when `--list-channels` is set.

## Recovery

- If cookies.txt is missing or expired, export fresh cookies from a logged-in browser session and place them at `~/.config/youtube/cookies.txt`.
- If the backoff file is stale (previous error more than 10 minutes ago), delete `~/.config/youtube/.backoff` and retry.
- If channel search returns no results, try global search (omit `--channels`).
- If HTML parsing fails (YouTube page structure changed), report the issue — this requires a script update.
