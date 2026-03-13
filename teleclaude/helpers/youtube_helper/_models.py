"""YouTube data models and type definitions."""

from pydantic import BaseModel
from typing_extensions import TypedDict

from teleclaude.core.models import JsonDict


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


class SubscriptionChannel(BaseModel):
    """Subscription channel model."""

    id: str
    title: str
    handle: str | None = None
    url_suffix: str | None = None
    description: str | None = None
    subscribers: str | None = None


class LockupViewModel(TypedDict, total=False):
    """Subset of lockupViewModel fields used by the helper."""

    contentId: str
    metadata: JsonDict
    contentImage: JsonDict


class VideoRenderer(TypedDict, total=False):
    """Subset of videoRenderer fields used by the helper."""

    videoId: str
    title: JsonDict
    longBylineText: JsonDict
    lengthText: JsonDict
    viewCountText: JsonDict
    publishedTimeText: JsonDict
    navigationEndpoint: JsonDict


class HistoryEntry(TypedDict):
    id: str
    title: str
    channel: str
    duration: str
    views: str
    url_suffix: str
    publish_time: str


class SubscriptionEntry(TypedDict):
    id: str
    title: str
    channel: str
    duration: str
    views: str
    publish_time: str
    url_suffix: str


class HtmlVideoInfo(TypedDict):
    long_desc: str | None


class RichGridItem(TypedDict, total=False):
    richItemRenderer: JsonDict  # guard: youtube-api - Nested InnerTube structure
    continuationItemRenderer: JsonDict  # guard: youtube-api - Nested InnerTube structure


class YouTubeBackoffError(RuntimeError):
    """Raised when the circuit breaker is active."""
