"""YouTube search, watch history, and transcript extraction helper.

Searches YouTube channels for videos, queries personal watch history
via InnerTube API, and extracts transcripts.
"""

import argparse
import asyncio
import json
import time
import urllib.parse
from collections.abc import Coroutine
from datetime import datetime, timedelta
from typing import Any, cast

import dateparser  # pylint: disable=import-error
from aiohttp import ClientSession
from youtube_transcript_api import YouTubeTranscriptApi  # pylint: disable=import-error

# Re-export models for backward-compatible imports
from teleclaude.helpers.youtube_helper._models import (
    HistoryEntry,
    HtmlVideoInfo,
    LockupViewModel,
    RichGridItem,
    SubscriptionChannel,
    SubscriptionEntry,
    Transcript,
    Video,
    VideoRenderer,
    VideoTranscript,
    YouTubeBackoffError,
)

# Re-export parsers for backward-compatible imports
from teleclaude.helpers.youtube_helper._parsers import (
    _extract_continuation_token,
    _extract_lockup_publish_time,
    _extract_richgrid_continuation,
    _extract_yt_initial_data,
    _fetch_channel_about_description,
    _find_about_description,
    _get_richgrid_contents,
    _get_sections,
    _parse_history_entries,
    _parse_html_list,
    _parse_html_video,
    _parse_lockup_view_model,
    _parse_subscription_channels,
    _parse_subscription_entries,
    _parse_video_renderer,
)

# Re-export utilities for backward-compatible imports
from teleclaude.helpers.youtube_helper._utils import (
    _INNERTUBE_API_URL,
    _INNERTUBE_CONTEXT,
    BACKOFF_FILE,
    BACKOFF_SECONDS,
    _build_innertube_headers,
    _check_backoff,
    _cookies_to_header,
    _load_cookies_txt,
    _refresh_cookies_if_needed,
    _safe_get,
    _safe_get_dict,
    _safe_get_list,
    _safe_get_str,
    _trigger_backoff,
    log,
)

__all__ = [
    # Models
    "BACKOFF_FILE",
    "BACKOFF_SECONDS",
    # Utils
    "_INNERTUBE_API_URL",
    "_INNERTUBE_CONTEXT",
    "HistoryEntry",
    "HtmlVideoInfo",
    "LockupViewModel",
    "RichGridItem",
    "SubscriptionChannel",
    "SubscriptionEntry",
    "Transcript",
    "Video",
    "VideoRenderer",
    "VideoTranscript",
    "YouTubeBackoffError",
    "_build_innertube_headers",
    "_check_backoff",
    "_cookies_to_header",
    # Parsers
    "_extract_continuation_token",
    "_extract_lockup_publish_time",
    "_extract_richgrid_continuation",
    "_extract_yt_initial_data",
    "_fetch_channel_about_description",
    "_find_about_description",
    "_get_richgrid_contents",
    "_get_sections",
    "_load_cookies_txt",
    "_parse_history_entries",
    "_parse_html_list",
    "_parse_html_video",
    "_parse_lockup_view_model",
    "_parse_subscription_channels",
    "_parse_subscription_entries",
    "_parse_video_renderer",
    "_refresh_cookies_if_needed",
    "_safe_get",
    "_safe_get_dict",
    "_safe_get_list",
    "_safe_get_str",
    "_trigger_backoff",
    "log",
    # Public functions
    "main",
    "youtube_history",
    "youtube_search",
    "youtube_subscriptions",
    "youtube_transcripts",
]


