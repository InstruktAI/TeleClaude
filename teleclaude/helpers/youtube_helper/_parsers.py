"""YouTube history, subscription, and HTML parsing helpers."""

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from aiohttp import ClientSession
from munch import munchify

from teleclaude.core.models import JsonDict, JsonValue
from teleclaude.helpers.youtube_helper._models import (
    HistoryEntry,
    HtmlVideoInfo,
    SubscriptionChannel,
    SubscriptionEntry,
    Video,
)
from teleclaude.helpers.youtube_helper._utils import _safe_get_dict, _safe_get_list, _safe_get_str, log

__all__ = [
    "YouTubeHtmlStructureError",
    "_extract_continuation_token",
    "_extract_lockup_publish_time",
    "_extract_richgrid_continuation",
    "_extract_yt_initial_data",
    "_fetch_channel_about_description",
    "_find_about_description",
    "_get_richgrid_contents",
    "_get_sections",
    "_parse_history_entries",
    "_parse_html_list",
    "_parse_html_video",
    "_parse_lockup_view_model",
    "_parse_subscription_channels",
    "_parse_subscription_entries",
    "_parse_video_renderer",
]


class _SearchResultsRenderer(StrEnum):
    BROWSE = "twoColumnBrowseResultsRenderer"
    GLOBAL = "twoColumnSearchResultsRenderer"


class YouTubeHtmlStructureError(RuntimeError):
    """Raised when YouTube search HTML no longer matches a supported renderer."""


_CONTENTS_KEY = "contents"
_TABS_KEY = "tabs"
_EXPANDABLE_TAB_KEY = "expandableTabRenderer"
_CONTENT_KEY = "content"
_SECTION_LIST_KEY = "sectionListRenderer"
_PRIMARY_CONTENTS_KEY = "primaryContents"
_HTML_STRUCTURE_EVENT = "YouTube HTML structure changed"
_HTML_STRUCTURE_ERROR = "YouTube search results used an unsupported HTML structure"
_SEARCH_RESULTS_PARSER = "search_results"
_UNKNOWN_RENDERER_KEYS = "unavailable"
_RENDERER_KEY_SEPARATOR = ","
_SUPPORTED_RENDERER_KEY = "supportedRenderer"
_ITEM_SECTION_KEY = "itemSectionRenderer"
_VIDEO_RENDERER_KEY = "videoRenderer"
_VIDEO_ID_KEY = "videoId"
_TITLE_KEY = "title"
_DESCRIPTION_SNIPPET_KEY = "descriptionSnippet"
_LONG_BYLINE_TEXT_KEY = "longBylineText"
_LENGTH_TEXT_KEY = "lengthText"
_VIEW_COUNT_TEXT_KEY = "viewCountText"
_PUBLISHED_TIME_TEXT_KEY = "publishedTimeText"
_NAVIGATION_ENDPOINT_KEY = "navigationEndpoint"
_COMMAND_METADATA_KEY = "commandMetadata"
_WEB_COMMAND_METADATA_KEY = "webCommandMetadata"
_RUNS_KEY = "runs"
_TEXT_KEY = "text"
_SIMPLE_TEXT_KEY = "simpleText"
_URL_KEY = "url"
_EMPTY_TEXT = ""


def _parse_history_entries(data: JsonDict) -> list[HistoryEntry]:
    """Extract video entries from InnerTube browse response JSON."""
    entries: list[HistoryEntry] = []
    try:
        sections = _get_sections(data)
        for section in sections:
            contents = _safe_get_list(section, "itemSectionRenderer", "contents")
            for item in contents:
                if isinstance(item, dict):
                    entry = _parse_lockup_view_model(item) or _parse_video_renderer(item)
                    if entry:
                        entries.append(entry)
    except (KeyError, IndexError, TypeError) as exc:
        log.warning("Failed to parse history entries: %s", exc)
    return entries


