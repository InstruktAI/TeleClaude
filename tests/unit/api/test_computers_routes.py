"""Characterization tests for computer listing routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import computers_routes
from teleclaude.core.models import ComputerInfo


class CacheStub:
    def get_computers(self) -> list[ComputerInfo]:
        return [
            ComputerInfo(name="raspi", status="online", user="pi", host="raspi.local"),
        ]


class TestComputersRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_computers_includes_local_and_cached_remote_entries(self) -> None:
        """Computer listing merges the local machine with cached remote computers."""
        computers_routes.configure(CacheStub())

        with (
            patch(
                "teleclaude.api.computers_routes.command_handlers.get_computer_info",
                new=AsyncMock(return_value=SimpleNamespace(user="alice", host="workstation", tmux_binary="tmux")),
            ),
            patch(
                "teleclaude.api.computers_routes.config",
                SimpleNamespace(computer=SimpleNamespace(name="local-box"), remote_computers=[]),
            ),
        ):
            response = await computers_routes.list_computers(_identity=object())

        assert [computer.model_dump() for computer in response] == [
            {
                "name": "local-box",
                "status": "online",
                "user": "alice",
                "host": "workstation",
                "is_local": True,
                "tmux_binary": "tmux",
            },
            {
                "name": "raspi",
                "status": "online",
                "user": "pi",
                "host": "raspi.local",
                "is_local": False,
                "tmux_binary": None,
            },
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_computers_wraps_command_failures_in_http_500(self) -> None:
        """Local computer discovery failures surface as a route-level 500."""
        computers_routes.configure(None)

        with patch(
            "teleclaude.api.computers_routes.command_handlers.get_computer_info",
            new=AsyncMock(side_effect=RuntimeError("offline")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await computers_routes.list_computers(_identity=object())

        assert exc_info.value.status_code == 500

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_computers_includes_config_defined_offline_remotes(self) -> None:
        computers_routes.configure(SimpleNamespace(get_computers=lambda: []))

        with (
            patch(
                "teleclaude.api.computers_routes.command_handlers.get_computer_info",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        user="alice",
                        host="workstation",
                        tmux_binary="tmux",
                    )
                ),
            ),
            patch(
                "teleclaude.api.computers_routes.config",
                SimpleNamespace(
                    computer=SimpleNamespace(name="local-box"),
                    remote_computers=[
                        SimpleNamespace(
                            name="raspi",
                            user="pi",
                            host="raspi.local",
                        )
                    ],
                ),
            ),
        ):
            response = await computers_routes.list_computers(_identity=object())

        serialized = [computer.model_dump() for computer in response]
        assert serialized == [
            {
                "name": "local-box",
                "status": "online",
                "user": "alice",
                "host": "workstation",
                "is_local": True,
                "tmux_binary": "tmux",
            },
            {
                "name": "raspi",
                "status": "offline",
                "user": "pi",
                "host": "raspi.local",
                "is_local": False,
                "tmux_binary": None,
            },
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_computers_deduplicates_config_and_cache_names_case_insensitively(self) -> None:
        computers_routes.configure(
            SimpleNamespace(
                get_computers=lambda: [SimpleNamespace(name="RASPI", user="cache-user", host="cache.local")]
            )
        )

        with (
            patch(
                "teleclaude.api.computers_routes.command_handlers.get_computer_info",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        user="alice",
                        host="workstation",
                        tmux_binary="tmux",
                    )
                ),
            ),
            patch(
                "teleclaude.api.computers_routes.config",
                SimpleNamespace(
                    computer=SimpleNamespace(name="local-box"),
                    remote_computers=[
                        SimpleNamespace(
                            name="raspi",
                            user="config-user",
                            host="config.local",
                        )
                    ],
                ),
            ),
        ):
            response = await computers_routes.list_computers(_identity=object())

        raspi_entries = [computer.model_dump() for computer in response if computer.name.lower() == "raspi"]
        assert len(raspi_entries) == 1
        assert raspi_entries[0]["status"] == "online"
        assert raspi_entries[0]["user"] == "cache-user"
