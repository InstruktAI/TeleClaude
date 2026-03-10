"""Unit tests for mirror API endpoints."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from teleclaude.api_server import APIServer


def _create_mirror_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE mirrors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                source_identity TEXT,
                computer TEXT NOT NULL,
                agent TEXT NOT NULL,
                project TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                timestamp_start TEXT,
                timestamp_end TEXT,
                conversation_text TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE mirrors_fts USING fts5(
                title, conversation_text,
                content='mirrors',
                content_rowid='id'
            );
            CREATE TRIGGER mirrors_ai AFTER INSERT ON mirrors BEGIN
                INSERT INTO mirrors_fts(rowid, title, conversation_text)
                VALUES (new.id, new.title, new.conversation_text);
            END;
            CREATE TRIGGER mirrors_ad AFTER DELETE ON mirrors BEGIN
                INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
                VALUES('delete', old.id, old.title, old.conversation_text);
            END;
            CREATE TRIGGER mirrors_au AFTER UPDATE ON mirrors BEGIN
                INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
                VALUES('delete', old.id, old.title, old.conversation_text);
                INSERT INTO mirrors_fts(rowid, title, conversation_text)
                VALUES (new.id, new.title, new.conversation_text);
            END;
            """
        )


def test_mirror_api_routes_search_get_and_transcript(
    tmp_path: Path,
    monkeypatch,
) -> None:
    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text('{"raw":"transcript"}\n', encoding="utf-8")
    db_path = tmp_path / "teleclaude.db"
    _create_mirror_schema(db_path)

    metadata = json.dumps({"transcript_path": str(transcript_path)})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO mirrors (
                session_id, source_identity, computer, agent, project, title, timestamp_start, timestamp_end,
                conversation_text, message_count, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sess-1",
                "claude:session.jsonl",
                "MozBook",
                "claude",
                "teleclaude",
                "Mirror search rollout",
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:05Z",
                "User: please ship the mirror search rollout\nAssistant: switching history search to FTS5 mirrors",
                2,
                metadata,
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:05Z",
            ),
        )

    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))

    from tests.unit.test_api_server import _install_admin_auth_override

    mock_adapter_client = MagicMock()
    mock_cache = MagicMock()
    mock_command_service = MagicMock()
    mock_command_service.create_session = AsyncMock()
    mock_command_service.end_session = AsyncMock()
    mock_command_service.process_message = AsyncMock()
    mock_command_service.handle_voice = AsyncMock()
    mock_command_service.handle_file = AsyncMock()
    mock_command_service.restart_agent = AsyncMock()
    mock_command_service.get_session_data = AsyncMock()

    with patch("teleclaude.api_server.get_command_service", return_value=mock_command_service):
        server = APIServer(client=mock_adapter_client, cache=mock_cache, socket_path=str(tmp_path / "api.sock"))
    client = TestClient(server.app)
    _install_admin_auth_override(client)

    search_response = client.get("/api/mirrors/search", params={"q": "mirror rollout", "agent": "claude"})
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert len(search_payload) == 1
    assert search_payload[0]["session_id"] == "sess-1"

    mirror_response = client.get("/api/mirrors/sess-1")
    assert mirror_response.status_code == 200
    assert mirror_response.json()["conversation_text"].startswith("User: please ship")

    transcript_response = client.get("/api/mirrors/sess-1/transcript")
    assert transcript_response.status_code == 200
    assert '{"raw":"transcript"}' in transcript_response.text