def _get_richgrid_contents(data: JsonDict) -> list[JsonDict]:
    """Extract richGrid contents from initial or continuation response."""
    if "contents" in data:
        contents = _safe_get_list(
            data,
            "contents",
            "twoColumnBrowseResultsRenderer",
            "tabs",
            0,
            "tabRenderer",
            "content",
            "richGridRenderer",
            "contents",
        )
        return [item for item in contents if isinstance(item, dict)]
    if "onResponseReceivedActions" in data:
        actions = _safe_get_list(data, "onResponseReceivedActions")
        for action in actions:
            if isinstance(action, dict) and "appendContinuationItemsAction" in action:
                items = _safe_get_list(action, "appendContinuationItemsAction", "continuationItems")
                return [item for item in items if isinstance(item, dict)]
    return []


def _extract_richgrid_continuation(contents: list[JsonDict]) -> str | None:
    """Extract continuation token from richGrid contents."""
    for item in contents:
        token = _safe_get_str(item, "continuationItemRenderer", "continuationEndpoint", "continuationCommand", "token")
        if token:
            return token
    return None


def _extract_lockup_publish_time(lvm: Mapping[str, JsonValue]) -> str:
    """Extract publish time from lockupViewModel metadata rows."""
    rows = _safe_get_list(
        dict(lvm), "metadata", "lockupMetadataViewModel", "metadata", "contentMetadataViewModel", "metadataRows"
    )
    if len(rows) < 2:
        return ""
    row1 = rows[1]
    if not isinstance(row1, dict):
        return ""
    parts = _safe_get_list(row1, "metadataParts")
    for part in parts:
        if isinstance(part, dict):
            text = _safe_get_str(part, "text", "content")
            if text:
                return text
    return ""


def _parse_subscription_entries(data: JsonDict) -> list[SubscriptionEntry]:
    """Extract subscription feed entries from InnerTube browse response JSON."""
    entries: list[SubscriptionEntry] = []
    contents = _get_richgrid_contents(data)
    for item in contents:
        if "richItemRenderer" not in item:
            continue
        content = _safe_get_dict(item, "richItemRenderer", "content")
        if "lockupViewModel" in content:
            lvm = _safe_get_dict(content, "lockupViewModel")
            entry = _parse_lockup_view_model({"lockupViewModel": lvm})
            if entry:
                entry["publish_time"] = _extract_lockup_publish_time(lvm)
                entries.append(entry)
            continue
        if "videoRenderer" in content:
            vr = _safe_get_dict(content, "videoRenderer")
            entry = _parse_video_renderer({"videoRenderer": vr})
            if entry:
                entry["publish_time"] = _safe_get_str(vr, "publishedTimeText", "simpleText")
                entries.append(entry)
    return entries


def _parse_subscription_channels(
    data: JsonDict,
) -> list[SubscriptionChannel]:
    """Extract subscription channel list from InnerTube browse response JSON."""
    channels: list[SubscriptionChannel] = []
    sections = _safe_get_list(
        data,
        "contents",
        "twoColumnBrowseResultsRenderer",
        "tabs",
        0,
        "tabRenderer",
        "content",
        "sectionListRenderer",
        "contents",
    )
    if not sections:
        return channels

    for section in sections:
        if not isinstance(section, dict):
            continue
        contents = _safe_get_list(section, "itemSectionRenderer", "contents")
        for content in contents:
            if not isinstance(content, dict):
                continue
            items = _safe_get_list(content, "shelfRenderer", "content", "expandedShelfContentsRenderer", "items")
            for item in items:
                if not isinstance(item, dict) or "channelRenderer" not in item:
                    continue
                r = _safe_get_dict(item, "channelRenderer")
                title = _safe_get_str(r, "title", "simpleText")
                channel_id = _safe_get_str(r, "channelId")
                url_suffix = _safe_get_str(r, "navigationEndpoint", "commandMetadata", "webCommandMetadata", "url")
                description: str | None = None
                if "descriptionSnippet" in r:
                    runs = _safe_get_list(r, "descriptionSnippet", "runs")
                    if runs:
                        description = (
                            "".join(_safe_get_str(run, "text") for run in runs if isinstance(run, dict)) or None
                        )
                handle = _safe_get_str(r, "subscriberCountText", "simpleText") or None
                if handle and not handle.startswith("@"):
                    handle = None
                subscribers = _safe_get_str(r, "videoCountText", "simpleText") or None
                channels.append(
                    SubscriptionChannel(
                        id=channel_id,
                        title=title,
                        handle=handle,
                        url_suffix=url_suffix or None,
                        description=description,
                        subscribers=subscribers,
                    )
                )
    return channels


