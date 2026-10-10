"""Extract and atomically publish immutable Blueprint generations."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from instrukt_ai_logging import get_logger

from teleclaude.core.blueprint._paths import (
    GRAPH_FILENAME,
    MANIFEST_FILENAME,
    blueprint_dir,
    current_generation_pointer,
    generations_dir,
    graph_path,
    graphify_graph_path,
    manifest_path,
    pin_current_generation,
    refresh_lock_path,
)
from teleclaude.core.blueprint.affected import load_graph
from teleclaude.core.blueprint.manifest import (
    BlueprintManifest,
    BlueprintStatus,
    read_manifest,
    read_published_generation,
    write_manifest,
)
from teleclaude.git_tree import TreeSource, materialize_tree

logger = get_logger(__name__)

_GRAPHIFY_OUT_DIRNAME = "graphify-out"
_GRAPHIFY_COMMAND = "graphify"
_GRAPHIFY_UPDATE_SUBCOMMAND = "update"
_GRAPHIFY_FORCE_OPTION = "--force"
_GRAPH_NODES_FIELD = "nodes"
_SOURCE_FILE_FIELD = "source_file"
_PARENT_PATH_COMPONENT = ".."
_WINDOWS_PATH_SEPARATOR = "\\"
_GENERATION_FAILED_ERROR_TEMPLATE = "Blueprint generation failed for {baseline_sha}: {reason}"
_GRAPHIFY_FAILED_ERROR_TEMPLATE = "graphify update exited {returncode}: {detail}"
_GRAPHIFY_OUTPUT_MISSING_ERROR = "graphify update did not produce graph.json in the committed snapshot"
_GRAPHIFY_OUTPUT_MALFORMED_ERROR = "graphify produced a malformed graph.json"
_GRAPHIFY_SOURCE_FILE_TYPE_ERROR = "graphify produced a non-string source_file"
_GRAPHIFY_SOURCE_FILE_PATH_ERROR = "graphify produced a non-repository-relative source_file"
_BLUEPRINT_ALIAS_DIRECTORY_ERROR_TEMPLATE = "Blueprint alias path is a directory: {link_path}"
_GENERATION_NAME_TEMPLATE = "{revision}-{nonce}"
_STAGING_NAME_TEMPLATE = ".staging-{nonce}"
_CURRENT_GRAPH_ALIAS_TEMPLATE = "current/{filename}"
_CURRENT_MANIFEST_ALIAS_TEMPLATE = "current/{filename}"
_GRAPHIFY_GRAPH_ALIAS_TEMPLATE = "../.teleclaude/blueprint/current/{filename}"
_TEMP_SYMLINK_NAME_TEMPLATE = ".{name}.{nonce}"
_LOCK_MODE = "a+"
_LOCK_OPEN_FLAGS = fcntl.LOCK_EX
_LOCK_NONBLOCKING_FLAG = fcntl.LOCK_NB


class BlueprintGenerationError(RuntimeError):
    """A committed tree could not be extracted and published as a complete generation."""


@contextmanager
def blueprint_generation_lock(repo_root: str | Path, *, wait: bool) -> Iterator[bool]:
    """Serialize every graph and manifest writer through the stable cache lock."""
    lock_path = refresh_lock_path(repo_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open(_LOCK_MODE) as handle:
        flags = _LOCK_OPEN_FLAGS if wait else _LOCK_OPEN_FLAGS | _LOCK_NONBLOCKING_FLAG
        try:
            fcntl.flock(handle.fileno(), flags)
        except OSError:
            if wait:
                raise
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def migrate_legacy_generation(repo_root: str | Path) -> None:
    """Move a valid legacy graph/manifest pair into immutable generation storage."""
    root = Path(repo_root).expanduser().resolve()
    if current_generation_pointer(root).is_symlink():
        return
    legacy_manifest = read_manifest(manifest_path(root))
    legacy_graph = graph_path(root)
    if legacy_manifest is None or legacy_manifest.status is not BlueprintStatus.OK or load_graph(legacy_graph) is None:
        return
    try:
        _validate_graph(legacy_graph)
    except BlueprintGenerationError:
        return
    _stage_and_activate_generation(root, legacy_graph, legacy_manifest)


def generate_committed_blueprint(repo_root: str | Path, *, baseline_sha: str) -> BlueprintManifest:
    """Extract one recorded commit tree and publish its complete graph generation.

    The caller owns ``blueprint_generation_lock``. The source is always an isolated
    linked worktree for ``baseline_sha``; neither the canonical working tree nor a
    branch worktree supplies graph input.
    """
    try:
        root = Path(repo_root).expanduser().resolve()
        migrate_legacy_generation(root)
        current = read_published_generation(root)
        if current is not None and current[1].baseline_sha == baseline_sha:
            return current[1]
        source = TreeSource.recorded_commit(root, baseline_sha)
        with materialize_tree(source) as snapshot_root:
            source_graph = _run_graphify_update(snapshot_root)
            _validate_graph(source_graph)
            manifest = BlueprintManifest(
                baseline_sha=baseline_sha,
                generated_at=datetime.now(UTC).isoformat(),
                status=BlueprintStatus.OK,
            )
            _stage_and_activate_generation(root, source_graph, manifest)
    except BlueprintGenerationError:
        raise
    except Exception as exc:
        raise BlueprintGenerationError(
            _GENERATION_FAILED_ERROR_TEMPLATE.format(baseline_sha=baseline_sha, reason=exc)
        ) from exc
    return manifest


def _run_graphify_update(snapshot_root: Path) -> Path:
    """Run the pinned Graphify extractor against an isolated committed snapshot."""
    # Graphify's supported code-refresh surface is its update command. Its
    # Python package exposes no public update API, so use the pinned executable
    # to retain Graphify's own ignore, manifest, and output orchestration.
    result = subprocess.run(
        [_GRAPHIFY_COMMAND, _GRAPHIFY_UPDATE_SUBCOMMAND, str(snapshot_root), _GRAPHIFY_FORCE_OPTION],
        capture_output=True,
        text=True,
        cwd=str(snapshot_root),
        check=False,
    )
    source_graph = snapshot_root / _GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise BlueprintGenerationError(
            _GRAPHIFY_FAILED_ERROR_TEMPLATE.format(returncode=result.returncode, detail=detail)
        )
    if not source_graph.is_file():
        raise BlueprintGenerationError(_GRAPHIFY_OUTPUT_MISSING_ERROR)
    return source_graph


def _validate_graph(path: Path) -> None:
    """Require Graphify's node/link seam and repository-relative source paths."""
    graph = load_graph(path)
    if graph is None:
        raise BlueprintGenerationError(_GRAPHIFY_OUTPUT_MALFORMED_ERROR)
    nodes = graph[_GRAPH_NODES_FIELD]
    assert isinstance(nodes, list)
    for node in nodes:
        if not isinstance(node, dict) or _SOURCE_FILE_FIELD not in node:
            continue
        source_file = node[_SOURCE_FILE_FIELD]
        if not isinstance(source_file, str):
            raise BlueprintGenerationError(_GRAPHIFY_SOURCE_FILE_TYPE_ERROR)
        source_path = PurePosixPath(source_file)
        if (
            source_path.is_absolute()
            or _PARENT_PATH_COMPONENT in source_path.parts
            or _WINDOWS_PATH_SEPARATOR in source_file
        ):
            raise BlueprintGenerationError(_GRAPHIFY_SOURCE_FILE_PATH_ERROR)


