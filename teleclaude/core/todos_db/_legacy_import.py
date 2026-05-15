"""Legacy markdown todo import during TodosDb bootstrap."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_DESIGN_SPEC,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_TEST_SPECS,
)
from teleclaude.slug import normalize_slug, validate_slug
from teleclaude.types.todos import DorState, TodoState

logger = get_logger(__name__)

_LEGACY_MARKER_FILES = ("roadmap.md", "icebox.md", "delivered.md", "bugs.md")
_ARTIFACT_STATE_FIELDS = {
    ARTIFACT_INPUT: "input",
    ARTIFACT_REQUIREMENTS: "requirements",
    ARTIFACT_TEST_SPECS: "test_specs",
    ARTIFACT_IMPLEMENTATION_PLAN: "implementation_plan",
    "art": "art",
    "visuals": "visuals",
    ARTIFACT_DESIGN_SPEC: "design_spec",
}
_ROADMAP_LINE_RE = re.compile(
    r"^- \[(?P<marker>[^\]]+)\]\s+"
    r"(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)"
    r"(?:\s*(?:-|—)\s*(?P<description>.*))?$"
)
_BUG_LINE_RE = re.compile(
    r"^- \[(?P<marker>[ xX])\]\s+\*\*(?P<title>[^*]+)\*\*"
    r"\s*(?:-|—)\s*(?P<description>.*)$"
)
_TRAILING_FOLDER_REF_RE = re.compile(r"\s*\(`?todos/[^)]*\)\s*$")


@dataclass(frozen=True)
class LegacyImportSummary:
    """Counts for one bootstrap-time legacy import."""

    roadmap_rows: int
    state_rows: int
    artifact_rows: int
    version_rows: int


@dataclass(frozen=True)
class _LegacyEntry:
    slug: str
    status: str
    marker: str
    description: str
    kind: str
    delivered_at: str | None = None
    delivered_commit: str | None = None


def maybe_auto_import_legacy_markdown_todos(db_path: str) -> LegacyImportSummary | None:
    """Import legacy markdown todos on first bootstrap of an empty DB."""
    project_root = _project_root_from_db_path(Path(db_path))
    if project_root is None:
        return None

    todos_dir = project_root / "todos"
    if not _has_legacy_markers(todos_dir):
        return None

    conn = sqlite3.connect(db_path)
    try:
        if not _database_is_empty(conn):
            return None
        summary = _import_legacy_markdown_todos(conn, todos_dir)
        if summary is None:
            return None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "Auto-imported legacy markdown todos from %s: roadmap=%d state=%d artifacts=%d versions=%d",
        todos_dir,
        summary.roadmap_rows,
        summary.state_rows,
        summary.artifact_rows,
        summary.version_rows,
    )
    return summary


def _project_root_from_db_path(db_path: Path) -> Path | None:
    if db_path.name != "todos.db":
        return None
    teleclaude_dir = db_path.parent
    if teleclaude_dir.name != ".teleclaude":
        return None
    return teleclaude_dir.parent


def _has_legacy_markers(todos_dir: Path) -> bool:
    if not todos_dir.is_dir():
        return False
    return any((todos_dir / name).is_file() for name in _LEGACY_MARKER_FILES)


def _database_is_empty(conn: sqlite3.Connection) -> bool:
    for table in ("roadmap", "todo_state", "todo_artifacts"):
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # guard: raw-sql
        if row and int(row[0]) > 0:
            return False
    return True


def _import_legacy_markdown_todos(conn: sqlite3.Connection, todos_dir: Path) -> LegacyImportSummary | None:
    folder_artifacts = _collect_folder_artifacts(todos_dir)
    seen_slugs: set[str] = set()
    entries: list[_LegacyEntry] = []
    entries.extend(_parse_roadmap_index(todos_dir / "roadmap.md", status="active", seen_slugs=seen_slugs))
    entries.extend(_parse_roadmap_index(todos_dir / "icebox.md", status="icebox", seen_slugs=seen_slugs))
    entries.extend(_parse_delivered_index(todos_dir / "delivered.md", seen_slugs=seen_slugs))
    entries.extend(_parse_bug_index(todos_dir / "bugs.md", seen_slugs=seen_slugs))
    if not entries:
        return None

    now = datetime.now(UTC).isoformat()
    summary = LegacyImportSummary(roadmap_rows=0, state_rows=0, artifact_rows=0, version_rows=0)
    artifact_targets: dict[str, str] = {}
    position = 1

    for entry in entries:
        row_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO roadmap "
            "(id, slug, position, group_slug, description, status, "
            "delivered_at, delivered_commit, children, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                entry.slug,
                position,
                None,
                entry.description or None,
                entry.status,
                entry.delivered_at,
                entry.delivered_commit,
                None,
                now,
                now,
            ),
        )
        summary = LegacyImportSummary(
            roadmap_rows=summary.roadmap_rows + 1,
            state_rows=summary.state_rows,
            artifact_rows=summary.artifact_rows,
            version_rows=summary.version_rows,
        )
        position += 1

        if entry.status != "delivered":
            state = _build_state(
                kind=entry.kind, marker=entry.marker, artifacts=folder_artifacts.get(entry.slug, {}), now=now
            )
            conn.execute(
                "INSERT INTO todo_state (id, slug, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (row_id, entry.slug, json.dumps(state, default=str), now, now),
            )
            summary = LegacyImportSummary(
                roadmap_rows=summary.roadmap_rows,
                state_rows=summary.state_rows + 1,
                artifact_rows=summary.artifact_rows,
                version_rows=summary.version_rows,
            )
            artifact_targets[entry.slug] = row_id
        elif entry.slug not in artifact_targets:
            artifact_targets[entry.slug] = row_id

    for slug, row_id in artifact_targets.items():
        artifacts = folder_artifacts.get(slug)
        if not artifacts:
            continue
        for name, content in artifacts.items():
            digest = _sha256(content)
            conn.execute(
                "INSERT INTO todo_artifacts (id, slug, name, content, digest, updated_by, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row_id, slug, name, content, digest, "legacy-import", now),
            )
            conn.execute(
                "INSERT INTO todo_artifact_versions (id, slug, name, content, digest, updated_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row_id, slug, name, content, digest, "legacy-import", now),
            )
            summary = LegacyImportSummary(
                roadmap_rows=summary.roadmap_rows,
                state_rows=summary.state_rows,
                artifact_rows=summary.artifact_rows + 1,
                version_rows=summary.version_rows + 1,
            )

    return summary


def _collect_folder_artifacts(todos_dir: Path) -> dict[str, dict[str, str]]:
    artifacts: dict[str, dict[str, str]] = {}
    for entry in sorted(todos_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        artifact_map: dict[str, str] = {}
        for artifact_path in sorted(entry.iterdir()):
            if artifact_path.is_file() and artifact_path.suffix == ".md":
                artifact_map[artifact_path.stem] = artifact_path.read_text(encoding="utf-8")
        if artifact_map:
            artifacts[entry.name] = artifact_map
    return artifacts


def _parse_roadmap_index(path: Path, *, status: str, seen_slugs: set[str]) -> list[_LegacyEntry]:
    if not path.is_file():
        return []

    entries: list[_LegacyEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        match = _ROADMAP_LINE_RE.match(line)
        if match is None:
            continue
        slug = match.group("slug")
        if not _record_slug(slug, seen_slugs):
            continue
        description = _clean_description(match.group("description") or "")
        entries.append(
            _LegacyEntry(
                slug=slug,
                status=status,
                marker=(match.group("marker") or "").strip(),
                description=description,
                kind="todo",
            )
        )
    return entries


def _parse_delivered_index(path: Path, *, seen_slugs: set[str]) -> list[_LegacyEntry]:
    if not path.is_file():
        return []

    entries: list[_LegacyEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "|" not in stripped:
            continue
        parts = [part.strip() for part in stripped.strip("|").split("|")]
        if len(parts) < 2:
            continue
        slug = parts[1]
        if not _record_slug(slug, seen_slugs):
            continue
        delivered_at = parts[0] or None
        description_parts = parts[2:]
        delivered_commit: str | None = None
        if len(description_parts) >= 2 and description_parts[-1].startswith("done/"):
            delivered_commit = _non_empty_value(description_parts[-2])
            description_parts = description_parts[:-2]
        description = " | ".join(part for part in description_parts if part and part.lower() != "delivered").strip()
        entries.append(
            _LegacyEntry(
                slug=slug,
                status="delivered",
                marker="x",
                description=description,
                kind="todo",
                delivered_at=delivered_at,
                delivered_commit=delivered_commit,
            )
        )
    return entries


def _parse_bug_index(path: Path, *, seen_slugs: set[str]) -> list[_LegacyEntry]:
    if not path.is_file():
        return []

    entries: list[_LegacyEntry] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        match = _BUG_LINE_RE.match(line)
        if match is None:
            continue
        marker = (match.group("marker") or "").strip().lower()
        title = (match.group("title") or "").strip()
        if not title:
            continue
        slug = _unique_bug_slug(f"fix-{normalize_slug(title)}", seen_slugs)
        description = _clean_description(match.group("description") or title)
        entries.append(
            _LegacyEntry(
                slug=slug,
                status="delivered" if marker == "x" else "active",
                marker=marker,
                description=description,
                kind="bug",
            )
        )
    return entries


def _unique_bug_slug(base: str, seen_slugs: set[str]) -> str:
    slug = base or "fix-bug"
    candidate = slug
    counter = 2
    while candidate in seen_slugs:
        candidate = f"{slug}-{counter}"
        counter += 1
    seen_slugs.add(candidate)
    return candidate


def _record_slug(slug: str, seen_slugs: set[str]) -> bool:
    try:
        validate_slug(slug)
    except ValueError:
        logger.warning("Skipping legacy todo entry with invalid slug: %s", slug)
        return False
    if slug in seen_slugs:
        logger.warning("Skipping duplicate legacy todo slug during import: %s", slug)
        return False
    seen_slugs.add(slug)
    return True


def _clean_description(description: str) -> str:
    return _TRAILING_FOLDER_REF_RE.sub("", description).strip()


# guard: loose-dict - TodoState.model_dump emits heterogeneous JSON payload values by design.
def _build_state(*, kind: str, marker: str, artifacts: dict[str, str], now: str) -> dict[str, object]:
    state = TodoState.defaults()
    state.kind = kind

    for artifact_name, content in artifacts.items():
        field_name = _ARTIFACT_STATE_FIELDS.get(artifact_name)
        if field_name is None:
            continue
        artifact_state = getattr(state.artifacts, field_name)
        artifact_state.digest = _sha256(content)
        artifact_state.produced_at = now

    if marker == ">":
        state.phase = "in_progress"
    elif marker == ".":
        state.dor = DorState(last_assessed_at=now, score=8, status="pass", schema_version=1, blockers=[])
        if kind == "bug":
            state.requirements_review.verdict = "skipped"
            state.test_spec_review.verdict = "skipped"
            state.plan_review.verdict = "skipped"
        else:
            state.requirements_review.verdict = "approve" if ARTIFACT_REQUIREMENTS in artifacts else "skipped"
            state.test_spec_review.verdict = "skipped"
            state.plan_review.verdict = "approve" if ARTIFACT_IMPLEMENTATION_PLAN in artifacts else "skipped"
            if ARTIFACT_IMPLEMENTATION_PLAN in artifacts:
                state.approvals.plan_approved.approved = True
                state.approvals.plan_approved.approved_at = now
        if not state.artifacts.test_specs.produced_at:
            state.artifacts.test_specs.produced_at = now

    return state.model_dump(mode="json")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _non_empty_value(value: str) -> str | None:
    stripped = value.strip()
    if stripped in {"", "-"}:
        return None
    return stripped
