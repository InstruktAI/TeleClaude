"""Render the one canonical GitHub envelope from owner-supplied typed facts."""

from __future__ import annotations

from urllib.parse import quote

from teleclaude.core.roles import RoleName
from teleclaude.types.github_posting import GitHubPostSource, NativeGitHubPostSource, ReflectedGitHubPostSource
from teleclaude.types.workflow_record import Act, Phase

_ABSENT = "-"
_ENCODED_MARKER = "%2D"
_SAFE = "-._~"
_UTF8 = "utf-8"
_STRICT = "strict"
_PART = "{part}/{total}"
_ENVELOPE = (
    "TeleClaude envelope\n"
    "Role: {role}\n"
    "Session: {session}\n"
    "Act: {act}\n"
    "Phase: {phase}\n"
    "Delivery: {delivery}\n"
    "Turn: {turn}\n"
    "Part: {part}\n"
    "End TeleClaude envelope\n\n"
    "{body}"
)


def _identifier(value: str) -> str:
    return _ENCODED_MARKER if value == _ABSENT else quote(value, safe=_SAFE, encoding=_UTF8, errors=_STRICT)


def render_github_envelope(
    role: RoleName, session_id: str, act: Act, phase: Phase | None, source: GitHubPostSource, body: str
) -> str:
    """Preserve opaque prose while rendering canonical values and exact source identities."""
    delivery = _ABSENT if isinstance(source, NativeGitHubPostSource) else _identifier(source.identity)
    mirror = source.mirror if isinstance(source, ReflectedGitHubPostSource) else None
    return _ENVELOPE.format(
        role=role.value,
        session=_identifier(session_id),
        act=act.value,
        phase=phase.value if phase is not None else _ABSENT,
        delivery=delivery,
        turn=_identifier(mirror.turn_id) if mirror is not None else _ABSENT,
        part=_PART.format(part=mirror.part, total=mirror.total) if mirror is not None else _ABSENT,
        body=body,
    )
