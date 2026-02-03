# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "youtube-transcript-api",
#     "aiohttp",
#     "dateparser",
#     "munch",
#     "pydantic",
# ]
# ///
"""YouTube search, watch history, and transcript extraction helper.

Searches YouTube channels for videos, queries personal watch history
via InnerTube API, and extracts transcripts.
"""

import asyncio
import hashlib
import http.cookiejar
import json
import logging
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import dateparser  # pylint: disable=import-error
from aiohttp import ClientSession
from munch import munchify  # pylint: disable=import-error
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi  # pylint: disable=import-error

# Configure logging to youtube_helper.log
log_dir = Path.home() / ".claude" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "youtube_helper.log"

log = logging.getLogger("youtube_helper")
log.setLevel(logging.INFO)
if not any(isinstance(handler, RotatingFileHandler) for handler in log.handlers):
    handler = RotatingFileHandler(
        str(log_file),
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [youtube_helper] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(handler)


class Transcript(BaseModel):
    """Transcript model."""

    text: str
    start: int
    duration: int


class VideoTranscript(BaseModel):
    """Video transcript model."""

    id: str
    text: str


class Video(BaseModel):
    """Video model."""

    id: str
    title: str
    short_desc: str
    channel: str
    duration: str
    views: str
    publish_time: str
    url_suffix: str
    long_desc: str | None = None
    transcript: str | None = None


# ---------------------------------------------------------------------------
# Circuit breaker for authenticated YouTube requests
# ---------------------------------------------------------------------------

BACKOFF_FILE = Path.home() / ".config" / "youtube" / ".backoff"
BACKOFF_SECONDS = 600  # 10 minutes


class YouTubeBackoffError(RuntimeError):
    """Raised when the circuit breaker is active."""


def _check_backoff() -> None:
    """Raise if we're still in a backoff window."""
    if not BACKOFF_FILE.exists():
        return
    try:
        expires = datetime.fromisoformat(BACKOFF_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        BACKOFF_FILE.unlink(missing_ok=True)
        return
    if datetime.now(timezone.utc) < expires:
        remaining = int((expires - datetime.now(timezone.utc)).total_seconds())
        raise YouTubeBackoffError(
            f"YouTube backoff active — retrying in {remaining}s. "
            f"Previous request triggered a protective response from YouTube."
        )
    BACKOFF_FILE.unlink(missing_ok=True)


def _trigger_backoff(reason: str) -> None:
    """Activate the circuit breaker."""
    expires = datetime.now(timezone.utc) + timedelta(seconds=BACKOFF_SECONDS)
    BACKOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKOFF_FILE.write_text(expires.isoformat(), encoding="utf-8")
    log.warning("YouTube backoff triggered for %ds: %s", BACKOFF_SECONDS, reason)


# ---------------------------------------------------------------------------
# Watch history via InnerTube browse API (aiohttp — no yt-dlp needed)
# ---------------------------------------------------------------------------

_INNERTUBE_API_URL = "https://www.youtube.com/youtubei/v1/browse"
_INNERTUBE_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20240101.00.00",
        "hl": "en",
        "gl": "US",
    }
}


def _load_cookies_txt(path: str) -> dict[str, str]:
    """Load a Netscape cookies.txt file and return youtube.com cookies as a dict."""
    jar = http.cookiejar.MozillaCookieJar(path)
    jar.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in jar if c.domain and ".youtube.com" in c.domain}