async def youtube_history(
    query: str | None = None,
    channel: str | None = None,
    max_results: int = 20,
    cookies_file: str | None = None,
    get_transcripts: bool = False,
    char_cap: int | None = None,
    _retry_after_refresh: bool = False,
) -> list[Video]:
    """Fetch personal YouTube watch history via InnerTube browse API.

    Args:
        query: Filter results by title (case-insensitive substring).
        channel: Filter to a specific channel name (case-insensitive exact match).
        max_results: Maximum videos to return.
        cookies_file: Path to a Netscape cookies.txt file (required for auth).
        get_transcripts: Fetch transcripts for matched videos.
        char_cap: Cap total output characters.
        _retry_after_refresh: Internal flag - if True, this is already a retry after cookie refresh.

    Returns:
        List of Video objects from watch history, most recent first.
    """
    _check_backoff()

    headers, cookies_file = _build_innertube_headers(cookies_file)

    # Fetch enough pages to satisfy filtering
    fetch_limit = max_results * 5 if (query or channel) else max_results
    log.info("Fetching watch history via InnerTube: target=%d, cookies=%s", fetch_limit, cookies_file)

    all_entries: list[HistoryEntry] = []
    continuation: str | None = None

    async with ClientSession() as session:
        for page in range(20):  # safety cap on pages
            body: dict[str, object] = {"context": _INNERTUBE_CONTEXT}  # guard: loose-dict - InnerTube API request
            if continuation:
                body["continuation"] = continuation
            else:
                body["browseId"] = "FEhistory"

            resp = await session.post(_INNERTUBE_API_URL, headers=headers, json=body)

            # Circuit breaker on HTTP errors
            if resp.status in (429, 403, 401):
                reason = f"HTTP {resp.status} from InnerTube browse"
                _trigger_backoff(reason)
                raise YouTubeBackoffError(
                    f"YouTube rejected the request ({reason}). Backing off for {BACKOFF_SECONDS}s."
                )
            if resp.status != 200:
                text = await resp.text()
                log.error("InnerTube browse failed (HTTP %d): %s", resp.status, text[:300])
                raise RuntimeError(f"InnerTube browse failed: HTTP {resp.status}")

            data = await resp.json()

            # Check if we're actually logged in
            logged_in = False
            for stp in data.get("responseContext", {}).get("serviceTrackingParams", []):
                for kv in stp.get("params", []):
                    if kv.get("key") == "logged_in" and kv.get("value") == "1":
                        logged_in = True
            if not logged_in and page == 0:
                # Single auto-refresh attempt - no retry loop
                if not _retry_after_refresh and _refresh_cookies_if_needed():
                    log.info("Cookies refreshed, retrying history fetch once...")
                    return await youtube_history(
                        query=query,
                        channel=channel,
                        max_results=max_results,
                        cookies_file=None,  # Force reload from default path
                        get_transcripts=get_transcripts,
                        char_cap=char_cap,
                        _retry_after_refresh=True,  # Prevent infinite recursion
                    )
                raise RuntimeError(
                    "YouTube did not recognize the session as logged in. Run: python -m teleclaude.helpers.youtube.refresh_cookies --setup"
                )

            entries = _parse_history_entries(data)
            all_entries.extend(entries)
            log.info("Page %d: got %d entries (total %d)", page, len(entries), len(all_entries))

            if len(all_entries) >= fetch_limit:
                break

            continuation = _extract_continuation_token(data)
            if not continuation:
                break

    log.info("InnerTube returned %d history entries total", len(all_entries))

    # Map to Video models
    videos: list[Video] = []
    for e in all_entries:
        vid = Video(
            id=e["id"],
            title=e["title"],
            short_desc="",
            channel=e["channel"],
            duration=e["duration"],
            views=e["views"],
            publish_time="",
            url_suffix=f"/watch?v={e['id']}",
        )
        videos.append(vid)

    # Client-side filtering
    if query:
        q = query.lower()
        videos = [v for v in videos if q in v.title.lower() or q in v.channel.lower()]

    if channel:
        ch = channel.lower()
        videos = [v for v in videos if ch in v.channel.lower()]

    videos = videos[:max_results]

    # Optional transcript fetch
    if get_transcripts:
        for vid in videos:
            vid.transcript = _get_video_transcript(vid.id)

    if char_cap:
        videos = _filter_by_char_cap(videos, char_cap)

    log.info("History search returned %d results", len(videos))
    return videos