def _stage_and_activate_generation(root: Path, source_graph: Path, manifest: BlueprintManifest) -> None:
    """Stage both generation files on the cache filesystem, then switch one pointer."""
    generations = generations_dir(root)
    generations.mkdir(parents=True, exist_ok=True)
    generation_name = _GENERATION_NAME_TEMPLATE.format(revision=manifest.baseline_sha[:12], nonce=uuid.uuid4().hex)
    staging = generations / _STAGING_NAME_TEMPLATE.format(nonce=uuid.uuid4().hex)
    final = generations / generation_name
    staging.mkdir()
    try:
        shutil.copyfile(source_graph, staging / GRAPH_FILENAME)
        write_manifest(staging / MANIFEST_FILENAME, manifest)
        _validate_graph(staging / GRAPH_FILENAME)
        os.replace(staging, final)
        _install_published_aliases(root)
        _switch_current_generation(root, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if final.exists() and pin_current_generation(root) is None:
            shutil.rmtree(final, ignore_errors=True)
        raise


def _install_published_aliases(root: Path) -> None:
    """Keep legacy stable paths and Graphify's default output on the shared pointer."""
    _replace_with_symlink(graph_path(root), _CURRENT_GRAPH_ALIAS_TEMPLATE.format(filename=GRAPH_FILENAME))
    _replace_with_symlink(manifest_path(root), _CURRENT_MANIFEST_ALIAS_TEMPLATE.format(filename=MANIFEST_FILENAME))
    _replace_with_symlink(
        graphify_graph_path(root),
        _GRAPHIFY_GRAPH_ALIAS_TEMPLATE.format(filename=GRAPH_FILENAME),
    )


def _replace_with_symlink(link_path: Path, target: str) -> None:
    """Replace a stable file path with a relative symlink using one same-filesystem rename."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.is_dir() and not link_path.is_symlink():
        raise BlueprintGenerationError(_BLUEPRINT_ALIAS_DIRECTORY_ERROR_TEMPLATE.format(link_path=link_path))
    temporary = link_path.with_name(_TEMP_SYMLINK_NAME_TEMPLATE.format(name=link_path.name, nonce=uuid.uuid4().hex))
    try:
        temporary.symlink_to(target)
        os.replace(temporary, link_path)
    finally:
        temporary.unlink(missing_ok=True)


def _switch_current_generation(root: Path, generation: Path) -> None:
    """Atomically point readers at one complete immutable generation directory."""
    pointer = current_generation_pointer(root)
    temporary = pointer.with_name(_TEMP_SYMLINK_NAME_TEMPLATE.format(name=pointer.name, nonce=uuid.uuid4().hex))
    relative_target = generation.relative_to(blueprint_dir(root))
    try:
        temporary.symlink_to(relative_target)
        os.replace(temporary, pointer)
    finally:
        temporary.unlink(missing_ok=True)