def _extract_yt_initial_data(html: str) -> JsonDict | None:
    if "ytInitialData" not in html:
        return None
    try:
        start = html.index("ytInitialData") + len("ytInitialData") + 3
        end = html.index("};", start) + 1
        json_str = html[start:end]
        return json.loads(json_str)  # type: ignore[no-any-return]
    except (ValueError, Exception):
        return None


def _find_about_description(obj: Any) -> str | None:
    if isinstance(obj, dict):
        if "descriptionPreviewViewModel" in obj:
            vm = obj["descriptionPreviewViewModel"]
            if isinstance(vm, dict):
                desc = vm.get("description", {})
                if isinstance(desc, dict):
                    content = desc.get("content")
                    if content:
                        return content  # type: ignore[no-any-return]
        if "channelAboutFullMetadataRenderer" in obj:
            meta = obj["channelAboutFullMetadataRenderer"]
            desc = meta.get("description", {})
            if isinstance(desc, dict):
                text = desc.get("simpleText")
                if text:
                    return text  # type: ignore[no-any-return]
            if isinstance(desc, str):
                return desc
        for value in obj.values():
            found = _find_about_description(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_about_description(item)
            if found:
                return found
    return None


async def _fetch_channel_about_description(
    session: ClientSession,
    channel: SubscriptionChannel,
) -> str | None:
    url = None
    if channel.handle:
        url = f"https://www.youtube.com/{channel.handle}/about?hl=en"
    elif channel.id:
        url = f"https://www.youtube.com/channel/{channel.id}/about?hl=en"
    if not url:
        return None
    try:
        resp = await session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Cookie": "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
            },
        )
        if resp.status != 200:
            return None
        html = await resp.text()
        data = _extract_yt_initial_data(html)
        if not data:
            return None
        return _find_about_description(data)
    except Exception:
        return None


def _get_sections(data: JsonDict) -> list[JsonDict]:
    """Get section list from initial or continuation response."""
    if "contents" in data:
        contents = _safe_get_list(
            data,
            "contents",
            "twoColumnBrowseResultsRenderer",
            "tabs",
            0,
            "tabRenderer",
            "content",
            "sectionListRenderer",
            "contents",
        )
        return [item for item in contents if isinstance(item, dict)]
    if "onResponseReceivedActions" in data:
        actions = _safe_get_list(data, "onResponseReceivedActions")
        for action in actions:
            if isinstance(action, dict) and "appendContinuationItemsAction" in action:
                items = _safe_get_list(action, "appendContinuationItemsAction", "continuationItems")
                return [item for item in items if isinstance(item, dict)]
    return []


def _parse_lockup_view_model(item: JsonDict) -> HistoryEntry | None:
    """Parse a lockupViewModel entry (current YouTube history format)."""
    lvm = _safe_get_dict(item, "lockupViewModel")
    if not lvm:
        return None
    vid_id = _safe_get_str(lvm, "contentId")
    meta = _safe_get_dict(lvm, "metadata", "lockupMetadataViewModel")
    title = _safe_get_str(meta, "title", "content")
    meta2 = _safe_get_dict(meta, "metadata", "contentMetadataViewModel")
    rows = _safe_get_list(meta2, "metadataRows")
    channel_name = ""
    views = ""
    # row[0] typically has channel (part 0) and views (part 1)
    if rows and isinstance(rows[0], dict):
        parts = _safe_get_list(rows[0], "metadataParts")
        if len(parts) >= 1 and isinstance(parts[0], dict):
            channel_name = _safe_get_str(parts[0], "text", "content")
        if len(parts) >= 2 and isinstance(parts[1], dict):
            views = _safe_get_str(parts[1], "text", "content")
    duration = ""
    overlays = _safe_get_list(lvm, "contentImage", "thumbnailViewModel", "overlays")
    for ov in overlays:
        if not isinstance(ov, dict):
            continue
        badges = _safe_get_list(ov, "thumbnailBottomOverlayViewModel", "badges")
        for b in badges:
            if isinstance(b, dict):
                duration = _safe_get_str(b, "thumbnailBadgeViewModel", "text")
    return {
        "id": vid_id,
        "title": title,
        "channel": channel_name,
        "duration": duration,
        "views": views,
        "url_suffix": f"/watch?v={vid_id}",
        "publish_time": _extract_lockup_publish_time(lvm),
    }