def _cookies_to_header(cookies: dict[str, str]) -> str:
    """Format cookie dict as a Cookie header string."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _refresh_cookies_if_needed() -> bool:
    """Run the cookie refresh script if profile exists. Returns True if successful."""
    profile_dir = Path.home() / ".config" / "youtube" / "playwright-profile"
    if not profile_dir.exists():
        log.warning("Playwright profile not found at %s - cannot auto-refresh cookies", profile_dir)
        return False

    refresh_script = Path(__file__).parent / "refresh_cookies.py"
    if not refresh_script.exists():
        log.warning("refresh_cookies.py not found - cannot auto-refresh cookies")
        return False

    log.info("Auto-refreshing YouTube cookies...")
    try:
        result = subprocess.run(
            ["uv", "run", str(refresh_script)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=refresh_script.parent,
        )
        if result.returncode == 0:
            log.info("Cookie refresh successful")
            return True
        log.error("Cookie refresh failed: %s", result.stderr)
        return False
    except subprocess.TimeoutExpired:
        log.error("Cookie refresh timed out")
        return False
    except Exception as e:
        log.error("Cookie refresh error: %s", e)
        return False


def _parse_history_entries(data: dict) -> list[dict]:
    """Extract video entries from InnerTube browse response JSON."""
    entries: list[dict] = []
    try:
        sections = _get_sections(data)
        for section in sections:
            renderer = section.get("itemSectionRenderer", {})
            for item in renderer.get("contents", []):
                entry = _parse_lockup_view_model(item) or _parse_video_renderer(item)
                if entry:
                    entries.append(entry)
    except (KeyError, IndexError, TypeError) as exc:
        log.warning("Failed to parse history entries: %s", exc)
    return entries


def _get_sections(data: dict) -> list[dict]:
    """Get section list from initial or continuation response."""
    if "contents" in data:
        return data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]["content"][
            "sectionListRenderer"
        ]["contents"]
    if "onResponseReceivedActions" in data:
        for action in data["onResponseReceivedActions"]:
            if "appendContinuationItemsAction" in action:
                return action["appendContinuationItemsAction"]["continuationItems"]
    return []


def _parse_lockup_view_model(item: dict) -> dict | None:
    """Parse a lockupViewModel entry (current YouTube history format)."""
    lvm = item.get("lockupViewModel")
    if not lvm:
        return None
    vid_id = lvm.get("contentId", "")
    meta = lvm.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = meta.get("title", {}).get("content", "")
    meta2 = meta.get("metadata", {}).get("contentMetadataViewModel", {})
    rows = meta2.get("metadataRows", [])
    channel_name = ""
    views = ""
    # row[0] typically has channel (part 0) and views (part 1)
    if rows:
        parts = rows[0].get("metadataParts", [])
        if len(parts) >= 1:
            channel_name = parts[0].get("text", {}).get("content", "")
        if len(parts) >= 2:
            views = parts[1].get("text", {}).get("content", "")
    duration = ""
    overlays = lvm.get("contentImage", {}).get("thumbnailViewModel", {}).get("overlays", [])
    for ov in overlays:
        badges = ov.get("thumbnailBottomOverlayViewModel", {}).get("badges", [])
        for b in badges:
            duration = b.get("thumbnailBadgeViewModel", {}).get("text", "")
    return {"id": vid_id, "title": title, "channel": channel_name, "duration": duration, "views": views}


def _parse_video_renderer(item: dict) -> dict | None:
    """Parse a videoRenderer entry (legacy YouTube format)."""
    vr = item.get("videoRenderer")
    if not vr:
        return None
    title_runs = vr.get("title", {}).get("runs", [])
    channel_runs = vr.get("longBylineText", {}).get("runs", [])
    return {
        "id": vr.get("videoId", ""),
        "title": title_runs[0].get("text", "") if title_runs else "",
        "channel": channel_runs[0].get("text", "") if channel_runs else "",
        "duration": vr.get("lengthText", {}).get("simpleText", ""),
        "views": vr.get("viewCountText", {}).get("simpleText", ""),
    }


def _extract_continuation_token(data: dict) -> str | None:
    """Extract the continuation token for the next page of history."""
    try:
        for section in _get_sections(data):
            cont = section.get("continuationItemRenderer", {})
            endpoint = cont.get("continuationEndpoint", {})
            token = endpoint.get("continuationCommand", {}).get("token")
            if token:
                return token
    except (KeyError, IndexError, TypeError):
        pass
    return None


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
        query: Filter results by title or channel name (case-insensitive substring).
        channel: Filter to a specific channel name (case-insensitive substring).
        max_results: Maximum videos to return.
        cookies_file: Path to a Netscape cookies.txt file (required for auth).
        get_transcripts: Fetch transcripts for matched videos.
        char_cap: Cap total output characters.
        _retry_after_refresh: Internal flag - if True, this is already a retry after cookie refresh.

    Returns:
        List of Video objects from watch history, most recent first.
    """
    _check_backoff()

    # Resolve cookies file
    default_cookies = Path.home() / ".config" / "youtube" / "cookies.txt"
    if not cookies_file and default_cookies.exists():
        cookies_file = str(default_cookies)
    if not cookies_file:
        raise FileNotFoundError(
            "No cookies file found. Export YouTube cookies to "
            "~/.config/youtube/cookies.txt (Netscape format) using a browser extension."
        )

    cookies = _load_cookies_txt(cookies_file)
    if not cookies:
        raise ValueError(f"No youtube.com cookies found in {cookies_file}")

    cookie_header = _cookies_to_header(cookies)
    # SAPISID hash for authenticated InnerTube requests
    sapid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID") or ""
    headers: dict[str, str] = {
        "Cookie": cookie_header,
        "Content-Type": "application/json",
        "Origin": "https://www.youtube.com",
        "X-Youtube-Client-Name": "1",
        "X-Youtube-Client-Version": "2.20240101.00.00",
    }
    if sapid:
        ts = str(int(time.time()))
        hash_input = f"{ts} {sapid} https://www.youtube.com"
        sapid_hash = hashlib.sha1(hash_input.encode()).hexdigest()
        headers["Authorization"] = f"SAPISIDHASH {ts}_{sapid_hash}"

    # Fetch enough pages to satisfy filtering
    fetch_limit = max_results * 5 if (query or channel) else max_results
    log.info("Fetching watch history via InnerTube: target=%d, cookies=%s", fetch_limit, cookies_file)

    all_entries: list[dict] = []
    continuation: str | None = None

    async with ClientSession() as session:
        for page in range(20):  # safety cap on pages
            body: dict[str, Any] = {"context": _INNERTUBE_CONTEXT}
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
                    "YouTube did not recognize the session as logged in. Run: uv run scripts/refresh_cookies.py --setup"
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


