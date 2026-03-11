"""Enrichment writer and merge module for telec init.

Turns AI analysis output into schema-valid project doc snippets under docs/project/.
Handles idempotent re-analysis with human-edit preservation.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

import frontmatter
import yaml

from teleclaude.constants import TAXONOMY_TYPES

logger = logging.getLogger(__name__)


RefreshResult = Literal["created", "updated", "unchanged"]


class SnippetMetadata(TypedDict, total=False):
    """Metadata for a generated snippet. All fields are optional; type and scope default to
    taxonomy name and 'project' respectively when omitted."""

    type: str
    scope: str
    description: str
    generated_at: str


class AnalysisMetadata(TypedDict):
    """Metadata persisted in .telec-init-meta.yaml."""

    last_analyzed_at: str
    analyzed_by: str
    files_analyzed: int
    snippets_generated: list[str]
    snippets_preserved: list[str]


# Marker that separates auto-generated content from human additions.
HUMAN_MARKER = "<!-- human -->"

# Frontmatter key that identifies auto-generated snippets.
GENERATED_BY_KEY = "generated_by"
GENERATED_BY_VALUE = "telec-init"

# Metadata file name persisted in project root.
META_FILENAME = ".telec-init-meta.yaml"

# Valid snippet ID pattern: project/{taxonomy}/{slug}
_SNIPPET_ID_RE = re.compile(r"^project/(" + "|".join(TAXONOMY_TYPES) + r")/[a-z][a-z0-9-]*$")

# Baseline taxonomy directories ensured by the writer.
_BASELINE_DIRS = ("design", "policy", "spec")

# Required keys in .telec-init-meta.yaml for a valid AnalysisMetadata.
_REQUIRED_META_KEYS = frozenset({"last_analyzed_at", "analyzed_by", "files_analyzed", "snippets_generated", "snippets_preserved"})


def validate_snippet_id(snippet_id: str) -> bool:
    """Check whether a snippet ID conforms to the project/{taxonomy}/{slug} pattern."""
    return bool(_SNIPPET_ID_RE.match(snippet_id))


def snippet_id_to_path(project_root: Path, snippet_id: str) -> Path:
    """Convert a snippet ID to its filesystem path under docs/project/.

    Raises:
        ValueError: If snippet_id does not contain exactly three slash-separated parts.
    """
    parts = snippet_id.split("/", 2)  # ['project', taxonomy, slug]
    if len(parts) != 3:
        raise ValueError(f"Snippet ID must have 3 parts (project/taxonomy/slug), got: {snippet_id!r}")
    return project_root / "docs" / parts[0] / parts[1] / f"{parts[2]}.md"


def ensure_taxonomy_directories(project_root: Path, snippet_ids: list[str]) -> None:
    """Create taxonomy directories implied by the snippet IDs, plus baseline dirs."""
    docs_project = project_root / "docs" / "project"
    for base_dir in _BASELINE_DIRS:
        (docs_project / base_dir).mkdir(parents=True, exist_ok=True)
    for sid in snippet_ids:
        if validate_snippet_id(sid):
            path = snippet_id_to_path(project_root, sid)
            path.parent.mkdir(parents=True, exist_ok=True)


def write_snippet(
    project_root: Path,
    snippet_id: str,
    content: str,
    metadata: SnippetMetadata,
) -> Path:
    """Write a schema-valid snippet under docs/project/.

    Args:
        project_root: Project root directory.
        snippet_id: Must match project/{taxonomy}/{slug}.
        content: Markdown body (without frontmatter).
        metadata: Optional metadata fields (type, scope, description, generated_at); defaults are derived from snippet_id.

    Returns:
        Path to the written file.

    Raises:
        ValueError: If snippet_id is invalid or would escape docs/project/.
    """
    if not validate_snippet_id(snippet_id):
        raise ValueError(f"Invalid snippet ID: {snippet_id}")

    file_path = snippet_id_to_path(project_root, snippet_id)

    # Safety: ensure the resolved path is under docs/project/
    docs_project = (project_root / "docs" / "project").resolve()
    if not file_path.resolve().is_relative_to(docs_project):
        raise ValueError(f"Snippet path escapes docs/project/: {file_path}")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(_render_snippet(snippet_id, content, metadata), encoding="utf-8")
    return file_path


def read_existing_snippets(project_root: Path) -> dict[str, Path]:
    """Find existing auto-generated snippets by checking for generated_by marker.

    Returns:
        Dict mapping snippet ID to file path for auto-generated snippets.
    """
    docs_project = project_root / "docs" / "project"
    if not docs_project.exists():
        return {}

    result: dict[str, Path] = {}
    for md_file in sorted(docs_project.rglob("*.md")):
        if md_file.name in ("index.md", "baseline.md"):
            continue
        try:
            post = frontmatter.load(md_file)
        except Exception as exc:
            logger.warning("Skipping unreadable snippet %s: %s", md_file, exc)
            continue
        meta = post.metadata or {}
        if meta.get(GENERATED_BY_KEY) == GENERATED_BY_VALUE:
            sid = meta.get("id")
            if isinstance(sid, str):
                result[sid] = md_file
    return result


def merge_snippet(existing_content: str, generated_content: str) -> str:
    """Merge generated content with existing, preserving human-authored sections.

    Human content after the <!-- human --> marker is preserved verbatim.
    Everything before the marker is replaced with the new generated content.
    """
    if HUMAN_MARKER not in existing_content:
        return generated_content

    # Split existing at the human marker
    _, human_section = existing_content.split(HUMAN_MARKER, 1)

    # Ensure the generated content ends with a newline before the marker
    gen = generated_content.rstrip("\n")
    return f"{gen}\n\n{HUMAN_MARKER}{human_section}"


def refresh_snippet(
    project_root: Path,
    snippet_id: str,
    content: str,
    metadata: SnippetMetadata,
) -> RefreshResult:
    """Write or merge a snippet, skipping unchanged files.

    Returns:
        'created' if the file was new,
        'updated' if content changed and was rewritten,
        'unchanged' if the merged output matches what is already on disk.

    Raises:
        ValueError: If snippet_id is invalid.
    """
    if not validate_snippet_id(snippet_id):
        raise ValueError(f"Invalid snippet ID: {snippet_id}")

    file_path = snippet_id_to_path(project_root, snippet_id)

    if not file_path.exists():
        write_snippet(project_root, snippet_id, content, metadata)
        return "created"

    existing_content = file_path.read_text(encoding="utf-8")

    # Preserve the existing generated_at so unchanged content compares equal.
    try:
        existing_post = frontmatter.loads(existing_content)
        existing_ts = existing_post.metadata.get("generated_at")
    except Exception as exc:
        logger.debug("Could not parse frontmatter for timestamp in %s: %s", file_path, exc)
        existing_ts = None

    compare_meta: SnippetMetadata = {**metadata}
    if isinstance(existing_ts, str):
        compare_meta["generated_at"] = existing_ts

    merged_body = merge_snippet(existing_content, _render_snippet(snippet_id, content, compare_meta))

    if merged_body == existing_content:
        return "unchanged"

    # Actual write uses a fresh timestamp.
    file_path.write_text(
        merge_snippet(existing_content, _render_snippet(snippet_id, content, metadata)),
        encoding="utf-8",
    )
    return "updated"


def _render_snippet(snippet_id: str, content: str, metadata: SnippetMetadata) -> str:
    """Render a snippet to its full text (frontmatter + body) without writing to disk."""
    fm = {
        "id": snippet_id,
        "type": metadata.get("type", snippet_id.split("/")[1]),
        "scope": metadata.get("scope", "project"),
        "description": metadata.get("description", ""),
        GENERATED_BY_KEY: GENERATED_BY_VALUE,
        "generated_at": metadata.get(
            "generated_at",
            datetime.now(UTC).isoformat(),
        ),
    }
    post = frontmatter.Post(content, **fm)
    return frontmatter.dumps(post) + "\n"


def write_metadata(
    project_root: Path,
    *,
    files_analyzed: int,
    snippets_generated: list[str],
    snippets_preserved: list[str],
) -> Path:
    """Persist .telec-init-meta.yaml with analysis run metadata."""
    meta_path = project_root / META_FILENAME
    payload = {
        "last_analyzed_at": datetime.now(UTC).isoformat(),
        "analyzed_by": GENERATED_BY_VALUE,
        "files_analyzed": files_analyzed,
        "snippets_generated": sorted(snippets_generated),
        "snippets_preserved": sorted(snippets_preserved),
    }
    meta_path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return meta_path


def read_metadata(project_root: Path) -> AnalysisMetadata | None:
    """Read .telec-init-meta.yaml if it exists."""
    meta_path = project_root / META_FILENAME
    if not meta_path.exists():
        return None
    try:
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("Malformed metadata in %s: expected dict, got %s", meta_path, type(data).__name__)
            return None
        missing = _REQUIRED_META_KEYS - data.keys()
        if missing:
            logger.warning("Malformed metadata in %s: missing keys %s", meta_path, sorted(missing))
            return None
        return data  # type: ignore[return-value]
    except Exception as exc:
        logger.warning("Could not read analysis metadata from %s: %s", meta_path, exc)
        return None
