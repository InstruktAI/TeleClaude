"""Functional regressions for direct conversation link cross-delivery."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.core.conversation_delivery import _collect_visible_conversation_segments_since
from teleclaude.core.models import JsonDict

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/direct-conversation-links"


def _write_claude_transcript(path: Path, entries: Sequence[JsonDict]) -> None:
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")


@pytest.mark.spec(_SPEC, "UC-DCL1")
async def test_cross_delivery_excludes_peer_bridge_and_includes_inter_actor_turn(tmp_path: Path) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    _write_claude_transcript(
        transcript_path,
        [
            {
                "timestamp": "2026-01-01T00:00:01+00:00",
                "message": {
                    "role": "user",
                    "content": "[TeleClaude - Peer (session-a) on local]\n\nPrior bundle.",
                },
            },
            {
                "timestamp": "2026-01-01T00:00:02+00:00",
                "message": {
                    "role": "user",
                    "content": "[Orchestrator (session-a) on local]\n\nContinue.",
                },
            },
        ],
    )

    segments = await _collect_visible_conversation_segments_since(
        str(transcript_path),
        AgentName.CLAUDE,
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert [segment.role for segment in segments] == ["user"]

    peer_only_transcript_path = tmp_path / "peer-only-transcript.jsonl"
    _write_claude_transcript(
        peer_only_transcript_path,
        [
            {
                "timestamp": "2026-01-01T00:00:01+00:00",
                "message": {
                    "role": "user",
                    "content": "[TeleClaude - Peer (session-a) on local]\n\nPrior bundle.",
                },
            },
        ],
    )

    peer_only_segments = await _collect_visible_conversation_segments_since(
        str(peer_only_transcript_path),
        AgentName.CLAUDE,
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert peer_only_segments == []
