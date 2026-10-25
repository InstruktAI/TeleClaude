"""Record pipeline-owned deployed files and retract files no longer produced."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path

from teleclaude.core.reconciliation.platform_repository import platform_scope_key
from teleclaude.paths import COMMANDS_DIR, DEPLOYED_COMMANDS_MANIFEST_PATH

_UTF8 = "utf-8"
_NEWLINE = "\n"
_MALFORMED_COMMANDS_MANIFEST_MESSAGE = (
    "Malformed deployed commands manifest at {path}: {detail}. Inspect or delete it to re-seed command ownership."
)
_COMMANDS_MANIFEST_EXPECTED_OBJECT_DETAIL = "expected an object"
_COMMANDS_MANIFEST_EXPECTED_SCOPE_ENTRIES_DETAIL = "expected scope-to-list entries"
_COMMANDS_MANIFEST_EXPECTED_OWNERS_DETAIL = "expected an 'owners' object"
_COMMANDS_MANIFEST_PATH_SHAPE_DETAIL = (
    "owned paths must be a basename or exactly '<domain>/<name>.md', with no traversal or extra separators"
)
_INVALID_COMMAND_BASENAMES = frozenset({".", ".."})
_RETIRED_NATIVE_COMMAND_DESTINATIONS = (
    (Path(".claude") / "commands", ".md"),
    (Path(".gemini") / "commands", ".toml"),
    (Path(".dsh") / "commands", ".md"),
)
_LEGACY_GEMINI_MASTER_PATH = Path(".gemini") / "GEMINI.md"
#: The pointer file distribution once generated beside every compiled master.
GENERATED_POINTER_FILENAME = "CLAUDE.md"
_GENERATED_POINTER_BYTES = b"@./AGENTS.md\n"
_GIT_EXECUTABLE = "git"
_GIT_HEAD_TREE_ENTRY_ARGS = ("ls-tree", "--name-only", "HEAD", "--")
_GIT_INDEX_ENTRY_ARGS = ("ls-files", "--error-unmatch", "--")
_GIT_SUCCESS = 0
_GIT_UNMATCHED = 1

# The versioned manifest shape: `{"version": 2, "owners": {scope_key: [path, ...]}}`.
# An unversioned payload (the historical bare `{scope_key: [path, ...]}` shape) is
# migrated forward on read — see `_migrate_unversioned_ownership` — and never
# written back out; every write uses the current version.
_MANIFEST_VERSION = 2
_VERSION_KEY = "version"
_OWNERS_KEY = "owners"
_LEGACY_GLOBAL_SCOPE_KEY = "global"


def _mother_scope_key() -> str:
    """Return the scope key the platform's own repository owns paths under, stable across releases."""
    return platform_scope_key()


def _validate_owned_path(candidate: object, *, manifest_path: Path) -> None:
    """Validate one owned path: a basename, or exactly ``<domain>/<name>.md``.

    Rejects traversal, absolute paths, backslashes, and any shape deeper than
    one optional domain segment — the only nesting the partitioned global
    corpus ever produces.
    """
    if not isinstance(candidate, str) or not candidate or "\\" in candidate:
        raise RuntimeError(
            _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(path=manifest_path, detail=_COMMANDS_MANIFEST_PATH_SHAPE_DETAIL)
        )
    segments = candidate.split("/")
    if len(segments) > 2 or any(not segment or segment in _INVALID_COMMAND_BASENAMES for segment in segments):
        raise RuntimeError(
            _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(path=manifest_path, detail=_COMMANDS_MANIFEST_PATH_SHAPE_DETAIL)
        )


def _parse_owners(payload: object, manifest_path: Path) -> dict[str, set[str]]:
    if not isinstance(payload, dict):
        raise RuntimeError(
            _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(
                path=manifest_path, detail=_COMMANDS_MANIFEST_EXPECTED_SCOPE_ENTRIES_DETAIL
            )
        )
    ownership: dict[str, set[str]] = {}
    for scope_key, relative_paths in payload.items():
        if not isinstance(scope_key, str) or not isinstance(relative_paths, list):
            raise RuntimeError(
                _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(
                    path=manifest_path, detail=_COMMANDS_MANIFEST_EXPECTED_SCOPE_ENTRIES_DETAIL
                )
            )
        for relative_path in relative_paths:
            _validate_owned_path(relative_path, manifest_path=manifest_path)
        ownership[scope_key] = set(relative_paths)
    return ownership


def _migrate_unversioned_ownership(ownership: dict[str, set[str]]) -> dict[str, set[str]]:
    """Rekey the historical ``global`` scope to Mother's canonical root.

    Only Mother could ever have populated ``global`` under the pre-registry,
    single-publisher model, so the rewrite is unconditional. Basenames need no
    further change: the unversioned shape never carried a domain segment.
    """
    if _LEGACY_GLOBAL_SCOPE_KEY not in ownership:
        return ownership
    migrated = dict(ownership)
    legacy_filenames = migrated.pop(_LEGACY_GLOBAL_SCOPE_KEY)
    mother_key = _mother_scope_key()
    migrated[mother_key] = migrated.get(mother_key, set()) | legacy_filenames
    return migrated