async def youtube_subscriptions(
    query: str | None = None,
    channel: str | None = None,
    max_results: int = 20,
    cookies_file: str | None = None,
    get_transcripts: bool = False,
    char_cap: int | None = None,
    list_channels: bool = False,
    max_channels: int | None = None,
    get_about_descriptions: bool = False,
) -> list[Video] | list[SubscriptionChannel]:
    """Fetch subscription feed or channel list via InnerTube browse API.

    Args:
        query: Filter results by title or channel name (case-insensitive substring).
        channel: Filter to a specific channel name (case-insensitive substring).
        max_results: Maximum videos/channels to return.
        cookies_file: Path to a Netscape cookies.txt file (required for auth).
        get_transcripts: Fetch transcripts for matched videos (feed mode).
        char_cap: Cap total output characters.
        list_channels: If True, return subscriptions channel list (FEchannels).
        max_channels: Optional limit for subscription channel list size.

    Returns:
        List of Video objects from subscription feed or SubscriptionChannel entries.
    """
    _check_backoff()

    headers, cookies_file = _build_innertube_headers(cookies_file)

    async with ClientSession() as session:
        if list_channels:
            body: dict[str, object] = {  # guard: loose-dict - InnerTube API request
                "context": _INNERTUBE_CONTEXT,
                "browseId": "FEchannels",
            }
            resp = await session.post(_INNERTUBE_API_URL, headers=headers, json=body)
            if resp.status in (429, 403, 401):
                reason = f"HTTP {resp.status} from InnerTube browse"
                _trigger_backoff(reason)
                raise YouTubeBackoffError(
                    f"YouTube rejected the request ({reason}). Backing off for {BACKOFF_SECONDS}s."
                )
            if resp.status != 200:
                text = await resp.text()
                log.error("InnerTube browse failed (HTTP %d): %s", resp.status, text[:300])
                raise RuntimeError(f"InnerTube browse failed: HTTP {resp.status}")

            data = await resp.json()
            channels = _parse_subscription_channels(data)
            if get_about_descriptions:
                for ch in channels:
                    about = await _fetch_channel_about_description(session, ch)
                    if about:
                        ch.description = about
            if max_channels is not None:
                return channels[:max_channels]
            return channels

        # Subscription feed (videos)
        fetch_limit = max_results * 5 if channel else max_results
        log.info("Fetching subscriptions feed via InnerTube: target=%d, cookies=%s", fetch_limit, cookies_file)

        all_entries: list[SubscriptionEntry] = []
        continuation: str | None = None

        for _page in range(10):  # safety cap
            body: dict[str, object] = {"context": _INNERTUBE_CONTEXT}  # guard: loose-dict - InnerTube API request
            if continuation:
                body["continuation"] = continuation
            else:
                body["browseId"] = "FEsubscriptions"

            resp = await session.post(_INNERTUBE_API_URL, headers=headers, json=body)
            if resp.status in (429, 403, 401):
                reason = f"HTTP {resp.status} from InnerTube browse"
                _trigger_backoff(reason)
                raise YouTubeBackoffError(
                    f"YouTube rejected the request ({reason}). Backing off for {BACKOFF_SECONDS}s."
                )
            if resp.status != 200:
                text = await resp.text()
                log.error("InnerTube browse failed (HTTP %d): %s", resp.status, text[:300])
                raise RuntimeError(f"InnerTube browse failed: HTTP {resp.status}")

            data = await resp.json()
            entries = _parse_subscription_entries(data)
            all_entries.extend(entries)

            if len(all_entries) >= fetch_limit:
                break

            continuation = _extract_richgrid_continuation(_get_richgrid_contents(data))
            if not continuation:
                break

        videos: list[Video] = []
        for e in all_entries:
            vid = Video(
                id=e.get("id", ""),
                title=e.get("title", ""),
                short_desc="",
                channel=e.get("channel", ""),
                duration=e.get("duration", ""),
                views=e.get("views", ""),
                publish_time=e.get("publish_time", ""),
                url_suffix=f"/watch?v={e.get('id', '')}",
            )
            videos.append(vid)

        if channel:
            ch = channel.lower()  # type: ignore[assignment]
            videos = [v for v in videos if v.channel.lower() == ch]  # type: ignore[comparison-overlap]

        videos = videos[:max_results]

        if get_transcripts:
            for vid in videos:
                vid.transcript = _get_video_transcript(vid.id)

        if char_cap:
            videos = _filter_by_char_cap(videos, char_cap)

        return videos


def _get_since_date(period_days: int, end_date: str) -> tuple[str, str, str]:
    """Calculate start date from period and end date."""
    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d")
    else:
        end = datetime.now()

    start = end - timedelta(days=period_days)
    return (
        str(start.year),
        str(start.month).zfill(2),
        str(start.day).zfill(2),
    )


def _build_youtube_search_url(query: str | None, period_days: int, end_date: str) -> str:
    """Build YouTube search query URL with date filters."""
    year, month, day = _get_since_date(period_days, end_date)
    query_str = f"{query} " if query else ""
    before = f"{' ' if query else ''}before:{end_date} " if end_date else ""
    return urllib.parse.quote_plus(f"{query_str}{before}after:{year}-{month}-{day}")


