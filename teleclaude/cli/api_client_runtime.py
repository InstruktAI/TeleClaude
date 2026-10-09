"""Settings, chiptunes, revive, and memory query surface for the TeleClaude API client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
from pydantic import TypeAdapter

from teleclaude.api_models import (
    ChiptunesCommandReceiptDTO,
    ChiptunesStatusDTO,
    CreateSessionResponseDTO,
    SettingsDTO,
    SettingsPatchDTO,
)
from teleclaude.cli.api_client_request import JsonBody, RequestOptions
from teleclaude.cli.clearance import ClearanceScope

_MEMORY_ROWS = TypeAdapter(list[dict[str, object]])  # guard: loose-dict - JSON response from daemon memory API
_MEMORY_ROW = TypeAdapter(dict[str, object])  # guard: loose-dict - JSON response from daemon memory API


class TelecRuntimeAPI:
    """Settings, chiptunes, revive, and memory operations."""

    _request: Callable[..., Awaitable[httpx.Response]]

    async def patch_settings(self, updates: SettingsPatchDTO) -> SettingsDTO:
        """Apply partial updates to runtime settings."""
        resp = await self._request(
            "PATCH",
            "/settings",
            request_options=RequestOptions(json_body=updates.model_dump(exclude_none=True)),
        )
        return TypeAdapter(SettingsDTO).validate_json(resp.text)

    async def deprovision_tts(self) -> SettingsDTO:
        """Force TTS off and remove the TTS-exclusive optional dependencies."""
        resp = await self._request(
            "POST",
            "/settings/tts/deprovision",
            request_options=RequestOptions(clearance_scope=ClearanceScope.verb("config tts deprovision")),
        )
        return TypeAdapter(SettingsDTO).validate_json(resp.text)

    async def chiptunes_next(self) -> ChiptunesCommandReceiptDTO:
        """Queue skip-to-next chiptunes command."""
        resp = await self._request("POST", "/api/chiptunes/next")
        return TypeAdapter(ChiptunesCommandReceiptDTO).validate_json(resp.text)

    async def chiptunes_prev(self) -> ChiptunesCommandReceiptDTO:
        """Queue previous-track chiptunes command."""
        resp = await self._request("POST", "/api/chiptunes/prev")
        return TypeAdapter(ChiptunesCommandReceiptDTO).validate_json(resp.text)

    async def chiptunes_pause(self) -> ChiptunesCommandReceiptDTO:
        """Queue pause command for chiptunes playback."""
        resp = await self._request("POST", "/api/chiptunes/pause")
        return TypeAdapter(ChiptunesCommandReceiptDTO).validate_json(resp.text)

    async def chiptunes_resume(self) -> ChiptunesCommandReceiptDTO:
        """Queue resume command for chiptunes playback."""
        resp = await self._request("POST", "/api/chiptunes/resume")
        return TypeAdapter(ChiptunesCommandReceiptDTO).validate_json(resp.text)

    async def chiptunes_stop(self) -> None:
        """Stop chiptunes playback and kill the worker process."""
        await self._request("POST", "/api/chiptunes/stop")

    async def get_chiptunes_status(self) -> ChiptunesStatusDTO:
        """Fetch current chiptunes playback state."""
        resp = await self._request("GET", "/api/chiptunes/status")
        return TypeAdapter(ChiptunesStatusDTO).validate_json(resp.text)

    async def revive_session(
        self, session_id: str, *, agent: str | None = None, project: str | None = None, computer: str | None = None
    ) -> CreateSessionResponseDTO:
        """Revive a session by TeleClaude or native session ID.

        Without agent, session_id is a TeleClaude session ID.
        With agent, session_id is a native agent session ID resolved server-side.
        """
        params: dict[str, str] = {}
        if agent:
            params["agent"] = agent
        if project:
            params["project"] = project
        if computer:
            params["computer"] = computer
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/revive",
            timeout=30.0,
            request_options=RequestOptions(
                params=params,
                clearance_scope=ClearanceScope.session_verb("sessions revive", session_id, computer=computer),
            ),
        )
        return TypeAdapter(CreateSessionResponseDTO).validate_json(resp.text)

    async def memory_search(
        self,
        query: str,
        limit: int = 20,
        obs_type: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, object]]:  # guard: loose-dict - JSON response from daemon memory API
        """Search memory observations."""
        params: dict[str, str] = {"query": query, "limit": str(limit)}
        if obs_type:
            params["type"] = obs_type
        if project:
            params["project"] = project
        resp = await self._request(
            "GET",
            "/api/memory/search",
            request_options=RequestOptions(params=params, clearance_scope=ClearanceScope.verb("memories search")),
        )
        return _MEMORY_ROWS.validate_json(resp.text)

    async def memory_save(
        self,
        text: str,
        title: str | None = None,
        obs_type: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Save a memory observation."""
        body: JsonBody = {"text": text}
        if title:
            body["title"] = title
        if obs_type:
            body["type"] = obs_type
        if project:
            body["project"] = project
        resp = await self._request(
            "POST",
            "/api/memory/save",
            request_options=RequestOptions(json_body=body, clearance_scope=ClearanceScope.ungoverned()),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_delete(
        self, observation_id: int
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Delete a memory observation by ID."""
        resp = await self._request(
            "DELETE",
            f"/api/memory/{observation_id}",
            request_options=RequestOptions(clearance_scope=ClearanceScope.verb("memories delete")),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_timeline(
        self,
        anchor: int,
        before: int = 3,
        after: int = 3,
        project: str | None = None,
    ) -> list[dict[str, object]]:  # guard: loose-dict - JSON response from daemon memory API
        """Get observations around an anchor ID."""
        params: dict[str, str] = {
            "anchor": str(anchor),
            "depth_before": str(before),
            "depth_after": str(after),
        }
        if project:
            params["project"] = project
        resp = await self._request(
            "GET",
            "/api/memory/timeline",
            request_options=RequestOptions(params=params, clearance_scope=ClearanceScope.verb("memories timeline")),
        )
        return _MEMORY_ROWS.validate_json(resp.text)