def _parse_video_renderer(item: JsonDict) -> SubscriptionEntry | None:
    """Parse a videoRenderer entry (legacy YouTube format)."""
    vr = _safe_get_dict(item, "videoRenderer")
    if not vr:
        return None
    title_runs = _safe_get_list(vr, "title", "runs")
    channel_runs = _safe_get_list(vr, "longBylineText", "runs")
    title = ""
    if title_runs and isinstance(title_runs[0], dict):
        title = _safe_get_str(title_runs[0], "text")
    channel = ""
    if channel_runs and isinstance(channel_runs[0], dict):
        channel = _safe_get_str(channel_runs[0], "text")
    return {
        "id": _safe_get_str(vr, "videoId"),
        "title": title,
        "channel": channel,
        "duration": _safe_get_str(vr, "lengthText", "simpleText"),
        "views": _safe_get_str(vr, "viewCountText", "simpleText"),
        "publish_time": _safe_get_str(vr, "publishedTimeText", "simpleText"),
        "url_suffix": _safe_get_str(vr, "navigationEndpoint", "commandMetadata", "webCommandMetadata", "url"),
    }


def _extract_continuation_token(data: JsonDict) -> str | None:
    """Extract the continuation token for the next page of history."""
    for section in _get_sections(data):
        token = _safe_get_str(
            section, "continuationItemRenderer", "continuationEndpoint", "continuationCommand", "token"
        )
        if token:
            return token
    return None


def _validated_search_sections(value: JsonValue) -> list[JsonDict]:
    if not isinstance(value, list):
        raise TypeError(_CONTENTS_KEY)
    sections: list[JsonDict] = []
    for section in value:
        if not isinstance(section, dict):
            raise TypeError(_CONTENTS_KEY)
        sections.append(section)
    return sections


def _search_result_sections(data: JsonDict) -> list[JsonDict]:
    contents = data.get(_CONTENTS_KEY)
    if not isinstance(contents, dict):
        raise TypeError(_CONTENTS_KEY)

    browse_renderer = contents.get(_SearchResultsRenderer.BROWSE)
    if isinstance(browse_renderer, dict):
        tabs = browse_renderer.get(_TABS_KEY)
        if not isinstance(tabs, list):
            raise TypeError(_TABS_KEY)
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            expandable_tab = tab.get(_EXPANDABLE_TAB_KEY)
            if not isinstance(expandable_tab, dict):
                continue
            content = expandable_tab.get(_CONTENT_KEY)
            if not isinstance(content, dict):
                raise TypeError(_CONTENT_KEY)
            section_list = content.get(_SECTION_LIST_KEY)
            if not isinstance(section_list, dict):
                raise TypeError(_SECTION_LIST_KEY)
            sections = _validated_search_sections(section_list.get(_CONTENTS_KEY))
            return sections
        raise KeyError(_EXPANDABLE_TAB_KEY)

    global_renderer = contents.get(_SearchResultsRenderer.GLOBAL)
    if isinstance(global_renderer, dict):
        primary_contents = global_renderer.get(_PRIMARY_CONTENTS_KEY)
        if not isinstance(primary_contents, dict):
            raise TypeError(_PRIMARY_CONTENTS_KEY)
        section_list = primary_contents.get(_SECTION_LIST_KEY)
        if not isinstance(section_list, dict):
            raise TypeError(_SECTION_LIST_KEY)
        sections = _validated_search_sections(section_list.get(_CONTENTS_KEY))
        return sections

    raise KeyError(_SUPPORTED_RENDERER_KEY)