def _filter_channels(channels: list[str]) -> list[str]:
    """Validate and normalize channel handles."""
    return [ch for ch in channels if ch and ch.lower() != "n/a"]


def _create_channel_tasks(
    channels_arr: list[str],
    encoded_search: str,
    max_videos_per_channel: int,
    get_descriptions: bool,
    get_transcripts: bool,
) -> list[Coroutine[Any, Any, list[Video]]]:
    """Create async tasks for fetching videos from each channel."""
    tasks = []
    for channel in channels_arr:
        if channel == "n/a":
            continue
        url = f"https://www.youtube.com/{channel}/search?hl=en&query={encoded_search}"
        tasks.append(
            _get_channel_videos(
                channel=channel,
                url=url,
                max_videos_per_channel=max_videos_per_channel,
                get_descriptions=get_descriptions,
                get_transcripts=get_transcripts,
            )
        )
    return tasks


def _process_video_results(results: list[list[Video]], query: str | None, char_cap: int | None) -> list[Video]:
    """Process and sort video results."""
    res: list[Video] = []
    for videos in results:
        if not query:
            videos.sort(key=_sort_by_publish_time)
            videos = videos[::-1]
        res.extend(videos)
    if char_cap:
        res = _filter_by_char_cap(res, char_cap)
    return res


async def youtube_search(
    channels: str | None,
    end_date: str = "",
    query: str | None = None,
    period_days: int = 3,
    max_videos_per_channel: int = 3,
    get_descriptions: bool = False,
    get_transcripts: bool = True,
    char_cap: int | None = None,
) -> list[Video]:
    """Search YouTube for videos with optional transcript extraction.

    Args:
        channels: Optional comma-separated list of channel handles (e.g., "@indydevdan,@someotherchannel").
            If omitted, runs a global search.
        end_date: End date in YYYY-MM-DD format (defaults to today)
        query: Search query
        period_days: Number of days back to search
        max_videos_per_channel: Maximum videos to return per channel
        get_descriptions: Extract full video descriptions
        get_transcripts: Extract video transcripts
        char_cap: Maximum total characters in results (for LLM context management)

    Returns:
        List of Video objects with metadata and optional transcripts
    """
    if not query:
        raise ValueError("No query specified")

    encoded_search = _build_youtube_search_url(query, period_days, end_date)

    if not channels:
        url = f"https://www.youtube.com/results?search_query={encoded_search}"
        videos = await _get_channel_videos(
            channel="global",
            url=url,
            max_videos_per_channel=max_videos_per_channel,
            get_descriptions=get_descriptions,
            get_transcripts=get_transcripts,
        )
        if char_cap:
            videos = _filter_by_char_cap(videos, char_cap)
        return videos

    channels_arr = _filter_channels(["@" + channel.replace("@", "") for channel in channels.lower().split(",")])
    if len(channels_arr) == 0:
        return []

    log.debug(
        "Searching channels: %s, query: %s, period_days: %s, end_date: %s, max_videos_per_channel: %s",
        channels_arr,
        query,
        period_days,
        end_date,
        max_videos_per_channel,
    )

    tasks = _create_channel_tasks(
        channels_arr,
        encoded_search,
        max_videos_per_channel,
        get_descriptions,
        get_transcripts,
    )

    try:
        results = await asyncio.gather(*tasks)
    except Exception as e:
        log.error("Error searching YouTube: %s", e, exc_info=True)
        raise

    return _process_video_results(results, query, char_cap)


def _filter_by_char_cap(videos: list[Video], char_cap: int | None) -> list[Video]:
    """Filter videos to fit within character cap by removing longest transcripts."""
    if char_cap is None:
        return videos
    while len(json.dumps([vid.model_dump_json() for vid in videos])) > char_cap:
        transcript_lengths = [len(video.transcript) for video in videos]
        max_index = transcript_lengths.index(max(transcript_lengths))
        videos.pop(max_index)
    return videos


def _sort_by_publish_time(video: Video) -> float:
    """Sort key function for videos by publish time."""
    now = datetime.now()
    d = dateparser.parse(
        video.publish_time.replace("Streamed ", ""),
        settings={"RELATIVE_BASE": now},
    )
    return time.mktime(d.timetuple())