def _parse_html_list(html: str, max_results: int) -> list[Video]:
    """Parse YouTube search results HTML."""
    results: list[Video] = []
    if "ytInitialData" not in html:
        return []
    start = html.index("ytInitialData") + len("ytInitialData") + 3
    end = html.index("};", start) + 1
    json_str = html[start:end]
    data = json.loads(json_str)
    if "twoColumnBrowseResultsRenderer" not in data["contents"]:
        return []
    tab = None
    for tab in data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]:
        if "expandableTabRenderer" in tab:
            break
    if tab is None:
        return []
    for contents in tab["expandableTabRenderer"]["content"]["sectionListRenderer"]["contents"]:
        if "itemSectionRenderer" in contents:
            for video in contents["itemSectionRenderer"]["contents"]:
                if "videoRenderer" not in video:
                    continue

                res: dict[str, str | list[str] | int | None] = {}
                video_data = video.get("videoRenderer", {})
                res["id"] = video_data.get("videoId", None)
                res["title"] = video_data.get("title", {}).get("runs", [[{}]])[0].get("text", "")
                res["short_desc"] = video_data.get("descriptionSnippet", {}).get("runs", [{}])[0].get("text", "")
                res["channel"] = video_data.get("longBylineText", {}).get("runs", [[{}]])[0].get("text", None)
                res["duration"] = video_data.get("lengthText", {}).get("simpleText", "")
                res["views"] = video_data.get("viewCountText", {}).get("simpleText", "")
                res["publish_time"] = video_data.get("publishedTimeText", {}).get(
                    "simpleText",
                    "",
                )
                res["url_suffix"] = (
                    video_data.get("navigationEndpoint", {})
                    .get("commandMetadata", {})
                    .get("webCommandMetadata", {})
                    .get("url", "")
                )
                results.append(Video(**res))
                if len(results) >= int(max_results):
                    break
        if len(results) >= int(max_results):
            break

    return results


