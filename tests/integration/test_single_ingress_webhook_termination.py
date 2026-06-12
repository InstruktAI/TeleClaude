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

import hashlib
import hmac
import json
from collections.abc import Mapping

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from teleclaude.hooks.inbound import InboundEndpointRegistry, NormalizerRegistry
from teleclaude.hooks.webhook_models import HookEvent

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


class _CapturingDispatch:
    """Stands in for the cluster-relay boundary; records every relayed event."""

    def __init__(self) -> None:
        self.relayed: list[HookEvent] = []

    async def __call__(self, event: HookEvent) -> None:
        self.relayed.append(event)


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


def _signed(payload: Mapping[str, object]) -> tuple[bytes, dict[str, str]]:
    """Serialize a payload and produce a valid provider signature header."""
    body = json.dumps(payload).encode()
    digest = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {_SIGNATURE_HEADER: f"sha256={digest}", "content-type": "application/json"}
    return body, headers


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://ingress")


@pytest.mark.spec(_SPEC, "UC-SIT-1")
async def test_signed_external_webhook_is_verified_normalized_and_relayed() -> None:
    # Given the ingress is reachable and a provider sends a signed webhook,
    # When it arrives at the ingress,
    # Then the ingress accepts it and relays the normalized event to the cluster.
    app, dispatch = _build_ingress((_GITHUB_PATH, _GITHUB_KEY))
    body, headers = _signed({"action": _RELEASE_ACTION, "release": {"tag_name": "v1.2.3"}})

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=headers)

    assert response.status_code == 200
    [relayed] = dispatch.relayed
    assert relayed.source == _GITHUB_SOURCE
    assert relayed.type == _GITHUB_TYPE
    assert relayed.payload["action"] == _RELEASE_ACTION


@pytest.mark.spec(_SPEC, "UC-SIT-2")
async def test_verified_event_is_relayed_without_any_role_or_channel_gate() -> None:
    # Given a low-power appliance ingress that would not itself act on the event,
    # When it receives and verifies that event,
    # Then it relays the event to the cluster anyway — the registry holds no gate
    # deciding whether to relay; a verified event is always dispatched.
    app, dispatch = _build_ingress((_GITHUB_PATH, _GITHUB_KEY))
    body, headers = _signed({"action": "published", "for_project": "a-repo-this-node-does-not-host"})

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=headers)

    assert response.status_code == 200
    [relayed] = dispatch.relayed
    assert relayed.source == _GITHUB_SOURCE
    assert relayed.type == _GITHUB_TYPE


@pytest.mark.spec(_SPEC, "UC-SIT-3")
async def test_unverified_payload_is_rejected_and_nothing_is_relayed() -> None:
    # Given a payload arrives without a valid provider signature,
    # When the ingress verifies it,
    # Then verification fails, the sender is rejected, and no event reaches the cluster.
    app, dispatch = _build_ingress((_GITHUB_PATH, _GITHUB_KEY))
    body = json.dumps({"action": "published"}).encode()
    forged = {_SIGNATURE_HEADER: "sha256=deadbeef", "content-type": "application/json"}

    async with _client(app) as client:
        response = await client.post(_GITHUB_PATH, content=body, headers=forged)

    assert response.status_code == 401
    assert dispatch.relayed == []


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
