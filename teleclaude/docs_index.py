"""Build and manage doc snippet index.yaml files.

Handles index generation and global collision checking.
Does NOT validate — that's resource_validation.py.

Called by ``telec sync``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import NotRequired, TypedDict

import frontmatter
import yaml
from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_project_config
from teleclaude.constants import (
    SNIPPET_VISIBILITY_INTERNAL,
    SNIPPET_VISIBILITY_VALUES,
)
from teleclaude.doc_body import PLANNED_BLOCK_RE, PLANNED_CHANGE_BLOCK_RE
from teleclaude.paths import ConfigFileName
from teleclaude.required_reads import extract_required_reads as _extract_required_reads
from teleclaude.slug import normalize_slug
from teleclaude.snippet_roots import is_excluded_snippet_path, iter_snippet_roots, snippet_files
from teleclaude.snippet_validation import (
    companion_slug,
    derive_company_snippet_classification,
    derive_snippet_classification,
    is_companion,
    load_domains,
)

__all__ = ["load_domains"]

logger = get_logger(__name__)


def _teleclaude_root() -> str:
    """Return teleclaude root path with tilde (portable)."""
    return "~/.teleclaude"


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------


class SnippetEntry(TypedDict):
    """Single snippet entry in the documentation index."""

    id: str
    description: str
    type: str
    scope: str
    domain: str
    activation_trigger: str | None
    path: str
    source_project: NotRequired[str]
    visibility: NotRequired[str]
    delivered_by: NotRequired[list[str]]
    superseded_by: NotRequired[list[str]]
    needs_domain_baseline: NotRequired[bool]


class IndexPayload(TypedDict):
    """Payload for the documentation index build result."""

    project_root: str
    snippets_root: str
    snippets: list[SnippetEntry]


class ThirdPartyEntry(TypedDict):
    """Third-party doc entry - no type field (not part of taxonomy)."""

    id: str
    description: str
    scope: str
    path: str


class ThirdPartyIndexPayload(TypedDict):
    """Payload for the third-party documentation index."""

    snippets_root: str
    snippets: list[ThirdPartyEntry]


def _copy_delivered_by_metadata(entry: SnippetEntry, metadata: Mapping[str, object]) -> None:
    raw_delivered_by = metadata.get("delivered_by")
    if isinstance(raw_delivered_by, list) and all(isinstance(slug, str) for slug in raw_delivered_by):
        entry["delivered_by"] = list(raw_delivered_by)


def _copy_needs_domain_baseline_metadata(entry: SnippetEntry, metadata: Mapping[str, object]) -> None:
    raw_value = metadata.get("needs_domain_baseline")
    if isinstance(raw_value, bool):
        entry["needs_domain_baseline"] = raw_value
    elif isinstance(raw_value, str) and raw_value.strip().lower() in {"true", "false"}:
        entry["needs_domain_baseline"] = raw_value.strip().lower() == "true"


def _extract_description_from_md(file_path: Path) -> str:
    """Extract description from markdown file (first H1 title or filename)."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return file_path.stem

    # Try frontmatter first
    if text.lstrip().startswith("---"):
        try:
            post = frontmatter.loads(text)
            desc = post.metadata.get("description") if post.metadata else None
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
        except Exception:
            pass

    # Fall back to first H1 title
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            # Remove type suffix if present (e.g., "— Spec")
            if " — " in title:
                title = title.split(" — ")[0].strip()
            return title

    return file_path.stem


def write_third_party_index_yaml(third_party_root: Path, scope: str) -> Path | None:
    """Generate index.yaml for third-party docs.

    Args:
        third_party_root: Path to third-party directory (e.g., docs/third-party or ~/.teleclaude/docs/third-party)
        scope: Either "project" or "global"

    Returns:
        Path to the generated index.yaml, or None if no docs found.
    """
    if not third_party_root.exists():
        return None

    legacy_md_index = third_party_root / "index.md"
    if legacy_md_index.exists():
        legacy_md_index.unlink()

    entries: list[ThirdPartyEntry] = []
    for path in sorted(third_party_root.rglob("*.md")):
        # Build ID from relative path (e.g., "third-party/react/hooks")
        try:
            rel = path.relative_to(third_party_root).as_posix()
        except ValueError:
            continue

        # Remove .md extension for ID
        snippet_id = f"third-party/{rel}"
        if snippet_id.endswith(".md"):
            snippet_id = snippet_id[:-3]

        description = _extract_description_from_md(path)

        # Path relative to snippets_root for loading
        entry: ThirdPartyEntry = {
            "id": snippet_id,
            "description": description,
            "scope": scope,
            "path": rel,
        }
        entries.append(entry)

    index_path = third_party_root / "index.yaml"

    if not entries:
        if index_path.exists():
            index_path.unlink()
        return None

    # Build payload
    home = str(Path.home())
    root_str = str(third_party_root)
    if root_str.startswith(home):
        root_str = root_str.replace(home, "~", 1)

    payload: ThirdPartyIndexPayload = {
        "snippets_root": root_str,
        "snippets": entries,
    }

    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
        if existing == rendered:
            return index_path

    index_path.write_text(rendered, encoding="utf-8")
    return index_path