def _parse_html_video(html: str) -> dict[str, str]:
    """Parse video page HTML to extract description."""
    result: dict[str, str] = {"long_desc": None}
    start = html.index("ytInitialData") + len("ytInitialData") + 3
    end = html.index("};", start) + 1
    json_str = html[start:end]
    data = json.loads(json_str)
    obj = munchify(data)
    try:
        result["long_desc"] = obj.contents.twoColumnWatchNextResults.results.results.contents[
            1
        ].videoSecondaryInfoRenderer.attributedDescription.content
    except (AttributeError, KeyError, IndexError, TypeError):
        log.warning("YouTube HTML structure changed, could not extract long description")
    return result


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
) -> list[Any]:
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
    channels: str,
    end_date: str = "",
    query: str | None = None,
    period_days: int = 3,
    max_videos_per_channel: int = 3,
    get_descriptions: bool = False,
    get_transcripts: bool = True,
    char_cap: int | None = None,
) -> list[Video]:
    """Search YouTube channels for videos with optional transcript extraction.

    Args:
        channels: Comma-separated list of channel handles (e.g., "@indydevdan,@someotherchannel")
        end_date: End date in YYYY-MM-DD format (defaults to today)
        query: Search query within channel
        period_days: Number of days back to search
        max_videos_per_channel: Maximum videos to return per channel
        get_descriptions: Extract full video descriptions
        get_transcripts: Extract video transcripts
        char_cap: Maximum total characters in results (for LLM context management)

    Returns:
        List of Video objects with metadata and optional transcripts
    """
    if not channels:
        raise ValueError("No channels specified")

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

    encoded_search = _build_youtube_search_url(query, period_days, end_date)
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


def _filter_by_char_cap(videos: list[Video], char_cap: int) -> list[Video]:
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


async def _get_video_info(session: ClientSession, video_id: str) -> dict[str, str]:
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


async def main() -> None:
    """CLI entrypoint for searching YouTube channels and extracting transcripts."""
    import argparse

    parser = argparse.ArgumentParser(description="YouTube search and transcript extraction")
    parser.add_argument("--mode", choices=["search", "transcripts", "history"], required=True, help="Operation mode")
    parser.add_argument("--ids", help="Comma-separated video IDs (for transcripts mode)")
    parser.add_argument("--channels", help="Comma-separated channel handles (for search mode)")
    parser.add_argument("--query", help="Search query (title/channel filter for history mode)")
    parser.add_argument("--channel", help="Filter to specific channel name (history mode)")
    parser.add_argument("--period-days", type=int, default=30, help="Days back to search (default: 30)")
    parser.add_argument("--end-date", default="", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--max-videos", type=int, default=5, help="Max videos per channel (default: 5)")
    parser.add_argument("--cookies", help="Path to Netscape cookies.txt file (default: ~/.config/youtube/cookies.txt)")
    parser.add_argument("--descriptions", action="store_true", help="Extract full descriptions")
    parser.add_argument("--no-transcripts", action="store_true", help="Skip transcript extraction")
    parser.add_argument("--transcripts", action="store_true", help="Fetch transcripts (history mode, off by default)")
    parser.add_argument("--char-cap", type=int, help="Max total characters for output")
    args = parser.parse_args()

    if args.mode == "transcripts":
        if not args.ids:
            parser.error("--ids required for transcripts mode")
        results = youtube_transcripts(args.ids)
        for t in results:
            print(f"Video ID: {t.id}")
            print(f"URL: https://youtube.com/watch?v={t.id}")
            print("---")
            print(t.text)
            print()
    elif args.mode == "history":
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
    elif args.mode == "search":
        if not args.channels:
            parser.error("--channels required for search mode")
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


if __name__ == "__main__":
    asyncio.run(main())
