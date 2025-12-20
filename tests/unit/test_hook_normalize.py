"""Tests for hook payload normalization helpers."""

from teleclaude.hooks.utils.normalize import normalize_session_start_payload


def test_normalize_session_start_trims_and_returns_values() -> None:
    data = {"session_id": "  abc123  ", "transcript_path": " /tmp/foo.jsonl "}
    session_id, transcript_path = normalize_session_start_payload(data)

    assert session_id == "abc123"
    assert transcript_path == "/tmp/foo.jsonl"
    assert data["session_id"] == "abc123"
    assert data["transcript_path"] == "/tmp/foo.jsonl"


def test_normalize_session_start_derives_session_id_from_path() -> None:
    data = {"transcript_path": "/tmp/gemini-session-999.jsonl"}
    session_id, transcript_path = normalize_session_start_payload(data)

    assert session_id == "gemini-session-999"
    assert transcript_path == "/tmp/gemini-session-999.jsonl"
    assert data["session_id"] == "gemini-session-999"


def test_normalize_session_start_finds_nested_values() -> None:
    data = {
        "details": {
            "sessionId": "nested-42",
            "transcriptFile": "/tmp/nested.jsonl",
        }
    }
    session_id, transcript_path = normalize_session_start_payload(data)

    assert session_id == "nested-42"
    assert transcript_path == "/tmp/nested.jsonl"