def remove_non_baseline_indexes(snippets_root: Path) -> list[str]:
    """Remove stale index.md files outside baseline/. Returns removed paths."""
    removed: list[str] = []
    for path in sorted(snippets_root.rglob("index.md")):
        if "baseline" in path.parts:
            continue
        if is_excluded_snippet_path(path, snippets_root):
            continue
        try:
            path.unlink()
            removed.append(str(path))
            logger.warning("index_removed", path=str(path))
        except Exception as exc:
            logger.warning("index_remove_failed", path=str(path), error=str(exc))
    return removed


# ---------------------------------------------------------------------------
# Required reads extraction
# ---------------------------------------------------------------------------


def extract_required_reads(content: str) -> list[str]:
    """Extract ``@`` paths from the Required Reads section."""
    refs, _ = _extract_required_reads(content)
    return refs


# ---------------------------------------------------------------------------
# Snippet root discovery
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Project config helpers
# ---------------------------------------------------------------------------


def ensure_project_config(project_root: Path) -> None:
    """Create a minimal teleclaude.yml if one does not exist.

    A freshly created project is a consumer, not a publisher: it declares no
    ``business.publishes`` (auto-declaring a domain would trip per-domain split
    detection against the real owner) and no dead ``business.domains`` map.
    """
    config_path = project_root / ConfigFileName.OVERLAY
    if config_path.exists():
        return
    config_path.write_text(
        "business: {}\n",
        encoding="utf-8",
    )


def get_project_slug(project_root: Path) -> str:
    """Return the canonical slug identifying *project_root*.

    Priority:
    1. ``config.project_slug`` when set in ``teleclaude.yml``.
    2. Slugified ``config.project_name`` when available.
    3. Slugified directory name as a final fallback.

    The slug is the machine identity used as the ``source_project`` field
    in ``index.yaml`` entries and as the cross-project prefix for snippet
    IDs (e.g., ``alpha/spec/overview``). Falling back through name and
    directory ensures projects authored before ``project_slug`` was
    required still resolve to a stable, lowercase key.
    """
    config_file = project_root / ConfigFileName.OVERLAY
    if config_file.exists():
        config = load_project_config(config_file)
        if config.project_slug:
            return config.project_slug
        if config.project_name:
            return normalize_slug(config.project_name)
    return normalize_slug(project_root.name)


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def _superseding_slugs(file_path: Path) -> list[str]:
    """Pending slugs touching this live parent, derived from the filesystem — not frontmatter.

    A slug supersedes the parent when it owns a companion ``<stem>.<slug>.md`` (full
    replacement), an in-body ``<!-- planned:slug -->`` block (additive), or an in-body
    ``<!-- planned-change:slug -->`` block (bounded replacement/removal). The index renders
    these as a ``(superseded by: …)`` suffix on the parent's line; the relationship is carried
    by the filename and the marker, so it needs no frontmatter and auto-clears on delivery.
    """
    stem = file_path.name[:-3] if file_path.name.endswith(".md") else file_path.name
    if "." in stem:
        return []  # the file itself is a companion, not a parent
    slugs: set[str] = set()
    for sibling in file_path.parent.glob(f"{stem}.*.md"):
        slug = companion_slug(sibling)
        if slug:
            slugs.add(slug)
    try:
        body = file_path.read_text(encoding="utf-8")
    except OSError:
        body = ""
    slugs.update(match.group("slug") for match in PLANNED_BLOCK_RE.finditer(body))
    slugs.update(match.group("slug") for match in PLANNED_CHANGE_BLOCK_RE.finditer(body))
    return sorted(slugs)


def _attach_superseding_slugs(entry: SnippetEntry, file_path: Path) -> None:
    slugs = _superseding_slugs(file_path)
    if slugs:
        entry["superseded_by"] = slugs


