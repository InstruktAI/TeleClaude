"""Signal pipeline event declarations: the item, cluster or synthesis the act produced is the subject."""

from __future__ import annotations

from pydantic import JsonValue

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.references import SignalClusterRef, SignalItemRef, SignalSynthesisRef


class SignalIngestReceivedData(EventData):
    fetched_at: str
    item_url: str
    published_at: str
    raw_title: str
    source_id: str
    tags: list[str]


class SignalClusterFormedData(EventData):
    cluster_id: int
    is_burst: bool
    is_novel: bool
    member_count: int
    summary: str
    tags: list[str]


class SignalSynthesisReadyData(EventData):
    cluster_id: int
    synthesis: dict[str, JsonValue]


class SignalIngestReceived(PlatformEvent[SignalItemRef, SignalIngestReceivedData]):
    NAME = "teleclaude.signal.ingest.received"
    DESCRIPTION = "A single feed item was ingested and normalised."


class SignalClusterFormed(PlatformEvent[SignalClusterRef, SignalClusterFormedData]):
    NAME = "teleclaude.signal.cluster.formed"
    DESCRIPTION = "A group of related ingested signals formed a cluster."


class SignalSynthesisReady(PlatformEvent[SignalSynthesisRef, SignalSynthesisReadyData]):
    NAME = "teleclaude.signal.synthesis.ready"
    DESCRIPTION = "A cluster has been synthesised into a structured artifact."


DECLARED: tuple[DeclaredEvent, ...] = (SignalIngestReceived, SignalClusterFormed, SignalSynthesisReady)
