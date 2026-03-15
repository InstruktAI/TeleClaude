"""Characterization tests for session file serving routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import data_routes


class TestDataRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_serve_session_file_returns_file_response_inside_workspace(self, tmp_path: Path) -> None:
        """Serving a session file returns a FileResponse for files under the workspace root."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "notes.txt"
        target.write_text("hello", encoding="utf-8")

        with (
            patch("teleclaude.api.data_routes.db") as db,
            patch("teleclaude.api.data_routes.get_session_output_dir", return_value=workspace),
        ):
            db.get_session = AsyncMock(return_value=SimpleNamespace(session_id="sess-1"))

            response = await data_routes.serve_session_file("sess-1", file="notes.txt")

        assert response.path == str(target)
        assert response.filename == "notes.txt"
        assert response.media_type == "text/plain"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_serve_session_file_rejects_path_traversal_segments(self) -> None:
        """Path traversal segments are rejected before touching the filesystem."""
        with patch("teleclaude.api.data_routes.db") as db:
            db.get_session = AsyncMock(return_value=SimpleNamespace(session_id="sess-2"))

            with pytest.raises(HTTPException) as exc_info:
                await data_routes.serve_session_file("sess-2", file="../secret.txt")

        assert exc_info.value.status_code == 403

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_serve_session_file_returns_404_for_missing_session(self) -> None:
        """File serving returns 404 when the session record does not exist."""
        with patch("teleclaude.api.data_routes.db") as db:
            db.get_session = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await data_routes.serve_session_file("missing", file="notes.txt")

        assert exc_info.value.status_code == 404