def _build_snippet_entry(
    file_path: Path,
    metadata: Mapping[str, object],
    *,
    project_root: Path,
    domains: set[str],
) -> SnippetEntry | None:
    description = metadata.get("description")
    if not isinstance(description, str):
        return None
    classification, reason = derive_snippet_classification(file_path, project_root=project_root, domains=domains)
    if classification is None:
        raise ValueError(f"Cannot derive snippet classification for {file_path}: {reason or 'unknown'}")
    try:
        relative_path = str(file_path.relative_to(project_root))
    except ValueError:
        relative_path = str(file_path)
    activation_trigger = metadata.get("activation_trigger")
    entry: SnippetEntry = {
        "id": classification.id,
        "description": description,
        "type": classification.type.value,
        "scope": classification.scope.value,
        "domain": classification.domain,
        "activation_trigger": activation_trigger if isinstance(activation_trigger, str) else None,
        "path": relative_path,
    }
    raw_visibility = metadata.get("visibility")
    if isinstance(raw_visibility, str) and raw_visibility in SNIPPET_VISIBILITY_VALUES:
        entry["visibility"] = raw_visibility
    else:
        entry["visibility"] = SNIPPET_VISIBILITY_INTERNAL
    _copy_delivered_by_metadata(entry, metadata)
    _copy_needs_domain_baseline_metadata(entry, metadata)
    _attach_superseding_slugs(entry, file_path)
    return entry


def _eligible_snippet_files(snippets_root: Path, *, include_baseline: bool) -> list[Path]:
    """Sorted snippet files for indexing, excluding companions.

    A companion ``<stem>.<slug>.md`` (sibling of an existing ``<stem>.md``) shares the
    parent's id and is the parent's pending replacement — it is never a standalone index
    entry. See ``software-development/principle/documentation-first-development`` section 10.
    """
    return sorted(f for f in snippet_files(snippets_root, include_baseline=include_baseline) if not is_companion(f))


def build_index_payload(project_root: Path, snippets_root: Path) -> IndexPayload:
    """Build the index.yaml payload for a snippet root."""
    domains = load_domains(project_root)
    remove_non_baseline_indexes(snippets_root)

    if not snippets_root.exists():
        return {"project_root": str(project_root), "snippets_root": str(snippets_root), "snippets": []}

    snippet_cache: list[tuple[Path, Mapping[str, object]]] = []
    snippets: list[SnippetEntry] = []

    try:
        rel_path = snippets_root.relative_to(project_root)
        include_baseline = str(rel_path) in ("docs/global", "agents/docs")
    except ValueError:
        include_baseline = False

    files = _eligible_snippet_files(snippets_root, include_baseline=include_baseline)
    if not files:
        return {"project_root": str(project_root), "snippets_root": str(snippets_root), "snippets": []}

    baseline_root = snippets_root / "baseline"
    for file_path in files:
        if include_baseline and baseline_root in file_path.parents:
            try:
                rel = file_path.relative_to(baseline_root).as_posix()
            except ValueError:
                rel = file_path.name
            snippet_id = f"baseline/{rel}"
            if snippet_id.endswith(".md"):
                snippet_id = snippet_id[: -len(".md")]
            snippet_type = rel.split("/", 1)[0] if "/" in rel else "principle"
            try:
                text = file_path.read_text(encoding="utf-8")
            except Exception:
                text = ""
            title_line = next(
                (line.strip() for line in text.splitlines() if line.strip().startswith("# ")),
                "",
            )
            description = title_line.lstrip("# ").strip() if title_line else snippet_id
            try:
                relative_path = str(file_path.relative_to(project_root))
            except ValueError:
                relative_path = str(file_path)
            snippets.append(
                {
                    "id": snippet_id,
                    "description": description,
                    "type": snippet_type,
                    "scope": "global",
                    "domain": "baseline",
                    "activation_trigger": None,
                    "path": relative_path,
                    "visibility": SNIPPET_VISIBILITY_INTERNAL,
                }
            )
            continue

        post = frontmatter.load(file_path)
        metadata: Mapping[str, object] = post.metadata or {}
        snippet_cache.append((file_path, metadata))

    for file_path, metadata in snippet_cache:
        entry = _build_snippet_entry(file_path, metadata, project_root=project_root, domains=domains)
        if entry is not None:
            snippets.append(entry)

    snippets.sort(key=lambda e: e["id"])

    project_slug = get_project_slug(project_root)
    for snippet in snippets:
        snippet["source_project"] = project_slug

    try:
        rel_path = snippets_root.relative_to(project_root)
        is_global = str(rel_path) in ("docs/global", "agents/docs")
    except ValueError:
        is_global = False

    if is_global:
        root = _teleclaude_root()
        snippets_root_str = f"{root}/docs"
        for snippet in snippets:
            p = snippet["path"]
            if p.startswith("docs/global/"):
                snippet["path"] = p.replace("docs/global/", "docs/", 1)
    else:
        home = str(Path.home())
        project_root_str = str(project_root)
        root = project_root_str.replace(home, "~", 1) if project_root_str.startswith(home) else project_root_str
        snippets_root_str = str(snippets_root)
        if snippets_root_str.startswith(home):
            snippets_root_str = snippets_root_str.replace(home, "~", 1)

    return {"project_root": root, "snippets_root": snippets_root_str, "snippets": snippets}