def _first_run_text(data: JsonDict, field: str) -> str:
    runs = _safe_get_list(data, field, _RUNS_KEY)
    if not runs or not isinstance(runs[0], dict):
        return _EMPTY_TEXT
    return _safe_get_str(runs[0], _TEXT_KEY)


def _search_video(video_data: JsonDict) -> Video:
    return Video(
        id=_safe_get_str(video_data, _VIDEO_ID_KEY),
        title=_first_run_text(video_data, _TITLE_KEY),
        short_desc=_first_run_text(video_data, _DESCRIPTION_SNIPPET_KEY),
        channel=_first_run_text(video_data, _LONG_BYLINE_TEXT_KEY),
        duration=_safe_get_str(video_data, _LENGTH_TEXT_KEY, _SIMPLE_TEXT_KEY),
        views=_safe_get_str(video_data, _VIEW_COUNT_TEXT_KEY, _SIMPLE_TEXT_KEY),
        publish_time=_safe_get_str(video_data, _PUBLISHED_TIME_TEXT_KEY, _SIMPLE_TEXT_KEY),
        url_suffix=_safe_get_str(
            video_data,
            _NAVIGATION_ENDPOINT_KEY,
            _COMMAND_METADATA_KEY,
            _WEB_COMMAND_METADATA_KEY,
            _URL_KEY,
        ),
    )


def _videos_from_search_sections(sections: list[JsonDict], max_results: int) -> list[Video]:
    results: list[Video] = []
    for contents in sections:
        if _ITEM_SECTION_KEY in contents:
            item_section = contents[_ITEM_SECTION_KEY]
            if not isinstance(item_section, dict):
                raise TypeError(_ITEM_SECTION_KEY)
            video_items = item_section.get(_CONTENTS_KEY)
            if not isinstance(video_items, list):
                raise TypeError(_CONTENTS_KEY)
            for video in video_items:
                if not isinstance(video, dict) or _VIDEO_RENDERER_KEY not in video:
                    continue
                video_data = video.get(_VIDEO_RENDERER_KEY)
                if not isinstance(video_data, dict):
                    raise TypeError(_VIDEO_RENDERER_KEY)
                results.append(_search_video(video_data))
                if len(results) >= int(max_results):
                    break
        if len(results) >= int(max_results):
            break
    return results


def _parse_html_list(html: str, max_results: int) -> list[Video]:
    """Parse YouTube search results HTML."""
    renderer_keys = _UNKNOWN_RENDERER_KEYS
    try:
        data = _extract_yt_initial_data(html)
        if data is None:
            raise ValueError(_CONTENTS_KEY)
        data_contents = data.get(_CONTENTS_KEY)
        if isinstance(data_contents, dict):
            renderer_keys = _RENDERER_KEY_SEPARATOR.join(sorted(data_contents))
        sections = _search_result_sections(data)
        return _videos_from_search_sections(sections, max_results)
    except (KeyError, TypeError, ValueError) as exc:
        log.error(
            _HTML_STRUCTURE_EVENT,
            parser=_SEARCH_RESULTS_PARSER,
            renderer_keys=renderer_keys,
            failure_type=type(exc).__name__,
        )
        raise YouTubeHtmlStructureError(_HTML_STRUCTURE_ERROR) from exc


def _parse_html_video(html: str) -> HtmlVideoInfo:
    """Parse video page HTML to extract description."""
    result: HtmlVideoInfo = {"long_desc": None}
    start = html.index("ytInitialData") + len("ytInitialData") + 3
    end = html.index("};", start) + 1
    json_str = html[start:end]
    data = json.loads(json_str)
    obj: Any = munchify(data)
    try:
        result["long_desc"] = obj.contents.twoColumnWatchNextResults.results.results.contents[
            1
        ].videoSecondaryInfoRenderer.attributedDescription.content
    except (AttributeError, KeyError, IndexError, TypeError):
        log.warning("YouTube HTML structure changed, could not extract long description")
    return result
