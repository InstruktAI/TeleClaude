"""Spec-anchored tests for single-ingress webhook termination.

Each test binds exactly one scenario from the feature spec via
``@pytest.mark.spec(<spec_id>, <scenario_id>)``. The human-authored Gherkin in
the spec is the contract; the test body only drives the REAL ingress
(``InboundEndpointRegistry`` over a bare FastAPI app) to exercise the scenario.

The ingress is the single public node: it verifies a provider HMAC signature,
normalizes the payload into a ``HookEvent``, and relays it UNCONDITIONALLY to the
cluster. ``dispatch`` is that cluster-relay boundary — it is the legitimate
process/cluster line, so it is the only thing mocked (a capturing async fake).
The endpoint under test (verify → normalize → relay) is never mocked.

UC-SIT-4 ("non-ingress nodes accept no external webhooks") is, at root, a
deployment-topology property rather than an in-process behavior of
``inbound.py``. It is bound here only at the honest in-process facet the registry
actually owns: the registry mounts solely the endpoints it was configured with,
so a webhook directed at an unconfigured path is served by no endpoint (404).
The promiscuous-open failure mode — a node answering webhooks it was never told
to serve — is what that binding guards.

Spec: docs/project/spec/feature/integration/single-ingress-webhook-termination.md
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from teleclaude.core.reconciliation import WEBHOOK_INGRESS_FEATURE_ID
from teleclaude.daemon import TeleClaudeDaemon
from teleclaude.daemon_event_platform import _DaemonEventPlatformMixin
from teleclaude.hooks.inbound import InboundEndpointRegistry, NormalizerRegistry
from teleclaude.hooks.webhook_models import HookEvent
from teleclaude.transport.cluster_bridge import CLUSTER_ENVELOPE_SCHEMA_VERSION, WEBHOOK_PREFIX, ClusterEnvelope

pytestmark = pytest.mark.integration

_SPEC = "project/spec/feature/integration/single-ingress-webhook-termination"

_SECRET = "ingress-shared-secret"

# Provider identities the test normalizers stamp; production and test share these
# constants so the relayed-event assertions are identity comparisons, not literals.
_GITHUB_KEY = "github"
_GITHUB_PATH = "/hooks/github"
_GITHUB_SOURCE = "github"
_GITHUB_TYPE = "release.published"
_RELEASE_ACTION = "published"

_STRIPE_KEY = "stripe"
_STRIPE_PATH = "/hooks/stripe"
_STRIPE_SOURCE = "stripe"
_STRIPE_TYPE = "invoice.paid"

_SIGNATURE_HEADER = "X-Hub-Signature-256"

type ClusterWebhookPayload = dict[str, object]  # guard: loose-dict - dynamic HookEvent JSON carried by cluster envelope


class _CapturingDispatch:
    """Stands in for the cluster-relay boundary; records every relayed event."""

    def __init__(self) -> None:
        self.relayed: list[HookEvent] = []

    async def __call__(self, event: HookEvent) -> None:
        self.relayed.append(event)

    async def dispatch(self, event: HookEvent) -> None:
        self.relayed.append(event)


class _FakePublisher:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.published: list[tuple[str, ClusterWebhookPayload, str | None]] = []

    async def publish(
        self,
        channel: str,
        payload: ClusterWebhookPayload,
        *,
        feature_id: str | None = None,
    ) -> bool:
        self.published.append((channel, payload, feature_id))
        return self.accepted


class _FakeCache:
    def __init__(self, publisher: _FakePublisher | None) -> None:
        self._publisher = publisher

    @property
    def cluster_publisher(self) -> _FakePublisher | None:
        return self._publisher


def _github_normalizer(
    payload: dict[str, object],  # guard: loose-dict - inbound webhook JSON is provider-defined.
    _headers: dict[str, str],
) -> HookEvent:
    return HookEvent.now(source=_GITHUB_SOURCE, event_type=_GITHUB_TYPE, payload=payload)


def _stripe_normalizer(
    payload: dict[str, object],  # guard: loose-dict - inbound webhook JSON is provider-defined.
    _headers: dict[str, str],
) -> HookEvent:
    return HookEvent.now(source=_STRIPE_SOURCE, event_type=_STRIPE_TYPE, payload=payload)


def _build_ingress(*registrations: tuple[str, str]) -> tuple[FastAPI, _CapturingDispatch]:
    """Wire a real ingress: FastAPI app + NormalizerRegistry + InboundEndpointRegistry.

    Each registration is a (path, normalizer_key) pair mounted with the shared
    HMAC secret. Returns the app and the capturing relay boundary.
    """
    app = FastAPI()
    normalizers = NormalizerRegistry()
    normalizers.register(_GITHUB_KEY, _github_normalizer)
    normalizers.register(_STRIPE_KEY, _stripe_normalizer)
    dispatch = _CapturingDispatch()
    ingress = InboundEndpointRegistry(app, normalizers, dispatch)
    for path, normalizer_key in registrations:
        ingress.register(path, normalizer_key, verify_config={"secret": _SECRET})
    return app, dispatch


def _build_relaying_ingress(
    *registrations: tuple[str, str],
    publisher: _FakePublisher | None = None,
) -> tuple[FastAPI, _CapturingDispatch, _FakePublisher | None]:
    app = FastAPI()
    normalizers = NormalizerRegistry()
    normalizers.register(_GITHUB_KEY, _github_normalizer)
    normalizers.register(_STRIPE_KEY, _stripe_normalizer)
    dispatch = _CapturingDispatch()
    harness = cast(Any, object.__new__(_DaemonEventPlatformMixin))
    harness.cache = _FakeCache(publisher)
    ingress = InboundEndpointRegistry(
        app,
        normalizers,
        lambda event: harness._dispatch_inbound_webhook_event(dispatch, event),
    )
    for path, normalizer_key in registrations:
        ingress.register(path, normalizer_key, verify_config={"secret": _SECRET})
    return app, dispatch, publisher


def _daemon_with_hook_dispatcher(dispatch: _CapturingDispatch) -> TeleClaudeDaemon:
    daemon = cast(Any, object.__new__(TeleClaudeDaemon))
    daemon._hook_dispatcher = dispatch
    daemon._log_background_task_exception = lambda _task_name: lambda _task: None
    return cast(TeleClaudeDaemon, daemon)


def _signed(payload: Mapping[str, object]) -> tuple[bytes, dict[str, str]]:
    """Serialize a payload and produce a valid provider signature header."""
    body = json.dumps(payload).encode()
    digest = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {_SIGNATURE_HEADER: f"sha256={digest}", "content-type": "application/json"}
    return body, headers


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://ingress")


@pytest.mark.spec(_SPEC, "UC-SIT-1")
async def test_signed_external_webhook_is_verified_normalized_and_relayed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given the ingress is reachable and a provider sends a signed webhook,
    # When it arrives at the ingress,
    # Then the ingress accepts it and relays the normalized event to the cluster.
    monkeypatch.setattr("teleclaude.daemon.config.computer.name", "subscriber-node")
    monkeypatch.setattr("teleclaude.daemon_event_platform.config.computer.is_ingress_node", True)
    publisher = _FakePublisher()
    app, dispatch, relay = _build_relaying_ingress((_GITHUB_PATH, _GITHUB_KEY), publisher=publisher)
    body, headers = _signed({"action": _RELEASE_ACTION, "release": {"tag_name": "v1.2.3"}})

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=headers)

    assert response.status_code == 200
    [relayed] = dispatch.relayed
    assert relayed.source == _GITHUB_SOURCE
    assert relayed.type == _GITHUB_TYPE
    assert relayed.payload["action"] == _RELEASE_ACTION
    assert relay is publisher
    [(channel, payload, feature_id)] = publisher.published
    assert channel == f"{WEBHOOK_PREFIX}{_GITHUB_SOURCE}"
    assert payload["source"] == _GITHUB_SOURCE
    assert payload["type"] == _GITHUB_TYPE
    assert feature_id == WEBHOOK_INGRESS_FEATURE_ID

    subscriber_dispatch = _CapturingDispatch()
    subscriber = _daemon_with_hook_dispatcher(subscriber_dispatch)
    subscriber._dispatch_cluster_event(
        ClusterEnvelope(
            schema_version=CLUSTER_ENVELOPE_SCHEMA_VERSION,
            channel=channel,
            idempotency_key="idem-webhook-github",
            emitted_at=relayed.timestamp,
            origin="ingress-node",
            payload=payload,
            feature_id=feature_id,
        )
    )
    await asyncio.sleep(0)

    [subscriber_event] = subscriber_dispatch.relayed
    assert subscriber_event.source == _GITHUB_SOURCE
    assert subscriber_event.type == _GITHUB_TYPE
    assert subscriber_event.payload["action"] == _RELEASE_ACTION


async def test_cluster_webhook_echo_from_local_origin_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("teleclaude.daemon.config.computer.name", "ingress-node")
    subscriber_dispatch = _CapturingDispatch()
    daemon = _daemon_with_hook_dispatcher(subscriber_dispatch)

    daemon._dispatch_cluster_event(
        ClusterEnvelope(
            schema_version=CLUSTER_ENVELOPE_SCHEMA_VERSION,
            channel=f"{WEBHOOK_PREFIX}{_GITHUB_SOURCE}",
            idempotency_key="idem-webhook-self",
            emitted_at="2026-06-22T00:00:00+00:00",
            origin="ingress-node",
            payload={"source": _GITHUB_SOURCE, "type": _GITHUB_TYPE, "timestamp": "2026-06-22T00:00:00+00:00"},
            feature_id=WEBHOOK_INGRESS_FEATURE_ID,
        )
    )
    await asyncio.sleep(0)

    assert subscriber_dispatch.relayed == []


@pytest.mark.spec(_SPEC, "UC-SIT-2")
async def test_verified_event_is_relayed_without_any_role_or_channel_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a low-power appliance ingress that would not itself act on the event,
    # When it receives and verifies that event,
    # Then it relays the event to the cluster anyway — the registry holds no gate
    # deciding whether to relay; a verified event is always dispatched.
    monkeypatch.setattr("teleclaude.daemon_event_platform.config.computer.is_ingress_node", True)
    publisher = _FakePublisher()
    app, dispatch, _relay = _build_relaying_ingress((_GITHUB_PATH, _GITHUB_KEY), publisher=publisher)
    body, headers = _signed({"action": "published", "for_project": "a-repo-this-node-does-not-host"})

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=headers)

    assert response.status_code == 200
    [relayed] = dispatch.relayed
    assert relayed.source == _GITHUB_SOURCE
    assert relayed.type == _GITHUB_TYPE
    [(channel, _payload, feature_id)] = publisher.published
    assert channel == f"{WEBHOOK_PREFIX}{_GITHUB_SOURCE}"
    assert feature_id == WEBHOOK_INGRESS_FEATURE_ID


@pytest.mark.spec(_SPEC, "UC-SIT-3")
async def test_unverified_payload_is_rejected_and_nothing_is_relayed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a payload arrives without a valid provider signature,
    # When the ingress verifies it,
    # Then verification fails, the sender is rejected, and no event reaches the cluster.
    monkeypatch.setattr("teleclaude.daemon_event_platform.config.computer.is_ingress_node", True)
    publisher = _FakePublisher()
    app, dispatch, _relay = _build_relaying_ingress((_GITHUB_PATH, _GITHUB_KEY), publisher=publisher)
    body = json.dumps({"action": "published"}).encode()
    forged = {_SIGNATURE_HEADER: "sha256=deadbeef", "content-type": "application/json"}

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=forged)

    assert response.status_code == 401
    assert dispatch.relayed == []
    assert publisher.published == []


async def test_ingress_publish_failure_returns_retryable_error_without_local_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("teleclaude.daemon_event_platform.config.computer.is_ingress_node", True)
    publisher = _FakePublisher(accepted=False)
    app, dispatch, _relay = _build_relaying_ingress((_GITHUB_PATH, _GITHUB_KEY), publisher=publisher)
    body, headers = _signed({"action": _RELEASE_ACTION})

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=headers)

    assert response.status_code == 502
    assert dispatch.relayed == []
    assert len(publisher.published) == 1


async def test_non_ingress_node_dispatches_locally_without_cluster_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("teleclaude.daemon_event_platform.config.computer.is_ingress_node", False)
    publisher = _FakePublisher()
    app, dispatch, _relay = _build_relaying_ingress((_GITHUB_PATH, _GITHUB_KEY), publisher=publisher)
    body, headers = _signed({"action": _RELEASE_ACTION})

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=headers)

    assert response.status_code == 200
    [relayed] = dispatch.relayed
    assert relayed.source == _GITHUB_SOURCE
    assert publisher.published == []


async def test_signed_webhook_without_identity_headers_carries_no_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("teleclaude.daemon_event_platform.config.computer.is_ingress_node", True)
    publisher = _FakePublisher()
    app, dispatch, _relay = _build_relaying_ingress((_GITHUB_PATH, _GITHUB_KEY), publisher=publisher)
    body, headers = _signed({"action": _RELEASE_ACTION})

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=headers)

    assert response.status_code == 200
    [relayed] = dispatch.relayed
    assert relayed.properties == {}
    [(_channel, payload, _feature_id)] = publisher.published
    assert payload["properties"] == {}


@pytest.mark.spec(_SPEC, "UC-SIT-4")
async def test_ingress_serves_no_endpoint_it_was_not_configured_for() -> None:
    # Given the ingress is configured with exactly one webhook endpoint,
    # When an external webhook is directed at a path it was not configured for,
    # Then no endpoint serves it (404) — the registry mounts only its configured
    # surface and is not promiscuously open.
    app, dispatch = _build_ingress((_GITHUB_PATH, _GITHUB_KEY))
    body, headers = _signed({"action": "published"})

    async with _client(app) as client:
        response = await client.post("/hooks/unconfigured", content=body, headers=headers)

    assert response.status_code == 404
    assert dispatch.relayed == []


@pytest.mark.spec(_SPEC, "UC-SIT-5")
async def test_one_ingress_terminates_multiple_providers_independently() -> None:
    # Given one ingress configured for two providers on a single app,
    # When events arrive for each provider,
    # Then the same ingress verifies, normalizes, and relays each independently —
    # adding the second provider required no second app or public endpoint.
    app, dispatch = _build_ingress((_GITHUB_PATH, _GITHUB_KEY), (_STRIPE_PATH, _STRIPE_KEY))
    github_body, github_headers = _signed({"action": "published"})
    stripe_body, stripe_headers = _signed({"id": "in_123"})

    async with _client(app) as client:
        github_response = await client.post(_GITHUB_PATH, content=github_body, headers=github_headers)
        stripe_response = await client.post(_STRIPE_PATH, content=stripe_body, headers=stripe_headers)

    assert github_response.status_code == 200
    assert stripe_response.status_code == 200
    relayed_by_source = {event.source: event.type for event in dispatch.relayed}
    assert relayed_by_source == {_GITHUB_SOURCE: _GITHUB_TYPE, _STRIPE_SOURCE: _STRIPE_TYPE}