def youtube_transcripts(ids: str) -> list[VideoTranscript]:
    """Extract transcripts from comma-separated video IDs.

    Args:
        ids: Comma-separated YouTube video IDs

    Returns:
        List of VideoTranscript objects
    """
    results: list[VideoTranscript] = []
    for video_id in ids.split(","):
        transcript = _get_video_transcript(video_id)
        results.append(VideoTranscript(id=video_id, text=transcript))
    return results


async def _get_channel_videos(
    channel: str,
    url: str,
    max_videos_per_channel: int,
    get_descriptions: bool,
    get_transcripts: bool,
) -> list[Video]:
    """Fetch and parse videos from a channel search page."""
    # Cookie to bypass YouTube consent page
    async with ClientSession() as session:
        response = await session.get(
            url,
            headers={"Cookie": "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"},
        )
        if response.status != 200:
            raise RuntimeError(
                f'Failed to fetch videos for channel "{channel}". '
                f"The handle is probably incorrect. Status: {response.status}"
            )
        html = await response.text()
        videos = _parse_html_list(html, max_results=max_videos_per_channel)
        for video in videos:
            if get_descriptions:
                video_info = await _get_video_info(session, video.id)
                video.long_desc = video_info.get("long_desc")
            if get_transcripts:
                transcript = _get_video_transcript(video.id)
                video.transcript = transcript
        return videos


