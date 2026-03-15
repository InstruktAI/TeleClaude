"""Characterization tests for teleclaude.hooks.inbound."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi import FastAPI

from teleclaude.core.models import JsonDict
from teleclaude.hooks.inbound import InboundEndpointRegistry, NormalizerRegistry
from teleclaude.hooks.webhook_models import HookEvent


@dataclass
class _DispatchRecorder:
    events: list[HookEvent] = field(default_factory=list)
    error: Exception | None = None

    async def __call__(self, event: HookEvent) -> None:
        if self.error is not None:
            raise self.error
        self.events.append(event)


def _build_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def _sign(body: bytes, secret: str) -> str:
    return f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"


class TestNormalizerRegistry:
    @pytest.mark.unit
    def test_register_and_get_round_trip_normalizers_by_key(self) -> None:
        registry = NormalizerRegistry()

        def _normalizer(payload: JsonDict, headers: dict[str, str]) -> HookEvent:
            return HookEvent(
                source="whatsapp",
                type="message.text",
                timestamp="2025-01-01T00:00:00+00:00",
                payload=payload,
            )

        registry.register("whatsapp", _normalizer)

        assert registry.get("whatsapp") is _normalizer
        assert registry.get("missing") is None


class TestInboundEndpointRegistry:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_verification_returns_the_hub_challenge_for_matching_tokens(self) -> None:
        app = FastAPI()
        normalizers = NormalizerRegistry()
        dispatch = _DispatchRecorder()
        registry = InboundEndpointRegistry(app, normalizers, dispatch)
        registry.register("/hooks/wa", "whatsapp", {"verify_token": "verify-me"})

        async with _build_client(app) as client:
            response = await client.get(
                "/hooks/wa",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "verify-me",
                    "hub.challenge": "12345",
                },
            )

        assert response.status_code == 200
        assert response.text == "12345"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_verifies_signature_and_dispatches_each_normalized_event(self) -> None:
        app = FastAPI()
        normalizers = NormalizerRegistry()
        dispatch = _DispatchRecorder()
        registry = InboundEndpointRegistry(app, normalizers, dispatch)

        def _normalizer(payload: JsonDict, headers: dict[str, str]) -> list[HookEvent]:
            assert headers["x-hook-signature"] == _sign(json.dumps(payload).encode(), "signing-secret")
            return [
                HookEvent(
                    source="whatsapp",
                    type="message.text",
                    timestamp="2025-01-01T00:00:00+00:00",
                    properties={"message_id": "1"},
                ),
                HookEvent(
                    source="whatsapp",
                    type="message.voice",
                    timestamp="2025-01-01T00:00:00+00:00",
                    properties={"message_id": "2"},
                ),
            ]

        normalizers.register("whatsapp", _normalizer)
        registry.register("/hooks/wa", "whatsapp", {"secret": "signing-secret"})
        payload = {"entry": [{"id": "1"}]}
        body = json.dumps(payload).encode()

        async with _build_client(app) as client:
            response = await client.post(
                "/hooks/wa",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hook-Signature": _sign(body, "signing-secret"),
                },
            )

        assert response.status_code == 200
        assert response.json() == {"status": "accepted"}
        assert [event.properties["message_id"] for event in dispatch.events] == ["1", "2"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_returns_bad_request_for_invalid_json_payloads(self) -> None:
        app = FastAPI()
        registry = InboundEndpointRegistry(app, NormalizerRegistry(), _DispatchRecorder())
        registry.register("/hooks/github", "github")

        async with _build_client(app) as client:
            response = await client.post(
                "/hooks/github",
                content=b"{",
                headers={"Content-Type": "application/json"},
            )

        assert response.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_returns_bad_gateway_when_dispatch_raises(self) -> None:
        app = FastAPI()
        normalizers = NormalizerRegistry()
        dispatch = _DispatchRecorder(error=RuntimeError("dispatch failed"))
        registry = InboundEndpointRegistry(app, normalizers, dispatch)

        def _normalizer(payload: JsonDict) -> HookEvent:
            return HookEvent(
                source="github",
                type="push",
                timestamp="2025-01-01T00:00:00+00:00",
                payload=payload,
            )

        normalizers.register("github", _normalizer)
        registry.register("/hooks/github", "github")

        async with _build_client(app) as client:
            response = await client.post(
                "/hooks/github",
                json={"ref": "refs/heads/main"},
            )

        assert response.status_code == 502
