"""Signal AI client protocol and default Anthropic-backed implementation."""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from teleclaude.events.signal.db import SignalItemPayload

logger = logging.getLogger(__name__)


class SynthesisArtifact(BaseModel):
    """Structured synthesis produced from a cluster of related signal items."""

    summary: str
    key_points: list[str]
    sources: list[str]
    confidence: float
    recommended_action: str | None = None


@runtime_checkable
class SignalAIClient(Protocol):
    """Interface required by signal cartridges that call AI services."""

    async def summarise(self, title: str, body: str) -> str:
        """Summarise one fetched item into a short sentence."""
        raise NotImplementedError

    async def extract_tags(self, title: str, summary: str) -> list[str]:
        """Extract normalized tags from a title and summary."""
        raise NotImplementedError

    async def embed(self, text: str) -> list[float] | None:
        """Return an embedding for text, or `None` when unavailable."""
        raise NotImplementedError

    async def synthesise_cluster(self, items: list[SignalItemPayload]) -> SynthesisArtifact:
        """Produce a structured synthesis for a related cluster of items."""
        raise NotImplementedError


class DefaultSignalAIClient:
    """Anthropic-backed signal AI client."""

    def __init__(self, ai_client: object) -> None:
        self._client = ai_client

    def _anthropic_client(self) -> object:
        """Return the raw Anthropic-compatible client object."""
        return self._client

    async def summarise(self, title: str, body: str) -> str:
        """Generate a short summary of one fetched article."""
        client = self._anthropic_client()
        prompt = f"Summarise this article in one sentence (max 20 words).\n\nTitle: {title}\n\nContent: {body[:2000]}"
        try:
            resp = await client.messages.create(  # type: ignore
                model="claude-haiku-4-5-20251001",
                max_tokens=60,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()  # type: ignore[no-any-return]
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("summarise failed: %s", e)
            raise

    async def extract_tags(self, title: str, summary: str) -> list[str]:
        """Generate normalized tags for one fetched article."""
        client = self._anthropic_client()
        prompt = (
            "Extract 3-7 lowercase hyphenated tags for this article.\n"
            "Return only comma-separated tags, no other text.\n\n"
            f"Title: {title}\nSummary: {summary}"
        )
        try:
            resp = await client.messages.create(  # type: ignore
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            tags = [t.strip().lower().replace(" ", "-") for t in raw.split(",") if t.strip()]
            return tags[:7]
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("extract_tags failed: %s", e)
            return []

    async def embed(self, _text: str) -> list[float] | None:
        """Return embeddings for text, or `None` when unavailable."""
        # Anthropic does not have an embedding API; return None to degrade gracefully.
        return None

    async def synthesise_cluster(self, items: list[SignalItemPayload]) -> SynthesisArtifact:
        """Produce a structured synthesis artifact for a cluster of signal items."""
        client = self._anthropic_client()
        item_descriptions = "\n".join(
            f"- {i.get('raw_title', 'Untitled')} ({i.get('item_url', '')}): {i.get('summary', '')}" for i in items[:10]
        )
        prompt = (
            "Synthesise the following news items into a structured JSON artifact.\n\n"
            f"Items:\n{item_descriptions}\n\n"
            "Respond with ONLY valid JSON in this exact format:\n"
            '{"summary": "<1-2 sentence overview>", "key_points": ["<point1>", "<point2>"], '
            '"sources": ["<url1>"], "confidence": 0.0, "recommended_action": null}'
        )
        try:
            resp = await client.messages.create(  # type: ignore
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            # Extract JSON block if wrapped in markdown
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return SynthesisArtifact(
                summary=str(data.get("summary", "")),
                key_points=[str(p) for p in data.get("key_points", [])],
                sources=[str(s) for s in data.get("sources", [])],
                confidence=float(data.get("confidence", 0.5)),
                recommended_action=data.get("recommended_action"),
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("synthesise_cluster failed: %s", e)
            raise
