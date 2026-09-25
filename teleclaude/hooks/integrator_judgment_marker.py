"""Checkout-scoped state for post-maintenance integrator judgment."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.git import Repo
from teleclaude.paths import TMP_SESSIONS_DIR, safe_path_component

logger = get_logger("teleclaude.hooks.integrator_judgment_marker")

_TEXT_ENCODING = "utf-8"
_LOCK_SUFFIX = ".lock"
_LOCK_MODE = "a+"
_EMPTY_CONTENT = ""
_NEWLINE = "\n"
_JSON_OBJECT_PREFIX = "{"
_RANGE_SEPARATOR = ".."
_LEGACY_RANGE_PREFIX = "range:"
_LEGACY_ACTION_PREFIX = "action:"
_MIGRATED_EVENT = "integrator_judgment_migrated"
_RECORDED_EVENT = "integrator_judgment_recorded"
_READY_EVENT = "integrator_judgment_ready"
_DISCHARGED_EVENT = "integrator_judgment_discharged"
CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG = "teleclaude_checkpoint_integrator_maintenance"


class _MarkerActivationPayload(BaseModel):
    """Closed wire model for one marker activation."""

    model_config = ConfigDict(extra="forbid")

    before_sha: str | None
    after_sha: str
    activated_at: str


class _MarkerPayload(BaseModel):
    """Closed wire model for the current judgment marker."""

    model_config = ConfigDict(extra="forbid")

    activations: list[_MarkerActivationPayload]
    action_ids: list[str]
    ready_at: str | None


@dataclass(frozen=True)
class JudgmentActivation:
    """One canonical-main activation awaiting a later judgment."""

    before_sha: str | None
    after_sha: str
    activated_at: str


@dataclass(frozen=True)
class IntegratorJudgmentMarker:
    """Accumulated activations, their judgment actions, and maintenance readiness."""

    activations: tuple[JudgmentActivation, ...]
    action_ids: tuple[str, ...]
    ready_at: str | None


def _marker_path(project_root: str | Path) -> Path:
    """Return the canonical-checkout-owned marker path."""
    root = resolve_project_state_root(project_root)
    return TMP_SESSIONS_DIR.resolve() / safe_path_component(str(root)) / CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG


@contextmanager
def _marker_lock(path: Path) -> Iterator[None]:
    """Serialize every marker read-modify-write through one stable sibling lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + _LOCK_SUFFIX)
    with lock_path.open(_LOCK_MODE, encoding=_TEXT_ENCODING) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_marker(path: Path, marker: IntegratorJudgmentMarker) -> None:
    """Atomically replace the marker with its current JSON representation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=_TEXT_ENCODING,
            dir=path.parent,
            prefix=path.name,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(asdict(marker), handle, separators=(",", ":"))
            handle.write(_NEWLINE)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _read_current(content: str) -> IntegratorJudgmentMarker:
    """Decode the current typed marker representation."""
    payload = _MarkerPayload.model_validate_json(content)
    activations = tuple(
        JudgmentActivation(
            before_sha=activation.before_sha,
            after_sha=activation.after_sha,
            activated_at=activation.activated_at,
        )
        for activation in payload.activations
    )
    return IntegratorJudgmentMarker(
        activations=activations,
        action_ids=tuple(payload.action_ids),
        ready_at=payload.ready_at,
    )


def _legacy_activations(project_root: str | Path, ranges: list[str]) -> tuple[JudgmentActivation, ...]:
    """Convert the prior line-oriented range marker to immutable activations."""
    root = resolve_project_state_root(project_root)
    repository = Repo(str(root))
    migrated: list[JudgmentActivation] = []
    for value in ranges:
        before_sha, separator, after_sha = value.partition(_RANGE_SEPARATOR)
        if not separator:
            before_sha, after_sha = _EMPTY_CONTENT, before_sha
        after_commit = repository.commit(after_sha)
        activated_at = after_commit.committed_datetime.astimezone(UTC).isoformat()
        migrated.append(
            JudgmentActivation(
                before_sha=before_sha or None,
                after_sha=after_commit.hexsha,
                activated_at=activated_at,
            )
        )
    return tuple(_dedupe_activations(migrated))


def _dedupe_activations(activations: list[JudgmentActivation]) -> list[JudgmentActivation]:
    """Retain the first activation for each committed tip."""
    seen: set[str] = set()
    result: list[JudgmentActivation] = []
    for activation in activations:
        if activation.after_sha in seen:
            continue
        seen.add(activation.after_sha)
        result.append(activation)
    return result


def _read_unlocked(path: Path, project_root: str | Path) -> IntegratorJudgmentMarker | None:
    """Read current state, migrating the legacy line representation once."""
    if not path.exists():
        return None
    content = path.read_text(encoding=_TEXT_ENCODING)
    if content.lstrip().startswith(_JSON_OBJECT_PREFIX):
        return _read_current(content)
    ranges: list[str] = []
    action_ids: list[str] = []
    for line in content.splitlines():
        if not line:
            continue
        if line.startswith(_LEGACY_ACTION_PREFIX):
            action_ids.append(line.removeprefix(_LEGACY_ACTION_PREFIX))
        elif line.startswith(_LEGACY_RANGE_PREFIX):
            ranges.append(line.removeprefix(_LEGACY_RANGE_PREFIX))
        else:
            ranges.append(line)
    stat = path.stat()
    ready_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    marker = IntegratorJudgmentMarker(
        activations=_legacy_activations(project_root, ranges),
        action_ids=tuple(dict.fromkeys(action_ids)),
        ready_at=ready_at,
    )
    _write_marker(path, marker)
    logger.info(_MIGRATED_EVENT, activation_count=len(marker.activations))
    return marker


def record_integrator_judgment_activation(
    project_root: str | Path,
    activation_range: ActivationRange,
    action_ids: list[str],
    activated_at: str,
) -> None:
    """Append one qualifying activation after its action records are durable."""
    path = _marker_path(project_root)
    activation = JudgmentActivation(
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        activated_at=activated_at,
    )
    with _marker_lock(path):
        marker = _read_unlocked(path, project_root)
        existing = marker or IntegratorJudgmentMarker(activations=(), action_ids=(), ready_at=None)
        activations = _dedupe_activations([*existing.activations, activation])
        updated = IntegratorJudgmentMarker(
            activations=tuple(activations),
            action_ids=tuple(dict.fromkeys([*existing.action_ids, *action_ids])),
            ready_at=None,
        )
        _write_marker(path, updated)
    logger.info(
        _RECORDED_EVENT,
        after_sha=activation_range.after_sha,
        action_ids=action_ids,
        activation_count=len(updated.activations),
    )


def mark_integrator_judgment_ready(
    project_root: str | Path,
    outstanding: Callable[[str], bool],
    ready_at: str,
) -> bool:
    """Record readiness only when no activation still has an action record."""
    path = _marker_path(project_root)
    with _marker_lock(path):
        marker = _read_unlocked(path, project_root)
        if marker is None or any(outstanding(activation.after_sha) for activation in marker.activations):
            return False
        updated = replace(marker, ready_at=ready_at)
        _write_marker(path, updated)
    logger.info(
        _READY_EVENT,
        ready_at=ready_at,
        activation_count=len(updated.activations),
    )
    return True


def read_integrator_judgment_marker(project_root: str | Path) -> IntegratorJudgmentMarker | None:
    """Return the checkout-owned marker, migrating the legacy form if needed."""
    path = _marker_path(project_root)
    with _marker_lock(path):
        return _read_unlocked(path, project_root)


def discharge_integrator_judgment(
    project_root: str | Path,
    observed: IntegratorJudgmentMarker,
) -> bool:
    """Delete the marker only when it still equals the state the integrator read."""
    path = _marker_path(project_root)
    with _marker_lock(path):
        current = _read_unlocked(path, project_root)
        if current is None or current != observed:
            return False
        path.unlink(missing_ok=True)
    logger.info(
        _DISCHARGED_EVENT,
        activation_count=len(observed.activations),
        action_ids=observed.action_ids,
    )
    return True