_COMPANY_AUTHORED_CLASSIFICATION_KEYS = ("id", "type", "scope", "domain")


def build_company_index_payload(company_dir: Path) -> IndexPayload:
    """Build the index.yaml payload for a company docs tree (``companies/<slug>/docs``).

    Classification is path-derived; the only authored frontmatter is ``description``
    (``visibility`` optional). A snippet that authors ``id``/``type``/``scope``/``domain``
    violates the no-authored-classification contract and fails the build loudly.
    """
    docs_root = company_dir / "docs"
    if not docs_root.exists():
        return {"project_root": str(docs_root), "snippets_root": str(docs_root), "snippets": []}

    snippets: list[SnippetEntry] = []
    for file_path in _eligible_snippet_files(docs_root, include_baseline=False):
        post = frontmatter.load(file_path)
        metadata: Mapping[str, object] = post.metadata or {}
        authored = [key for key in _COMPANY_AUTHORED_CLASSIFICATION_KEYS if key in metadata]
        if authored:
            raise ValueError(
                f"Company snippet {file_path} authors path-derived classification keys {authored}; "
                "company snippets author only 'description'."
            )
        description = metadata.get("description")
        if not isinstance(description, str):
            raise ValueError(f"Company snippet {file_path} is missing a 'description'.")
        classification, reason = derive_company_snippet_classification(file_path, company_docs_root=docs_root)
        if classification is None:
            raise ValueError(f"Cannot derive company snippet classification for {file_path}: {reason or 'unknown'}")
        raw_visibility = metadata.get("visibility")
        visibility = (
            raw_visibility
            if isinstance(raw_visibility, str) and raw_visibility in SNIPPET_VISIBILITY_VALUES
            else SNIPPET_VISIBILITY_INTERNAL
        )
        snippets.append(
            {
                "id": classification.id,
                "description": description,
                "type": classification.type.value,
                "scope": classification.scope.value,
                "domain": classification.domain,
                "activation_trigger": None,
                "path": str(file_path.relative_to(docs_root)),
                "visibility": visibility,
            }
        )

    snippets.sort(key=lambda e: e["id"])
    return {"project_root": str(docs_root), "snippets_root": str(docs_root), "snippets": snippets}


def write_company_index(company_dir: Path) -> Path:
    """Build and write the company docs index.yaml. Returns the target path."""
    docs_root = company_dir / "docs"
    target = docs_root / "index.yaml"
    payload = build_company_index_payload(company_dir)
    if not payload["snippets"]:
        if target.exists():
            target.unlink()
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    return target


def write_index_yaml(project_root: Path, snippets_root: Path) -> Path:
    """Build and write index.yaml for a snippet root. Returns the target path."""
    target = snippets_root / "index.yaml"
    # Third-party indexes are handled separately by write_third_party_index_yaml
    if "third-party" in snippets_root.parts:
        return target
    payload = build_index_payload(project_root, snippets_root)
    if not payload["snippets"]:
        if target.exists():
            target.unlink()
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == rendered:
            return target
    target.write_text(rendered, encoding="utf-8")
    return target


def build_all_indexes(project_root: Path) -> list[Path]:
    """Build index.yaml for all snippet roots. Main entry point."""
    ensure_project_config(project_root)
    roots = iter_snippet_roots(project_root)
    written: list[Path] = []
    for snippets_root in roots:
        written.append(write_index_yaml(project_root, snippets_root))

    # Generate third-party index.yaml (separate from taxonomy)
    third_party_root = project_root / "docs" / "third-party"
    third_party_index = write_third_party_index_yaml(third_party_root, scope="project")
    if third_party_index:
        written.append(third_party_index)

    return written
