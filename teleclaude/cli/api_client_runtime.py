"""Settings, chiptunes, revive, and memory query surface for the TeleClaude API client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPMethod

import httpx
from pydantic import TypeAdapter

from teleclaude.api_models import (
    CreateSessionResponseDTO,
    SettingsDTO,
    SettingsPatchDTO,
)
from teleclaude.api_models_chiptunes import (
    ChiptunesCommandReceiptDTO,
    ChiptunesPreference,
    ChiptunesPreferenceRequest,
    ChiptunesStatusDTO,
)
from teleclaude.cli.api_client_request import JsonBody, RequestOptions
from teleclaude.cli.clearance import ClearanceScope
from teleclaude.config.operation_answers import CONFIG_OPERATIONS_PATH

_CONFIG_OPERATION_TIMEOUT_SECONDS = 60.0

_MEMORY_ROWS = TypeAdapter(list[dict[str, object]])  # guard: loose-dict - JSON response from daemon memory API


def _curation_address(
    *,
    session_id: str | None = None,
    identity: str | None = None,
    desk: str | None = None,
    extraction: str | None = None,
) -> dict[str, str]:
    """The addressing fields of a curation request: the session, or the identity, desk and extraction."""
    fields = dict(session_id=session_id, identity=identity, desk=desk, extraction=extraction)
    return {name: value for name, value in fields.items() if value is not None}


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

    async def set_chiptunes_favorite(self, sid_path: str, track_name: str, *, marked: bool) -> ChiptunesStatusDTO:
        """Mark or unmark a track as a favourite; the answer is the playback state it altered."""
        return await self._set_chiptunes_preference(ChiptunesPreference.FAVORITE, sid_path, track_name, marked=marked)

    async def set_chiptunes_dislike(self, sid_path: str, track_name: str, *, marked: bool) -> ChiptunesStatusDTO:
        """Mark or unmark a track as disliked; the answer is the playback state it altered."""
        return await self._set_chiptunes_preference(ChiptunesPreference.DISLIKE, sid_path, track_name, marked=marked)

    async def _set_chiptunes_preference(
        self, preference: ChiptunesPreference, sid_path: str, track_name: str, *, marked: bool
    ) -> ChiptunesStatusDTO:
        request = ChiptunesPreferenceRequest(sid_path=sid_path, track_name=track_name, marked=marked)
        resp = await self._request(
            HTTPMethod.PUT, preference.path, request_options=RequestOptions(json_body=request.model_dump())
        )
        return TypeAdapter(ChiptunesStatusDTO).validate_json(resp.text)

    async def get_chiptunes_status(self) -> ChiptunesStatusDTO:
        """Fetch current chiptunes playback state."""
        resp = await self._request("GET", "/api/chiptunes/status")
        return TypeAdapter(ChiptunesStatusDTO).validate_json(resp.text)

    async def run_config_operation(self, request_body: JsonBody, command_path: str) -> str:
        """Run one configuration operation on the daemon, cleared as the `telec config` command that performs it.

        The request and the answer are the operation's JSON; the caller owns their typed models.
        """
        resp = await self._request(
            HTTPMethod.POST,
            CONFIG_OPERATIONS_PATH,
            timeout=_CONFIG_OPERATION_TIMEOUT_SECONDS,
            request_options=RequestOptions(json_body=request_body, clearance_scope=ClearanceScope.verb(command_path)),
        )
        return resp.text

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

    async def memory_curation_scope(
        self,
        *,
        session_id: str | None = None,
        identity: str | None = None,
        desk: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """List the scope a conversation session or an identity (and desk) defines for curation."""
        resp = await self._request(
            "GET",
            "/api/memory/curation/scope",
            request_options=RequestOptions(
                params=_curation_address(session_id=session_id, identity=identity, desk=desk),
                clearance_scope=ClearanceScope.verb("memories scope"),
            ),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_curation_add(
        self,
        obs_type: str,
        text: str,
        *,
        session_id: str | None = None,
        identity: str | None = None,
        desk: str | None = None,
        extraction: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Add a current memory about the person a session or an extraction names."""
        resp = await self._request(
            "POST",
            "/api/memory/curation/add",
            request_options=RequestOptions(
                json_body={
                    **_curation_address(session_id=session_id, identity=identity, desk=desk, extraction=extraction),
                    "type": obs_type,
                    "text": text,
                },
                clearance_scope=ClearanceScope.verb("memories add"),
            ),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_curation_update(
        self,
        observation_id: int,
        text: str,
        *,
        session_id: str | None = None,
        identity: str | None = None,
        desk: str | None = None,
        extraction: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Replace the statement of a current memory in the scope a session or an extraction names."""
        resp = await self._request(
            "POST",
            "/api/memory/curation/update",
            request_options=RequestOptions(
                json_body={
                    **_curation_address(session_id=session_id, identity=identity, desk=desk, extraction=extraction),
                    "id": observation_id,
                    "text": text,
                },
                clearance_scope=ClearanceScope.verb("memories update"),
            ),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_curation_retire(
        self,
        observation_id: int,
        *,
        session_id: str | None = None,
        identity: str | None = None,
        desk: str | None = None,
        extraction: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Retire a current memory in the scope a session or an extraction names."""
        resp = await self._request(
            "POST",
            "/api/memory/curation/retire",
            request_options=RequestOptions(
                json_body={
                    **_curation_address(session_id=session_id, identity=identity, desk=desk, extraction=extraction),
                    "id": observation_id,
                },
                clearance_scope=ClearanceScope.verb("memories retire"),
            ),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_curation_prospect(
        self,
        obs_type: str,
        text: str,
        *,
        session_id: str | None = None,
        desk: str | None = None,
        extraction: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Collect a business item from a desk conversation as a prospect."""
        resp = await self._request(
            "POST",
            "/api/memory/curation/prospect",
            request_options=RequestOptions(
                json_body={
                    **_curation_address(session_id=session_id, desk=desk, extraction=extraction),
                    "type": obs_type,
                    "text": text,
                },
                clearance_scope=ClearanceScope.verb("memories prospect"),
            ),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_extraction_read(
        self, extraction_id: str
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Read an extraction's conversation material, coverage and scope."""
        resp = await self._request(
            "GET",
            f"/api/memory/curation/extraction/{extraction_id}",
            request_options=RequestOptions(clearance_scope=ClearanceScope.verb("memories extraction read")),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_extraction_complete(
        self, extraction_id: str
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Declare an extraction's changes finished."""
        resp = await self._request(
            "POST",
            f"/api/memory/curation/extraction/{extraction_id}/complete",
            request_options=RequestOptions(clearance_scope=ClearanceScope.verb("memories extraction complete")),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_extraction_fail(
        self, extraction_id: str, reason: str
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Report that an extraction could not be finished."""
        resp = await self._request(
            "POST",
            f"/api/memory/curation/extraction/{extraction_id}/fail",
            request_options=RequestOptions(
                json_body={"reason": reason}, clearance_scope=ClearanceScope.verb("memories extraction fail")
            ),
        )
        return _MEMORY_ROW.validate_json(resp.text)

    async def memory_curation_advance(
        self, session_id: str, newest_entry_read: str
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Advance a conversation session's read point."""
        resp = await self._request(
            "POST",
            "/api/memory/curation/advance",
            request_options=RequestOptions(
                json_body={"session_id": session_id, "to": newest_entry_read},
                clearance_scope=ClearanceScope.verb("memories advance"),
            ),
        )
        return _MEMORY_ROW.validate_json(resp.text)
