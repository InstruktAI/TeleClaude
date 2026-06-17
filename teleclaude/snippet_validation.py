"""Validate snippet IDs, paths, and inline references against the taxonomy."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from teleclaude.constants import DOMAIN_SCOPES, TAXONOMY_TYPES
from teleclaude.paths import GLOBAL_SNIPPETS_DIR

ALLOWED_TAXONOMIES = frozenset(TAXONOMY_TYPES)
_DOMAINS = frozenset(DOMAIN_SCOPES)


class SnippetTaxonomy(StrEnum):
    """Closed taxonomy values for documentation snippets."""

    PRINCIPLE = "principle"
    CONCEPT = "concept"
    POLICY = "policy"
    PROCEDURE = "procedure"
    DESIGN = "design"
    SPEC = "spec"
    ADR = "adr"


class SnippetScope(StrEnum):
    """Closed scope values materialized in the snippet index."""

    GLOBAL = "global"
    PROJECT = "project"


@dataclass(frozen=True)
class SnippetIdParts:
    """Parsed components of a snippet ID."""

    scope: str
    taxonomy: str
    rest: str

    def value(self) -> str:
        """Return the full snippet ID string."""
        if self.rest:
            return f"{self.scope}/{self.taxonomy}/{self.rest}"
        return f"{self.scope}/{self.taxonomy}"


@dataclass(frozen=True)
class SnippetClassification:
    """Path-derived snippet classification materialized by the index."""

    id: str
    type: SnippetTaxonomy
    scope: SnippetScope
    domain: str


def load_domains(_project_root: Path) -> set[str]:
    """Return the canonical domain scopes from constants."""
    return set(_DOMAINS)


def _split_parts(value: str) -> tuple[list[str], bool]:
    raw = value.strip().strip("/")
    if not raw:
        return [], True
    parts = raw.split("/")
    has_empty = any(not part for part in parts)
    return parts, has_empty


def _allowed_scopes(domains: Iterable[str]) -> set[str]:
    return {"general", "project", *domains}


def validate_snippet_id_format(
    value: str,
    *,
    domains: Iterable[str],
) -> tuple[SnippetIdParts | None, str | None]:
    """Validate a snippet ID string and return parsed parts or an error code."""
    if not value.strip():
        return None, "missing"
    raw = value.strip()
    if raw.startswith("@"):
        raw = raw[1:]
    if raw.endswith(".md"):
        return None, "looks_like_path"
    if raw.startswith("docs/") or raw.startswith("~") or raw.startswith("/"):
        return None, "looks_like_path"
    parts, has_empty = _split_parts(raw)
    if has_empty:
        return None, "empty_segment"
    if len(parts) < 2:
        return None, "missing_taxonomy"
    scope, taxonomy = parts[0], parts[1]
    if scope not in _allowed_scopes(domains):
        return None, "invalid_scope"
    if taxonomy not in ALLOWED_TAXONOMIES:
        return None, "invalid_taxonomy"
    rest = "/".join(parts[2:])
    return SnippetIdParts(scope=scope, taxonomy=taxonomy, rest=rest), None


def companion_slug(path: Path) -> str | None:
    """Sole owner of the companion filename grammar.

    A companion is ``<stem>.<slug>.md`` — a sibling of an existing ``<stem>.md``.
    Snippet stems and slugs are kebab-case (dot-free), so a companion is the only
    ``.md`` file whose name carries a dot before the extension; the segment before
    that final dot names the parent stem, the segment after names the delivering
    slug. Returns the slug when ``path`` is a companion, else ``None``. A companion
    is the full next version of its parent and deliberately shares the parent's id,
    so id↔path checks exempt it.
    """
    base = path.name[:-3] if path.name.endswith(".md") else path.name
    if "." not in base:
        return None
    stem, slug = base.rsplit(".", 1)
    if not slug or not (path.parent / f"{stem}.md").exists():
        return None
    return slug


def companion_parent(path: Path) -> Path | None:
    """The parent ``<stem>.md`` of a companion ``<stem>.<slug>.md``, or ``None``."""
    if companion_slug(path) is None:
        return None
    stem = path.name[:-3].rsplit(".", 1)[0]
    return path.parent / f"{stem}.md"


def is_companion(path: Path) -> bool:
    """Whether ``path`` is a companion ``<stem>.<slug>.md`` (see :func:`companion_slug`)."""
    return companion_slug(path) is not None


def expected_snippet_id_for_path(
    path: Path,
    *,
    project_root: Path,
    domains: Iterable[str],
) -> tuple[str | None, str | None]:
    """Derive the expected snippet ID from a filesystem path."""
    try:
        rel = path.resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        return None, "not_under_project_root"

    parts = rel.parts
    if len(parts) < 2 or parts[0] != "docs":
        return None, "not_under_docs_root"

    if parts[1] == "third-party":
        if path.name == "index.md":
            return None, None
        return None, None

    if parts[1] == "global":
        return _expected_from_global(parts, path, domains)

    if parts[1] == "project":
        return _expected_from_project(parts, path)

    return None, "invalid_docs_root"


def derive_snippet_classification(
    path: Path,
    *,
    project_root: Path,
    domains: Iterable[str],
) -> tuple[SnippetClassification | None, str | None]:
    """Derive snippet classification from its filesystem path."""
    id_path = companion_parent(path) or path
    snippet_id, id_error = expected_snippet_id_for_path(id_path, project_root=project_root, domains=domains)
    if id_error:
        return None, id_error
    if not snippet_id:
        return None, "not_a_snippet"

    taxonomy, taxonomy_error = _taxonomy_from_path(id_path, project_root=project_root)
    if taxonomy_error:
        return None, taxonomy_error
    if taxonomy is None:
        return None, "missing_taxonomy"

    scope, scope_error = _index_scope_from_path(id_path, project_root=project_root)
    if scope_error:
        return None, scope_error
    if scope is None:
        return None, "missing_scope"

    return (
        SnippetClassification(
            id=snippet_id,
            type=taxonomy,
            scope=scope,
            domain=snippet_id.split("/", 1)[0],
        ),
        None,
    )


def _taxonomy_from_path(
    path: Path,
    *,
    project_root: Path,
) -> tuple[SnippetTaxonomy | None, str | None]:
    try:
        rel = path.resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        return None, "not_under_project_root"
    parts = rel.parts
    raw_taxonomy: str | None = None
    if len(parts) >= 4 and parts[0] == "docs" and parts[1] == "global":
        raw_taxonomy = parts[3]
    elif len(parts) >= 3 and parts[0] == "docs" and parts[1] == "project":
        raw_taxonomy = parts[2]
    if raw_taxonomy is None:
        return None, "missing_taxonomy"
    try:
        return SnippetTaxonomy(raw_taxonomy), None
    except ValueError:
        return None, "invalid_taxonomy"


def _index_scope_from_path(
    path: Path,
    *,
    project_root: Path,
) -> tuple[SnippetScope | None, str | None]:
    try:
        rel = path.resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        return None, "not_under_project_root"
    parts = rel.parts
    if len(parts) < 2 or parts[0] != "docs":
        return None, "not_under_docs_root"
    if parts[1] == "global":
        return SnippetScope.GLOBAL, None
    if parts[1] == "project":
        return SnippetScope.PROJECT, None
    return None, "invalid_docs_root"


def _expected_from_global(
    parts: tuple[str, ...],
    path: Path,
    domains: Iterable[str],
) -> tuple[str | None, str | None]:
    if len(parts) < 3:
        return None, "missing_global_scope"
    scope_segment = parts[2]
    # Global root baseline: docs/global/baseline.md / baseline-progressive.md
    if path.name.startswith("baseline") and path.name.endswith(".md") and path.parent.name == "global":
        return None, None
    # Domain-level baseline: docs/global/<domain>/baseline.md (e.g.
    # software-development, creative). Treated as a manifest — no frontmatter
    # required. The deploy pipeline inflates it into a real file at
    # ~/.teleclaude/docs/_baselines/<domain>.md for codex-readable consumption.
    if path.name in {"baseline.md", "baseline-progressive.md"} and path.parent.name == scope_segment:
        return None, None
    if scope_segment == "baseline":
        if len(parts) < 5:
            return None, "baseline_missing_taxonomy"
        taxonomy = parts[3]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return None, "invalid_taxonomy"
        return None, None

    scope = "general" if scope_segment == "general" else scope_segment
    if scope not in _allowed_scopes(domains):
        return None, "invalid_scope"
    if len(parts) < 5:
        return None, "missing_taxonomy"
    taxonomy = parts[3]
    if taxonomy not in ALLOWED_TAXONOMIES:
        return None, "invalid_taxonomy"
    rest = _tail(parts, 4, path)
    if not rest:
        return None, "missing_slug"
    return SnippetIdParts(scope=scope, taxonomy=taxonomy, rest=rest).value(), None


def _expected_from_project(
    parts: tuple[str, ...],
    path: Path,
) -> tuple[str | None, str | None]:
    if len(parts) < 3:
        return None, "missing_taxonomy"
    if path.name.startswith("baseline") and path.name.endswith(".md") and path.parent.name == "project":
        return None, None
    if parts[2] == "baseline":
        return None, "project_baseline_only_index"
    taxonomy = parts[2]
    if taxonomy not in ALLOWED_TAXONOMIES:
        return None, "invalid_taxonomy"
    rest = _tail(parts, 3, path)
    if not rest:
        return None, "missing_slug"
    return SnippetIdParts(scope="project", taxonomy=taxonomy, rest=rest).value(), None


def _tail(parts: tuple[str, ...], start_idx: int, path: Path) -> str:
    name = path.stem if path.suffix else parts[-1]
    tail_parts = list(parts[start_idx:-1]) + [name]
    return "/".join([p for p in tail_parts if p])


def validate_inline_ref_format(ref: str, *, domains: Iterable[str]) -> str | None:
    """Validate an inline @ref and return an error code or None if valid."""
    if not ref:
        return "missing_ref"
    if not ref.startswith("@"):
        return "missing_at_prefix"
    if ref.startswith("@docs/"):
        return _validate_project_ref(ref[len("@docs/") :], domains)
    for abs_prefix in _global_ref_prefixes():
        if ref.startswith(abs_prefix):
            return _validate_global_ref(ref[len(abs_prefix) :], domains)
    return "invalid_prefix"


def _global_ref_prefixes() -> tuple[str, ...]:
    """Return valid absolute prefixes for global documentation refs."""
    configured_prefix = f"@{GLOBAL_SNIPPETS_DIR}/"
    home_prefix = f"@{Path.home()}/.teleclaude/docs/"
    tilde_prefix = "@~/.teleclaude/docs/"
    return tuple(dict.fromkeys((configured_prefix, home_prefix, tilde_prefix)))


def snippet_body_digest(snippet_id: str) -> str:
    """Return SHA256 of snippet content, excluding delivered_by frontmatter churn."""
    snippet_path = _resolve_snippet_path(snippet_id)
    if snippet_path is None:
        return ""
    try:
        content = snippet_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    filtered = _strip_delivered_by_frontmatter(content)
    return hashlib.sha256(filtered.encode("utf-8")).hexdigest()


def _resolve_snippet_path(snippet_id: str) -> Path | None:
    """Resolve a canonical snippet ID through project then global snippet indexes."""
    project_index = Path.cwd() / "docs" / "project" / "index.yaml"
    global_index = GLOBAL_SNIPPETS_DIR / "index.yaml"
    for index_path in (project_index, global_index):
        resolved = _resolve_snippet_path_from_index(snippet_id, index_path)
        if resolved is not None:
            return resolved
    return None


def _resolve_snippet_path_from_index(snippet_id: str, index_path: Path) -> Path | None:
    if not index_path.exists():
        return None
    try:
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    project_root = payload.get("project_root")
    snippets = payload.get("snippets")
    if not isinstance(project_root, str) or not isinstance(snippets, list):
        return None
    root_path = Path(project_root).expanduser()
    for item in snippets:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        raw_path = item.get("path")
        if item_id != snippet_id or not isinstance(raw_path, str):
            continue
        path = Path(raw_path).expanduser()
        return path if path.is_absolute() else root_path / path
    return None


def _strip_delivered_by_frontmatter(content: str) -> str:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content
    end_idx = next((idx for idx, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end_idx is None:
        return content

    filtered_header = [lines[0]]
    skipping_delivered_by = False
    for line in lines[1:end_idx]:
        stripped = line.lstrip()
        if stripped.startswith("delivered_by:"):
            skipping_delivered_by = True
            continue
        if skipping_delivered_by:
            if _is_frontmatter_continuation(stripped):
                continue
            skipping_delivered_by = False
        filtered_header.append(line)
    filtered_header.append(lines[end_idx])
    return "".join(filtered_header + lines[end_idx + 1 :])


def _is_frontmatter_continuation(stripped_line: str) -> bool:
    if not stripped_line.strip():
        return True
    if stripped_line.startswith("-"):
        return True
    return ":" not in stripped_line


def _validate_project_ref(rel: str, domains: Iterable[str]) -> str | None:
    if rel.startswith("docs/"):
        return "nested_docs_root"
    if rel == "baseline.md":
        return None
    if rel == "project/baseline.md":
        return None
    parts, has_empty = _split_parts(rel)
    if has_empty:
        return "empty_segment"
    if len(parts) < 3:
        return "missing_segments"
    if parts[0] != "project":
        return "invalid_project_scope"
    if parts[1] == "baseline":
        if len(parts) < 4:
            return "missing_segments"
        taxonomy = parts[2]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return "invalid_taxonomy"
        if not parts[-1].endswith(".md"):
            return "missing_md_extension"
        return None
    taxonomy = parts[1]
    if taxonomy not in ALLOWED_TAXONOMIES:
        return "invalid_taxonomy"
    if not parts[-1].endswith(".md"):
        return "missing_md_extension"
    return None


def _validate_global_ref(rel: str, domains: Iterable[str]) -> str | None:
    if rel.startswith("docs/"):
        return "nested_docs_root"
    if rel == "baseline.md":
        return None
    parts, has_empty = _split_parts(rel)
    if has_empty:
        return "empty_segment"
    if len(parts) < 3:
        return "missing_segments"
    if parts[0] == "baseline":
        taxonomy = parts[1]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return "invalid_taxonomy"
    else:
        scope = "general" if parts[0] == "general" else parts[0]
        if scope not in _allowed_scopes(domains):
            return "invalid_scope"
        taxonomy = parts[1]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return "invalid_taxonomy"
    if not parts[-1].endswith(".md"):
        return "missing_md_extension"
    return None
