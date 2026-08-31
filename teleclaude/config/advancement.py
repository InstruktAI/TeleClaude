"""One-time advancement of legacy tier configuration documents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import NotRequired, TypedDict, cast

import yaml

from teleclaude.config.declaration import write_declared_config
from teleclaude.config.schema import ConfigKind
from teleclaude.paths import COMPANIES_ROOT, CONFIG_ADVANCEMENT_STATE_PATH, GLOBAL_CONFIG_PATH, PEOPLE_DIR
from teleclaude.project_manifest import load_registered_roots

ADVANCEMENT_STATE_PATH = CONFIG_ADVANCEMENT_STATE_PATH
_UTF8 = "utf-8"
_ELIGIBLE_ROOTS_FIELD = "eligible_roots"
_COMPLETED_ROOTS_FIELD = "completed_roots"
_EPOCH_NOT_OPEN = "epoch_not_open"
_ROOT_NOT_ELIGIBLE = "root_not_eligible"
_DOCUMENT_MISSING = "document_missing"
_STATE_ERROR = "Invalid config advancement state: {path}"
_DOCUMENT_ERROR = "Configuration document must be a mapping: {path}"
_NEWLINE = "\n"


class AdvancementState(TypedDict):
    """Durable epoch membership and completed-root records."""

    eligible_roots: dict[str, str]
    completed_roots: list[str]


class AdvanceResult(TypedDict):
    """The outcome of advancing one configured root."""

    eligible: bool
    completed: bool
    advanced: bool
    reason: NotRequired[str]


def open_epoch(state_path: Path = ADVANCEMENT_STATE_PATH) -> bool:
    """Capture the current eligible-root set exactly once."""
    if state_path.exists():
        return False
    state = AdvancementState(eligible_roots=_eligible_roots(), completed_roots=[])
    _write_state(state_path, state)
    return True


def advance_config(
    path: Path, kind: ConfigKind, root: Path, *, state_path: Path = ADVANCEMENT_STATE_PATH
) -> AdvanceResult:
    """Repair an eligible legacy document until its root is recorded complete."""
    state = _load_state(state_path)
    if state is None:
        return AdvanceResult(eligible=False, completed=False, advanced=False, reason=_EPOCH_NOT_OPEN)
    root_key = str(root.expanduser().resolve())
    if state["eligible_roots"].get(root_key) != kind.value:
        return AdvanceResult(eligible=False, completed=False, advanced=False, reason=_ROOT_NOT_ELIGIBLE)
    if root_key in state["completed_roots"]:
        return AdvanceResult(eligible=True, completed=True, advanced=False)
    if not path.exists():
        return AdvanceResult(eligible=True, completed=False, advanced=False, reason=_DOCUMENT_MISSING)
    document = _load_document(path)
    write_declared_config(path, kind, document, schema_root=_schema_root(kind, root))
    state["completed_roots"].append(root_key)
    _write_state(state_path, state)
    return AdvanceResult(eligible=True, completed=True, advanced=True)


def advance_context_config(path: Path, root: Path) -> AdvanceResult:
    """Advance an eligible context marker before its declaration is read."""
    state = _load_state(ADVANCEMENT_STATE_PATH)
    if state is None:
        return AdvanceResult(eligible=False, completed=False, advanced=False, reason=_EPOCH_NOT_OPEN)
    raw_kind = state["eligible_roots"].get(str(root.expanduser().resolve()))
    if raw_kind is None:
        return AdvanceResult(eligible=False, completed=False, advanced=False, reason=_ROOT_NOT_ELIGIBLE)
    return advance_config(path, ConfigKind(raw_kind), root, state_path=ADVANCEMENT_STATE_PATH)


def advance_reachable_roots(state_path: Path = ADVANCEMENT_STATE_PATH) -> list[AdvanceResult]:
    """Best-effort advance every currently reachable root in the captured epoch."""
    state = _load_state(state_path)
    if state is None:
        return []
    results: list[AdvanceResult] = []
    for root_key, raw_kind in state["eligible_roots"].items():
        root = Path(root_key)
        if not root.is_dir():
            continue
        kind = ConfigKind(raw_kind)
        results.append(advance_config(root / "teleclaude.yml", kind, root, state_path=state_path))
    return results


def _eligible_roots() -> dict[str, str]:
    roots: dict[str, str] = {str(GLOBAL_CONFIG_PATH.parent.expanduser().resolve()): ConfigKind.GLOBAL.value}
    for directory in _tier_directories(PEOPLE_DIR):
        roots[str(directory.resolve())] = ConfigKind.PERSON.value
    for directory in _tier_directories(COMPANIES_ROOT):
        roots[str(directory.resolve())] = ConfigKind.COMPANY.value
    for entry in load_registered_roots():
        roots[str(entry.path)] = ConfigKind.PROJECT.value
    return roots


def _tier_directories(parent: Path) -> list[Path]:
    if not parent.is_dir():
        return []
    return [path for path in parent.iterdir() if path.is_dir()]


def _schema_root(kind: ConfigKind, root: Path) -> Path:
    if kind is ConfigKind.PROJECT or kind is ConfigKind.GLOBAL:
        return root
    return root.parent.parent


def _load_document(path: Path) -> Mapping[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding=_UTF8)) or {}
    if not isinstance(loaded, dict):
        raise ValueError(_DOCUMENT_ERROR.format(path=path))
    return cast(Mapping[str, object], loaded)


def _load_state(state_path: Path) -> AdvancementState | None:
    if not state_path.exists():
        return None
    raw = json.loads(state_path.read_text(encoding=_UTF8))
    if not isinstance(raw, dict):
        raise ValueError(_STATE_ERROR.format(path=state_path))
    eligible = raw.get(_ELIGIBLE_ROOTS_FIELD)
    completed = raw.get(_COMPLETED_ROOTS_FIELD)
    if not isinstance(eligible, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in eligible.items()
    ):
        raise ValueError(_STATE_ERROR.format(path=state_path))
    if not isinstance(completed, list) or not all(isinstance(value, str) for value in completed):
        raise ValueError(_STATE_ERROR.format(path=state_path))
    return AdvancementState(eligible_roots=cast(dict[str, str], eligible), completed_roots=completed)


def _write_state(state_path: Path, state: AdvancementState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + _NEWLINE, encoding=_UTF8)
