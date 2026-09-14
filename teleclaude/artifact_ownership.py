"""Record pipeline-owned deployed files and retract files no longer produced."""

from __future__ import annotations

import json
from pathlib import Path

from teleclaude.paths import COMMANDS_DIR, DEPLOYED_COMMANDS_MANIFEST_PATH

_UTF8 = "utf-8"
_NEWLINE = "\n"
_MALFORMED_COMMANDS_MANIFEST_MESSAGE = (
    "Malformed deployed commands manifest at {path}: {detail}. Inspect or delete it to re-seed command ownership."
)
_COMMANDS_MANIFEST_EXPECTED_OBJECT_DETAIL = "expected an object"
_COMMANDS_MANIFEST_EXPECTED_SCOPE_ENTRIES_DETAIL = "expected scope-to-list entries"
_COMMANDS_MANIFEST_BASENAME_DETAIL = "command names must be basenames"
_INVALID_COMMAND_BASENAMES = frozenset({".", ".."})
_COMMAND_NAME_SEPARATORS = frozenset({"/", "\\"})
_RETIRED_NATIVE_COMMAND_DESTINATIONS = (
    (Path(".claude") / "commands", ".md"),
    (Path(".gemini") / "commands", ".toml"),
    (Path(".dsh") / "commands", ".md"),
)
_LEGACY_GEMINI_MASTER_PATH = Path(".gemini") / "GEMINI.md"


def _load_deployed_commands_manifest(manifest_path: Path) -> dict[str, set[str]]:
    """Load the per-source-scope command ownership inventory."""
    try:
        payload: object = json.loads(manifest_path.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(_MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(path=manifest_path, detail=exc)) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(
                path=manifest_path,
                detail=_COMMANDS_MANIFEST_EXPECTED_OBJECT_DETAIL,
            )
        )

    ownership: dict[str, set[str]] = {}
    for scope_key, filenames in payload.items():
        if not isinstance(scope_key, str) or not isinstance(filenames, list):
            raise RuntimeError(
                _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(
                    path=manifest_path,
                    detail=_COMMANDS_MANIFEST_EXPECTED_SCOPE_ENTRIES_DETAIL,
                )
            )
        if any(
            not isinstance(filename, str)
            or not filename
            or filename in _INVALID_COMMAND_BASENAMES
            or any(separator in filename for separator in _COMMAND_NAME_SEPARATORS)
            for filename in filenames
        ):
            raise RuntimeError(
                _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(
                    path=manifest_path,
                    detail=_COMMANDS_MANIFEST_BASENAME_DETAIL,
                )
            )
        ownership[scope_key] = set(filenames)
    return ownership


def _write_deployed_commands_manifest(manifest_path: Path, ownership: dict[str, set[str]]) -> None:
    """Persist command ownership with stable, human-inspectable ordering."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = {scope_key: sorted(filenames) for scope_key, filenames in sorted(ownership.items())}
    manifest_path.write_text(json.dumps(serialized, indent=2) + _NEWLINE, encoding=_UTF8)


def reconcile_deployed_files(
    *,
    scope_key: str,
    staged_commands_dir: Path,
    commands_dir: Path = COMMANDS_DIR,
    manifest_path: Path = DEPLOYED_COMMANDS_MANIFEST_PATH,
) -> None:
    """Retract this scope's absent commands while preserving other scopes' ownership."""
    current_filenames = (
        {entry.name for entry in staged_commands_dir.iterdir() if entry.is_file()}
        if staged_commands_dir.is_dir()
        else set()
    )
    if not manifest_path.exists():
        # No inventory means there is no evidence that an existing destination file is ours.
        _write_deployed_commands_manifest(manifest_path, {scope_key: current_filenames})
        return

    ownership = _load_deployed_commands_manifest(manifest_path)
    previous_filenames = ownership.get(scope_key)
    if previous_filenames is None:
        _write_deployed_commands_manifest(manifest_path, {**ownership, scope_key: current_filenames})
        return

    other_filenames = set().union(
        *(filenames for other_scope, filenames in ownership.items() if other_scope != scope_key)
    )
    for filename in sorted(previous_filenames - current_filenames - other_filenames):
        # Manifest validation constrains every deletion to one direct child of COMMANDS_DIR.
        (commands_dir / filename).unlink(missing_ok=True)

    ownership[scope_key] = current_filenames
    _write_deployed_commands_manifest(manifest_path, ownership)


def retract_retired_native_artifacts(
    *,
    scope_key: str,
    scope_root: Path,
    is_global_scope: bool,
    replacement_master_written: bool,
    manifest_path: Path = DEPLOYED_COMMANDS_MANIFEST_PATH,
) -> None:
    """Retract manifest-owned native command copies and the replaced global Gemini master."""
    ownership = _load_deployed_commands_manifest(manifest_path) if manifest_path.exists() else {}
    for relative_destination, extension in _RETIRED_NATIVE_COMMAND_DESTINATIONS:
        destination = scope_root / relative_destination
        for filename in ownership.get(scope_key, set()):
            (destination / f"{Path(filename).stem}{extension}").unlink(missing_ok=True)
    if is_global_scope and replacement_master_written:
        (scope_root / _LEGACY_GEMINI_MASTER_PATH).unlink(missing_ok=True)