async def _get_video_info(session: ClientSession, video_id: str) -> HtmlVideoInfo:
    """Fetch video page to extract full description."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    response = await session.get(
        url,
        headers={"Cookie": "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"},
    )
    html = await response.text()
    return _parse_html_video(html)


def _get_video_transcript(video_id: str, strip_timestamps: bool = False) -> str:
    """Extract transcript from YouTube video using youtube-transcript-api.

    Args:
        video_id: YouTube video ID
        strip_timestamps: If True, remove timestamp markers

    Returns:
        Transcript text with or without timestamps
    """
    ytt_api = YouTubeTranscriptApi()
    try:
        transcripts = ytt_api.fetch(video_id, preserve_formatting=True)
        return " ".join(
            [
                (
                    "[" + str(t["start"]).split(".", maxsplit=1)[0] + "s] " + t["text"]
                    if not strip_timestamps
                    else t["text"]
                )
                for t in transcripts.to_raw_data()
            ],
        )
    except (KeyError, AttributeError, ValueError, ConnectionError, TimeoutError) as e:
        log.warning("Could not fetch transcript for %s: %s", video_id, e)
        return ""


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube search and transcript extraction")
    parser.add_argument(
        "--mode",
        choices=["search", "transcripts", "history", "subscriptions"],
        required=True,
        help="Operation mode",
    )
    parser.add_argument("--ids", help="Comma-separated video IDs (for transcripts mode)")
    parser.add_argument("--channels", help="Comma-separated channel handles (optional for search mode)")
    parser.add_argument("--query", help="Search query (required for search mode; title-only for history mode)")
    parser.add_argument("--channel", help="Filter to specific channel name (history/subscriptions feed)")
    parser.add_argument("--period-days", type=int, default=30, help="Days back to search (default: 30)")
    parser.add_argument("--end-date", default="", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--max-videos", type=int, default=5, help="Max videos per channel (default: 5)")
    parser.add_argument("--cookies", help="Path to Netscape cookies.txt file (default: ~/.config/youtube/cookies.txt)")
    parser.add_argument("--descriptions", action="store_true", help="Extract full descriptions")
    parser.add_argument("--no-transcripts", action="store_true", help="Skip transcript extraction")
    parser.add_argument("--transcripts", action="store_true", help="Fetch transcripts (history mode, off by default)")
    parser.add_argument("--char-cap", type=int, help="Max total characters for output")
    parser.add_argument(
        "--list-channels",
        action="store_true",
        help="List subscription channels (subscriptions mode only)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output (subscriptions --list-channels only)",
    )
    parser.add_argument(
        "--max-channels",
        type=int,
        help="Max channels to return (subscriptions --list-channels only; default: no limit)",
    )
    return parser


def _print_transcript_results(results: list[VideoTranscript]) -> None:
    for transcript in results:
        print(f"Video ID: {transcript.id}")
        print(f"URL: https://youtube.com/watch?v={transcript.id}")
        print("---")
        print(transcript.text)
        print()


def _print_history_results(videos: list[Video]) -> None:
    if not videos:
        print("No matching videos found in watch history.")
    for video in videos:
        print(f"Title: {video.title}")
        print(f"URL: https://youtube.com{video.url_suffix}")
        print(f"Channel: {video.channel}")
        print(f"Duration: {video.duration}")
        if video.views:
            print(f"Views: {video.views}")
        if video.transcript:
            print("---")
            print(video.transcript)
        print()


def _print_subscription_channel_results(channels: list[SubscriptionChannel], *, as_json: bool) -> None:
    if as_json:
        payload = [
            {
                "id": ch.id,
                "title": ch.title,
                "handle": ch.handle,
                "url_suffix": ch.url_suffix,
                "description": ch.description,
                "subscribers": ch.subscribers,
            }
            for ch in channels
        ]
        print(json.dumps(payload))
        return
    for ch in channels:
        print(f"Channel: {ch.title}")
        if ch.handle:
            print(f"Handle: {ch.handle}")
        if ch.url_suffix:
            print(f"URL: https://youtube.com{ch.url_suffix}")
        if ch.subscribers:
            print(f"Meta: {ch.subscribers}")
        if ch.description:
            print(f"Description: {ch.description}")
        print()


def _print_subscription_video_results(videos: list[Video]) -> None:
    for video in videos:
        print(f"Title: {video.title}")
        print(f"URL: https://youtube.com{video.url_suffix}")
        print(f"Channel: {video.channel}")
        if video.publish_time:
            print(f"Published: {video.publish_time}")
        if video.duration:
            print(f"Duration: {video.duration}")
        if video.views:
            print(f"Views: {video.views}")
        if video.transcript:
            print("---")
            print(video.transcript)
        print()


def _print_search_results(videos: list[Video]) -> None:
    for video in videos:
        print(f"Title: {video.title}")
        print(f"URL: https://youtube.com{video.url_suffix}")
        print(f"Channel: {video.channel}")
        print(f"Published: {video.publish_time}")
        print(f"Duration: {video.duration}")
        print(f"Views: {video.views}")
        if video.long_desc:
            print(f"Description: {video.long_desc}")
        if video.transcript:
            print("---")
            print(video.transcript)
        print()


async def _run_history_mode(args: argparse.Namespace) -> None:
    try:
        videos = await youtube_history(
            query=args.query,
            channel=args.channel,
            max_results=args.max_videos,
            cookies_file=args.cookies,
            get_transcripts=args.transcripts,
            char_cap=args.char_cap,
        )
    except YouTubeBackoffError as e:
        print(f"⏸ {e}", flush=True)
        raise SystemExit(1) from e
    _print_history_results(videos)


async def _run_subscriptions_mode(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.query:
        parser.error("--query is not supported for subscriptions mode")
    if args.json and not args.list_channels:
        parser.error("--json is only supported with --list-channels")
    try:
        results = await youtube_subscriptions(
            query=args.query,
            channel=args.channel,
            max_results=args.max_videos,
            cookies_file=args.cookies,
            get_transcripts=args.transcripts,
            char_cap=args.char_cap,
            list_channels=args.list_channels,
            max_channels=args.max_channels,
        )
    except YouTubeBackoffError as e:
        print(f"⏸ {e}", flush=True)
        raise SystemExit(1) from e

    if not results:
        print("No matching subscriptions found.")
        return
    if args.list_channels:
        _print_subscription_channel_results(cast(list[SubscriptionChannel], results), as_json=args.json)
        return
    _print_subscription_video_results(cast(list[Video], results))


async def _run_search_mode(args: argparse.Namespace) -> None:
    videos = await youtube_search(
        channels=args.channels,
        query=args.query,
        period_days=args.period_days,
        end_date=args.end_date,
        max_videos_per_channel=args.max_videos,
        get_descriptions=args.descriptions,
        get_transcripts=not args.no_transcripts,
        char_cap=args.char_cap,
    )
    _print_search_results(videos)


async def main() -> None:
    """CLI entrypoint for searching YouTube channels and extracting transcripts."""
    parser = _build_cli_parser()
    args = parser.parse_args()

    if args.mode == "transcripts":
        if not args.ids:
            parser.error("--ids required for transcripts mode")
        _print_transcript_results(youtube_transcripts(args.ids))
        return
    if args.mode == "history":
        await _run_history_mode(args)
        return
    if args.mode == "subscriptions":
        await _run_subscriptions_mode(args, parser)
        return
    await _run_search_mode(args)


if __name__ == "__main__":
    asyncio.run(main())
