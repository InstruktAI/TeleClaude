"""Characterization tests for people routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from teleclaude.api import people_routes


class TestPeopleRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_people_returns_safe_subset_from_global_config(self) -> None:
        """People listing maps configured people into the public DTO shape."""
        global_config = SimpleNamespace(
            people=[
                SimpleNamespace(
                    name="Alice",
                    email="alice@example.com",
                    role="admin",
                    expertise={"python": "expert"},
                    proficiency="expert",
                    api_key="secret",
                )
            ]
        )

        with patch("teleclaude.cli.config_handlers.get_global_config", return_value=global_config):
            people = await people_routes.list_people()

        assert [person.model_dump() for person in people] == [
            {
                "name": "Alice",
                "email": "alice@example.com",
                "role": "admin",
                "expertise": {"python": "expert"},
                "proficiency": "expert",
            }
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_people_wraps_config_failures_in_http_500(self) -> None:
        """Config-loading failures surface as a route-level 500 error."""
        with patch("teleclaude.cli.config_handlers.get_global_config", side_effect=RuntimeError("boom")):
            with pytest.raises(HTTPException) as exc_info:
                await people_routes.list_people()

        assert exc_info.value.status_code == 500
