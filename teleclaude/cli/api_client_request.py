"""Request inputs shared by the TeleClaude API client and its query surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field

from teleclaude.cli.clearance import ClearanceScope

type JsonBody = dict[str, object]  # guard: loose-dict - JSON API response


@dataclass(frozen=True)
class RequestOptions:
    """Optional HTTP request inputs."""

    params: dict[str, str] | list[tuple[str, str]] | None = None
    json_body: JsonBody | None = None
    clearance_scope: ClearanceScope = field(default_factory=ClearanceScope.ungoverned)
