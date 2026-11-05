---
activation_trigger: Use when the human asks about YouTube content — a video, channel, transcript,
  or their watch history.
description: Access YouTube channels, personal watch history, subscriptions, and video
  transcripts for research and information gathering using the youtube_helper script.
visibility: public
---

# YouTube Research — Procedure

## Goal

Retrieve YouTube content (videos, transcripts, watch history, subscriptions) for research and analysis using the `youtube_helper.py` script.

## Preconditions

- `~/.teleclaude/scripts/helpers/youtube_helper.py` is available.
- For `history` and `subscriptions` modes: `~/.config/youtube/cookies.txt` exists (Netscape format, exported from a logged-in browser session using a browser tool such as playwright mcp).
- For `search` and `transcripts` modes: no cookies required.

## Steps

1. **Choose a mode** based on the research goal:
   - `search` — find videos by keyword across channels or globally.
   - `transcripts` — extract full transcripts from specific video IDs.
   - `history` — browse personal watch history with optional filters.
   - `subscriptions` — browse subscription feed or list subscribed channels.

2. **Run the helper** with the selected mode and relevant flags:
   - Execute the global helper path itself: `~/.teleclaude/scripts/helpers/youtube_helper.py`. Its `uv` shebang supplies the dependencies its PEP 723 header declares.
   - Pass `--mode <mode>` and the mode-specific flags; `--help` lists them with their defaults.

3. **Handle rate limits** — if YouTube returns HTTP 429/403/401, the script enforces a 10-minute backoff using `~/.config/youtube/.backoff`. Wait for the backoff to expire before retrying.

4. **Manage context size** — use `--char-cap <N>` to limit total output when results need to fit within an LLM context window.

### Examples

- **Transcribing a YouTube video directly to stdout**:
  `~/.teleclaude/scripts/helpers/youtube_helper.py --mode transcripts --ids <VIDEO_ID>`
- **Searching for videos about "quantum computing", metadata only**:
  `~/.teleclaude/scripts/helpers/youtube_helper.py --mode search --query "quantum computing" --max-videos 10 --no-transcripts`
- **Listing personal watch history from the last 7 days**:
  `~/.teleclaude/scripts/helpers/youtube_helper.py --mode history --period-days 7`
- **Listing subscribed channels**:
  `~/.teleclaude/scripts/helpers/youtube_helper.py --mode subscriptions --list-channels`

## Outputs

- **Search mode**: video metadata (title, URL, channel, duration, views, publish time) plus full transcripts with `[Ns]` timestamp markers.
- **Transcripts mode**: full transcript text per video ID with timestamps.
- **History mode**: video metadata from personal watch history, most recent first.
- **Subscriptions mode**: video metadata from subscription feed, or channel list when `--list-channels` is set.

## Recovery

- If the helper fails with `ModuleNotFoundError`, it was started through a bare interpreter such as `python3`; execute the helper path itself.
- If cookies.txt is missing on this computer, history and subscriptions are unavailable here; `search` and `transcripts` still work, and a video's ID or URL from the human goes straight to `transcripts`.
- If cookies.txt is missing or expired, export fresh cookies from a logged-in browser session and place them at `~/.config/youtube/cookies.txt`.
- If the backoff file is stale (previous error more than 10 minutes ago), delete `~/.config/youtube/.backoff` and retry.
- If channel search returns no results, try global search (omit `--channels`).
- If HTML parsing fails (YouTube page structure changed), report the issue — this requires a script update.
