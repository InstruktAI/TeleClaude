"""Characterization tests for teleclaude.events.signal.ai."""

from __future__ import annotations

import pytest

from teleclaude.events.signal.ai import DefaultSignalAIClient, SignalAIClient, SynthesisArtifact


def test_synthesis_artifact_fields_present() -> None:
    artifact = SynthesisArtifact(
        summary="overview text",
        key_points=["point1", "point2"],
        sources=["https://example.com"],
        confidence=0.9,
    )
    assert artifact.summary == "overview text"
    assert artifact.key_points == ["point1", "point2"]
    assert artifact.sources == ["https://example.com"]
    assert artifact.confidence == 0.9
    assert artifact.recommended_action is None


def test_synthesis_artifact_recommended_action_optional() -> None:
    artifact = SynthesisArtifact(
        summary="test",
        key_points=[],
        sources=[],
        confidence=0.5,
        recommended_action="review this",
    )
    assert artifact.recommended_action == "review this"


def test_signal_ai_client_is_protocol() -> None:
    # Protocol is runtime-checkable
    assert hasattr(SignalAIClient, "summarise")
    assert hasattr(SignalAIClient, "extract_tags")
    assert hasattr(SignalAIClient, "embed")
    assert hasattr(SignalAIClient, "synthesise_cluster")


def test_default_client_satisfies_protocol() -> None:
    client = DefaultSignalAIClient(ai_client=object())
    assert isinstance(client, SignalAIClient)


async def test_default_client_embed_returns_none() -> None:
    client = DefaultSignalAIClient(ai_client=object())
    result = await client.embed("some text")
    assert result is None


async def test_default_client_summarise_propagates_exceptions() -> None:
    class FakeClient:
        class messages:
            @staticmethod
            async def create(*_args: object, **__: object) -> object:
                raise RuntimeError("api error")

    client = DefaultSignalAIClient(ai_client=FakeClient())
    with pytest.raises(RuntimeError):
        await client.summarise("title", "body")


async def test_default_client_extract_tags_returns_empty_on_error() -> None:
    class FakeClient:
        class messages:
            @staticmethod
            async def create(*_args: object, **__: object) -> object:
                raise RuntimeError("api error")

    client = DefaultSignalAIClient(ai_client=FakeClient())
    tags = await client.extract_tags("title", "summary")
    assert tags == []
