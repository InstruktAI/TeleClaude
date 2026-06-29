"""Drift provenance synchronization for lifecycle artifacts."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_TASK_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
    STATE_KEY_TASK_PLAN,
)
from teleclaude.core.next_machine._types import upstream_keys_for
from teleclaude.core.next_machine.git_ops import extract_referenced_paths, get_origin_main_sha
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.paths import DEFAULT_TELECLAUDE_HOME, GLOBAL_DOCS_DIR
from teleclaude.types.todos import ArtifactEntry

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

_ARTIFACT_TO_STATE_KEY: dict[str, str] = {
    ARTIFACT_INPUT: STATE_KEY_INPUT,
    ARTIFACT_PRD: STATE_KEY_PRD,
    ARTIFACT_REQUIREMENTS: STATE_KEY_REQUIREMENTS,
    ARTIFACT_ARCHITECTURE: STATE_KEY_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS: STATE_KEY_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN: STATE_KEY_IMPLEMENTATION_PLAN,
    ARTIFACT_TASK_PLAN: STATE_KEY_TASK_PLAN,
}

_ARTIFACT_REVIEW_FIELDS: dict[str, str] = {
    STATE_KEY_REQUIREMENTS: "requirements_review",
    STATE_KEY_ARCHITECTURE: "architecture_review",
    STATE_KEY_IMPLEMENTATION_PLAN: "plan_review",
}

_INLINE_REF_RE = re.compile(r"@(?:docs/[^\s)]+\.md|/[^\s)]+/\.teleclaude/docs/[^\s)]+\.md)")


async def sync_artifact_provenance(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    artifact_name: str,
    *,
    repo_root: str,
    artifact_body: str,
    snippet_digest_fn: Callable[[str], str],
) -> None:
    """Populate all drift provenance fields for a tracked lifecycle artifact."""
    key = _state_key_for_artifact(artifact_name)
    if key is None:
        return
    entry = _entry(writer, key)
    entry.digest = await todos_db.artifact_digest(slug, artifact_name)
    entry.codebase_sha_at_write = get_origin_main_sha(repo_root)
    entry.referenced_paths = extract_referenced_paths(artifact_body)
    entry.upstream_digests = _current_upstream_digests(writer, key)
    entry.owned_snippet_digests = await read_owned_snippet_digests(
        todos_db,
        slug,
        artifact_name,
        snippet_digest_fn=snippet_digest_fn,
    )
    entry.referenced_snippet_digests = await read_referenced_snippet_digests(
        todos_db,
        slug,
        artifact_name,
        artifact_body,
        repo_root=repo_root,
        snippet_digest_fn=snippet_digest_fn,
    )
    entry.produced_at = datetime.now(UTC).isoformat()
    entry.async_provenance_complete = True
    _clear_rewrite_drift_state(writer, artifact_name)


def sync_artifact_provenance_sync_subset(
    writer: StateWriter,
    slug: str,
    artifact_name: str,
    *,
    repo_root: str,
    sha_at_write: str,
    referenced_paths: list[str],
    digest: str,
) -> None:
    """Populate sync-readable provenance and clear async-only fields."""
    _ = slug, repo_root
    key = _state_key_for_artifact(artifact_name)
    if key is None:
        return
    entry = _entry(writer, key)
    entry.digest = digest
    entry.codebase_sha_at_write = sha_at_write
    entry.referenced_paths = referenced_paths
    entry.upstream_digests = _current_upstream_digests(writer, key)
    entry.produced_at = datetime.now(UTC).isoformat()
    entry.owned_snippet_digests = {}
    entry.referenced_snippet_digests = {}
    entry.async_provenance_complete = False
    _clear_rewrite_drift_state(writer, artifact_name)


def refresh_referenced_paths(
    writer: StateWriter,
    state_key: str,
    *,
    artifact_body: str,
) -> None:
    """Refresh only the body-derived code surface for an existing artifact."""
    entry = _entry(writer, state_key)
    entry.referenced_paths = extract_referenced_paths(artifact_body)


def clear_artifact_provenance(writer: StateWriter, slug: str, artifact_name: str) -> None:
    """Clear every persisted provenance field for a removed lifecycle artifact."""
    _ = slug
    key = _state_key_for_artifact(artifact_name)
    if key is None:
        return
    entry = _entry(writer, key)
    entry.digest = ""
    entry.produced_at = ""
    entry.codebase_sha_at_write = ""
    entry.referenced_paths = []
    entry.upstream_digests = {}
    entry.owned_snippet_digests = {}
    entry.referenced_snippet_digests = {}
    entry.async_provenance_complete = False
    _clear_rewrite_drift_state(writer, artifact_name)


async def read_owned_snippet_digests(
    todos_db: TodosDb,
    slug: str,
    artifact_name: str,
    *,
    snippet_digest_fn: Callable[[str], str],
) -> dict[str, str]:
    """Read snippets whose delivered_by membership names this todo."""
    _ = todos_db, artifact_name
    return {
        snippet_id: digest
        for snippet_id in _snippet_ids_delivered_by(slug)
        if (digest := snippet_digest_fn(snippet_id))
    }


async def read_referenced_snippet_digests(
    todos_db: TodosDb,
    slug: str,
    artifact_name: str,
    artifact_body: str,
    *,
    repo_root: str,
    snippet_digest_fn: Callable[[str], str],
) -> dict[str, str]:
    """Read digests for validator-accepted snippet refs in an artifact body."""
    _ = todos_db, slug, artifact_name
    return {
        snippet_id: digest
        for snippet_id in extract_snippet_refs(artifact_body, repo_root)
        if (digest := snippet_digest_fn(snippet_id))
    }


def extract_snippet_refs(artifact_body: str, project_root: str) -> list[str]:
    """Extract canonical snippet IDs from validator-accepted inline @ references."""
    refs: set[str] = set()
    for match in _INLINE_REF_RE.finditer(artifact_body):
        ref = match.group(0)
        if ref.startswith("@docs/"):
            snippet_id = _project_ref_to_id(ref[len("@docs/") :])
        else:
            snippet_id = _global_ref_to_id(ref)
        if snippet_id:
            refs.add(snippet_id)
    return sorted(refs)


def _state_key_for_artifact(artifact_name: str) -> str | None:
    return _ARTIFACT_TO_STATE_KEY.get(artifact_name)


def _entry(writer: StateWriter, key: str) -> ArtifactEntry:
    return cast(ArtifactEntry, getattr(writer.state.artifacts, key))


def _current_upstream_digests(writer: StateWriter, key: str) -> dict[str, str]:
    return {
        upstream_key: getattr(writer.state.artifacts, upstream_key).digest
        for upstream_key in upstream_keys_for(writer.state.kind, key)
    }


def _clear_rewrite_drift_state(writer: StateWriter, artifact_name: str) -> None:
    key = _state_key_for_artifact(artifact_name)
    if key is None:
        return
    writer.state.approvals.drift_reviewed.pop(artifact_name, None)
    writer.state.approvals.drift_reviewed.pop(key, None)
    review_field = _ARTIFACT_REVIEW_FIELDS.get(key)
    if review_field:
        getattr(writer.state, review_field).cleared_by_substantive_drift = False
    if key == STATE_KEY_IMPLEMENTATION_PLAN:
        writer.state.artifacts.implementation_plan.seeded = False


def _project_ref_to_id(rel_ref: str) -> str:
    if not rel_ref.endswith(".md"):
        return ""
    return rel_ref.removesuffix(".md")


def _global_ref_to_id(ref: str) -> str:
    raw = ref.removeprefix("@")
    path = Path(raw).expanduser()
    roots = (GLOBAL_DOCS_DIR, DEFAULT_TELECLAUDE_HOME / "docs")
    for root in roots:
        expanded_root = root.expanduser()
        for candidate_path, candidate_root in ((path, expanded_root), (path.resolve(), expanded_root.resolve())):
            try:
                rel = candidate_path.relative_to(candidate_root)
            except (ValueError, OSError):
                continue
            if rel.suffix != ".md":
                return ""
            return str(rel.with_suffix(""))
    return ""


def _snippet_ids_delivered_by(slug: str) -> list[str]:
    ids: set[str] = set()
    for index_path in (Path.cwd() / "docs" / "project" / "index.yaml", GLOBAL_DOCS_DIR / "index.yaml"):
        ids.update(_snippet_ids_delivered_by_from_index(index_path, slug))
    return sorted(ids)


def _snippet_ids_delivered_by_from_index(index_path: Path, slug: str) -> set[str]:
    if not index_path.exists():
        return set()
    try:
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    if not isinstance(payload, dict):
        return set()
    snippets = payload.get("snippets")
    if not isinstance(snippets, list):
        return set()
    ids: set[str] = set()
    for item in snippets:
        if not isinstance(item, dict):
            continue
        snippet_id = item.get("id")
        delivered_by = item.get("delivered_by")
        if isinstance(snippet_id, str) and isinstance(delivered_by, list) and slug in delivered_by:
            ids.add(snippet_id)
    return ids