def _load_deployed_commands_manifest(manifest_path: Path) -> dict[str, set[str]]:
    """Load the per-source-scope command ownership inventory.

    Transparently upcasts an unversioned legacy manifest in memory; the next
    write persists the versioned shape, so the upcast never needs to run twice
    against the same file.
    """
    try:
        payload: object = json.loads(manifest_path.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(_MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(path=manifest_path, detail=exc)) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(
                path=manifest_path, detail=_COMMANDS_MANIFEST_EXPECTED_OBJECT_DETAIL
            )
        )

    if _VERSION_KEY in payload:
        owners_payload = payload.get(_OWNERS_KEY)
        if owners_payload is None:
            raise RuntimeError(
                _MALFORMED_COMMANDS_MANIFEST_MESSAGE.format(
                    path=manifest_path, detail=_COMMANDS_MANIFEST_EXPECTED_OWNERS_DETAIL
                )
            )
        return _parse_owners(owners_payload, manifest_path)

    return _migrate_unversioned_ownership(_parse_owners(payload, manifest_path))


def _write_deployed_commands_manifest(manifest_path: Path, ownership: dict[str, set[str]]) -> None:
    """Persist command ownership with stable, human-inspectable ordering."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = {
        _VERSION_KEY: _MANIFEST_VERSION,
        _OWNERS_KEY: {scope_key: sorted(filenames) for scope_key, filenames in sorted(ownership.items())},
    }
    manifest_path.write_text(json.dumps(serialized, indent=2) + _NEWLINE, encoding=_UTF8)


def _prune_empty_directories(root: Path, commands_dir: Path) -> None:
    """Remove now-empty directories strictly beneath ``commands_dir``, never it."""
    current = root
    while current != commands_dir and commands_dir in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def reconcile_deployed_files(
    *,
    scope_key: str,
    staged_commands_dir: Path,
    commands_dir: Path = COMMANDS_DIR,
    manifest_path: Path = DEPLOYED_COMMANDS_MANIFEST_PATH,
) -> None:
    """Retract this scope's absent commands while preserving other scopes' ownership.

    Both the staged and deployed corpora are enumerated recursively by
    corpus-relative path, so a command's move from a root basename to a
    ``<domain>/<name>.md`` key deletes nothing another owner still claims.
    """
    current_filenames = (
        {
            entry.relative_to(staged_commands_dir).as_posix()
            for entry in staged_commands_dir.rglob("*")
            if entry.is_file()
        }
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
        ownership[scope_key] = current_filenames
        _write_deployed_commands_manifest(manifest_path, ownership)
        return

    other_filenames = set().union(
        *(filenames for other_scope, filenames in ownership.items() if other_scope != scope_key), set()
    )
    for relative_path in sorted(previous_filenames - current_filenames - other_filenames):
        # Manifest validation constrains every deletion to one contained relative path.
        destination = commands_dir / relative_path
        destination.unlink(missing_ok=True)
        _prune_empty_directories(destination.parent, commands_dir)

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
        for relative_path in ownership.get(scope_key, set()):
            (destination / f"{Path(relative_path).stem}{extension}").unlink(missing_ok=True)
    if is_global_scope and replacement_master_written:
        (scope_root / _LEGACY_GEMINI_MASTER_PATH).unlink(missing_ok=True)


def retired_pointer_candidate(master_dir: Path) -> Path:
    """Return where a retired generated pointer would sit beside a compiled master."""
    return master_dir / GENERATED_POINTER_FILENAME


def _absent_from_canonical_head(canonical_root: Path, relative: str) -> bool:
    # Tree membership has no Python API here; git is its only authority.
    result = subprocess.run(
        [_GIT_EXECUTABLE, *_GIT_HEAD_TREE_ENTRY_ARGS, relative],
        cwd=canonical_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == _GIT_SUCCESS and not result.stdout.strip()


def _absent_from_canonical_index(canonical_root: Path, relative: str) -> bool:
    # Index membership has no Python API here; git is its only authority.
    result = subprocess.run(
        [_GIT_EXECUTABLE, *_GIT_INDEX_ENTRY_ARGS, relative],
        cwd=canonical_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == _GIT_UNMATCHED


def is_retired_pointer(*, snapshot_root: Path, canonical_root: Path, relative: Path) -> bool:
    """Return whether a canonical file is a generated pointer nobody owns.

    It must be a regular file whose bytes equal the pointer, absent from the
    published snapshot, and neither in the canonical repository's current
    ``HEAD`` tree nor in its index. A git query that fails counts as owned.
    """
    destination = canonical_root / relative
    if destination.is_symlink() or not destination.is_file():
        return False
    if destination.read_bytes() != _GENERATED_POINTER_BYTES:
        return False
    if os.path.lexists(snapshot_root / relative):
        return False
    posix = relative.as_posix()
    return _absent_from_canonical_head(canonical_root, posix) and _absent_from_canonical_index(canonical_root, posix)


def retract_retired_pointers(*, snapshot_root: Path, canonical_root: Path, candidates: Iterable[Path]) -> list[Path]:
    """Delete each canonical generated pointer that is still retired at the moment of deletion.

    ``candidates`` are snapshot-rooted pointer paths beside compiled masters.
    Every clause of :func:`is_retired_pointer` is evaluated immediately before
    each unlink; a candidate failing any clause is left untouched. Returns the
    canonical paths removed.
    """
    removed: list[Path] = []
    for candidate in candidates:
        relative = candidate.relative_to(snapshot_root)
        if is_retired_pointer(snapshot_root=snapshot_root, canonical_root=canonical_root, relative=relative):
            destination = canonical_root / relative
            destination.unlink()
            removed.append(destination)
    return removed
