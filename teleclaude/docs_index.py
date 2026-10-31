"""Build and manage doc snippet index.yaml files.

Handles index generation and global collision checking.
Does NOT validate — that's resource_validation.py.

Used by recorded-commit publication to build indexes from its source snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final, NotRequired, TypedDict, cast

import frontmatter
import yaml
from instrukt_ai_logging import get_logger

from teleclaude.config.declaration import write_declared_config
from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import ConfigKind
from teleclaude.constants import (
    SNIPPET_VISIBILITY_INTERNAL,
    SNIPPET_VISIBILITY_VALUES,
)
from teleclaude.doc_body import PLANNED_BLOCK_RE, PLANNED_CHANGE_BLOCK_RE
from teleclaude.docs_subscriptions import IndexKey, resolve_delivery_settings
from teleclaude.entry_declarations import (
    DispatchPayload,
    EntryKey,
    ParameterPayload,
    entry_payload,
    parse_entry_declarations,
)
from teleclaude.paths import ConfigFileName
from teleclaude.required_reads import extract_required_reads as _extract_required_reads
from teleclaude.slug import normalize_slug
from teleclaude.snippet_roots import (
    is_excluded_snippet_path,
    iter_snippet_roots,
    snippet_files,
)
from teleclaude.snippet_scope import SnippetScope
from teleclaude.snippet_validation import (
    DOCS_HALVES,
    TierAuthoredClassificationKey,
    companion_slug,
    derive_snippet_classification,
    derive_tier_snippet_classification,
    is_companion,
    is_half_root_baseline_manifest,
    load_domains,
    read_declared_project_slug,
)

__all__ = ["load_domains", "reroot_index_document"]

logger = get_logger(__name__)

_EMPTY_PROJECT_CONFIG_DOCUMENT: Final[Mapping[str, object]] = {"business": {}}
_INDEX_PROJECT_ROOT_FIELD: Final = "project_root"
_INDEX_FILENAME: Final = "index.yaml"
_DOCS_DIRNAME: Final = "docs"
_LOCAL_HALF: Final = "local"
_INDEX_SNIPPETS_ROOT_FIELD: Final = "snippets_root"
_INVALID_INDEX_DOCUMENT_MESSAGE: Final = (
    "Index document must contain a string snippets_root field and an optional string project_root field."
)
_UNSUPPORTED_TIER_KIND: Final = "Cannot build a tier index for home kind {kind}"


def _teleclaude_root() -> str:
    """Return teleclaude root path with tilde (portable)."""
    return "~/.teleclaude"


def _display_home_path(path: Path) -> str:
    """Render a path below the current user's home with a portable tilde prefix."""
    expanded_path = path.expanduser()
    try:
        relative_path = expanded_path.relative_to(Path.home())
    except ValueError:
        return str(expanded_path)
    return f"~/{relative_path.as_posix()}" if relative_path.parts else "~"


def reroot_index_document(index_document: str, source_root: Path, target_root: Path) -> str:
    """Re-express index roots beneath source_root at target_root, preserving unrelated metadata."""
    parsed: object = yaml.safe_load(index_document)
    if (
        not isinstance(parsed, dict)
        or not isinstance(parsed.get(_INDEX_SNIPPETS_ROOT_FIELD), str)
        or (_INDEX_PROJECT_ROOT_FIELD in parsed and not isinstance(parsed.get(_INDEX_PROJECT_ROOT_FIELD), str))
    ):
        raise ValueError(_INVALID_INDEX_DOCUMENT_MESSAGE)
    payload = cast(IndexDocument, parsed)
    source_path = source_root.expanduser().resolve()
    target_path = target_root.expanduser().resolve()
    for key in (_INDEX_PROJECT_ROOT_FIELD, _INDEX_SNIPPETS_ROOT_FIELD):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        index_path = Path(value).expanduser().resolve()
        try:
            relative_path = index_path.relative_to(source_path)
        except ValueError:
            continue
        payload[key] = _display_home_path(target_path / relative_path)
    return str(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False))


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
    subscriptions: NotRequired[list[str]]
    subscription_home: NotRequired[str]
    subscription_identity: NotRequired[str]
    subscription_attendance: NotRequired[str]
    event_delivery: NotRequired[str]
    interruptible: NotRequired[bool]
    role: NotRequired[str]
    parameters: NotRequired[list[ParameterPayload]]
    dispatch: NotRequired[DispatchPayload]


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


class IndexDocument(TypedDict):
    """Serialized project or third-party index with shared root fields."""

    project_root: NotRequired[str]
    snippets_root: str
    snippets: list[SnippetEntry] | list[ThirdPartyEntry]


def _copy_delivered_by_metadata(entry: SnippetEntry, metadata: Mapping[str, object]) -> None:
    raw_delivered_by = metadata.get("delivered_by")
    if isinstance(raw_delivered_by, list) and all(isinstance(slug, str) for slug in raw_delivered_by):
        entry["delivered_by"] = list(raw_delivered_by)


def _copy_subscriptions_metadata(entry: SnippetEntry, metadata: Mapping[str, object]) -> None:
    raw_subscriptions = metadata.get("subscriptions")
    if isinstance(raw_subscriptions, list) and all(isinstance(event_type, str) for event_type in raw_subscriptions):
        entry["subscriptions"] = list(raw_subscriptions)
    raw_subscription_home = metadata.get(IndexKey.SUBSCRIPTION_HOME)
    if isinstance(raw_subscription_home, str):
        entry[IndexKey.SUBSCRIPTION_HOME.value] = raw_subscription_home
    raw_subscription_identity = metadata.get(IndexKey.SUBSCRIPTION_IDENTITY)
    if isinstance(raw_subscription_identity, str):
        entry[IndexKey.SUBSCRIPTION_IDENTITY.value] = raw_subscription_identity
    raw_subscription_attendance = metadata.get(IndexKey.SUBSCRIPTION_ATTENDANCE)
    if isinstance(raw_subscription_attendance, str):
        entry[IndexKey.SUBSCRIPTION_ATTENDANCE.value] = raw_subscription_attendance
    delivery = resolve_delivery_settings(metadata)
    if delivery is not None:
        entry[IndexKey.EVENT_DELIVERY.value] = delivery.event_delivery.value
        entry[IndexKey.INTERRUPTIBLE.value] = delivery.interruptible


def _copy_entry_declarations(entry: SnippetEntry, metadata: Mapping[str, object]) -> None:
    """Publish a procedure's usable entry declarations; an unusable declaration publishes none."""
    declarations = parse_entry_declarations(metadata).declarations
    if declarations is None:
        return
    payload = entry_payload(declarations)
    entry[EntryKey.ROLE.value] = payload[EntryKey.ROLE.value]
    if EntryKey.PARAMETERS.value in payload:
        entry[EntryKey.PARAMETERS.value] = payload[EntryKey.PARAMETERS.value]
    if EntryKey.DISPATCH.value in payload:
        entry[EntryKey.DISPATCH.value] = payload[EntryKey.DISPATCH.value]


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


def write_third_party_index_yaml(
    third_party_root: Path, scope: str, *, published_root: Path | None = None
) -> Path | None:
    """Generate index.yaml for third-party docs.

    Args:
        third_party_root: Path to third-party directory (e.g., docs/third-party or ~/.teleclaude/docs/third-party)
        scope: Either "project" or "global"
        published_root: Address readers resolve the entries under when the index is written
            before the directory is exchanged into place; defaults to ``third_party_root``.

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
    root_str = _display_home_path(published_root if published_root is not None else third_party_root)

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
    write_declared_config(config_path, ConfigKind.PROJECT, _EMPTY_PROJECT_CONFIG_DOCUMENT)


def get_project_slug(project_root: Path) -> str:
    """Return the canonical slug identifying *project_root*.

    Priority:
    1. ``config.project_slug`` when set in ``teleclaude.yml``.
    2. Slugified ``config.project_name`` when available.
    3. Slugified directory name as a final fallback.

    Used where a slug is needed before one is declared (project setup and
    registration). Local snippet identities never use this fallback; they are
    minted from :func:`teleclaude.snippet_validation.read_declared_project_slug`.
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
    _copy_subscriptions_metadata(entry, metadata)
    _copy_entry_declarations(entry, metadata)
    _attach_superseding_slugs(entry, file_path)
    return entry


def _eligible_snippet_files(snippets_root: Path, *, include_baseline: bool) -> list[Path]:
    """Sorted snippet files for indexing, excluding companions.

    A companion ``<stem>.<slug>.md`` (sibling of an existing ``<stem>.md``) shares the
    parent's id and is the parent's pending replacement — it is never a standalone index
    entry. See ``sdlc/principle/documentation-first-development`` section 10.
    """
    return sorted(f for f in snippet_files(snippets_root, include_baseline=include_baseline) if not is_companion(f))


def build_index_payload(project_root: Path, snippets_root: Path) -> IndexPayload:
    """Build the index.yaml payload for a snippet root.

    A project's local root mints ``projects/<declared slug>/…`` identities and
    fails closed with :class:`teleclaude.snippet_validation.UndeclaredProjectSlugError`
    when the project declares no slug.
    """
    is_local_root = snippets_root == project_root / _DOCS_DIRNAME / _LOCAL_HALF
    local_slug = read_declared_project_slug(project_root) if is_local_root else None
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

        post = frontmatter.load(str(file_path))
        metadata: Mapping[str, object] = post.metadata or {}
        snippet_cache.append((file_path, metadata))

    for file_path, metadata in snippet_cache:
        entry = _build_snippet_entry(file_path, metadata, project_root=project_root, domains=domains)
        if entry is not None:
            snippets.append(entry)

    snippets.sort(key=lambda e: e["id"])

    project_slug = local_slug or get_project_slug(project_root)
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
        root = _display_home_path(project_root)
        snippets_root_str = _display_home_path(snippets_root)

    return {"project_root": root, "snippets_root": snippets_root_str, "snippets": snippets}


def _build_tier_index_payload(tier_root: Path, half: str, tier_kind: SnippetScope) -> IndexPayload:
    """Build the catalog payload for one half (``docs/global`` or ``docs/local``) of a tier home.

    Classification is path-derived; the only authored frontmatter is ``description``
    (``visibility`` optional). A snippet that authors ``id``/``type``/``scope``/``domain``
    violates the no-authored-classification contract and fails the build loudly.
    The half's root ``baseline*.md`` manifests are not snippets and are skipped.

    Recorded rooted at the half, which is a publication snapshot when building at
    platform-home publication time; ``reroot_index_document`` re-expresses the
    recorded roots at install time, so this function need not know its own
    install-time destination.
    """
    tier_docs_root = tier_root / _DOCS_DIRNAME
    half_root = tier_docs_root / half
    tier_label = tier_kind.value.capitalize()
    if not half_root.exists():
        return {"project_root": str(half_root), "snippets_root": str(half_root), "snippets": []}

    snippets: list[SnippetEntry] = []
    for file_path in _eligible_snippet_files(half_root, include_baseline=False):
        if is_half_root_baseline_manifest(file_path, docs_root=tier_docs_root):
            continue
        post = frontmatter.load(str(file_path))
        metadata: Mapping[str, object] = post.metadata or {}
        authored = [key.value for key in TierAuthoredClassificationKey if key in metadata]
        if authored:
            raise ValueError(
                f"{tier_label} snippet {file_path} authors path-derived classification keys {authored}; "
                f"{tier_label.lower()} snippets author only 'description'."
            )
        description = metadata.get("description")
        if not isinstance(description, str):
            raise ValueError(f"{tier_label} snippet {file_path} is missing a 'description'.")
        classification, reason = derive_tier_snippet_classification(file_path, tier_root=tier_root, tier_kind=tier_kind)
        if classification is None:
            raise ValueError(
                f"Cannot derive {tier_label.lower()} snippet classification for {file_path}: {reason or 'unknown'}"
            )
        raw_visibility = metadata.get("visibility")
        visibility = (
            raw_visibility
            if isinstance(raw_visibility, str) and raw_visibility in SNIPPET_VISIBILITY_VALUES
            else SNIPPET_VISIBILITY_INTERNAL
        )
        entry: SnippetEntry = {
            "id": classification.id,
            "description": description,
            "type": classification.type.value,
            "scope": classification.scope.value,
            "domain": classification.domain,
            "activation_trigger": None,
            "path": str(file_path.relative_to(half_root)),
            "visibility": visibility,
        }
        _copy_subscriptions_metadata(entry, metadata)
        _copy_entry_declarations(entry, metadata)
        snippets.append(entry)

    snippets.sort(key=lambda e: e["id"])
    return {"project_root": str(half_root), "snippets_root": str(half_root), "snippets": snippets}


def build_company_index_payload(company_dir: Path, half: str) -> IndexPayload:
    """Build the catalog payload for one half of a company home (``companies/<slug>``)."""
    return _build_tier_index_payload(company_dir, half, SnippetScope.COMPANY)


def build_person_index_payload(person_dir: Path, half: str) -> IndexPayload:
    """Build the catalog payload for one half of a person home (``people/<slug>``)."""
    return _build_tier_index_payload(person_dir, half, SnippetScope.PERSON)


def tier_index_path(tier_root: Path, half: str) -> Path:
    """Return the catalog path of one half of a tier home: ``docs/<half>/index.yaml``."""
    return tier_root / _DOCS_DIRNAME / half / _INDEX_FILENAME


def _write_index_content_gated(target: Path, payload: IndexPayload, *, delete_if_empty: bool) -> Path:
    """Write an index.yaml only when its rendered content differs from what's on disk.

    A tier catalog is kept even when empty (``delete_if_empty=False``): its
    existence is what tells a reader the tier participates, and an absent file
    is indistinguishable from an undeclared tier-shaped folder. Project and
    global catalogs keep the existing delete-when-empty behavior.
    """
    if not payload["snippets"] and delete_if_empty:
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


def write_tier_indexes(tier_root: Path, tier_kind: SnippetScope) -> list[Path]:
    """Build and write both halves' catalogs of a tier home. Returns the target paths.

    Each half gets a catalog even when it holds no snippets.
    """
    written: list[Path] = []
    for half in DOCS_HALVES:
        payload = _build_tier_index_payload(tier_root, half, tier_kind)
        written.append(_write_index_content_gated(tier_index_path(tier_root, half), payload, delete_if_empty=False))
    return written


def write_index_yaml(project_root: Path, snippets_root: Path) -> Path:
    """Build and write index.yaml for a snippet root. Returns the target path."""
    target = snippets_root / "index.yaml"
    # Third-party indexes are handled separately by write_third_party_index_yaml
    if "third-party" in snippets_root.parts:
        return target
    payload = build_index_payload(project_root, snippets_root)
    return _write_index_content_gated(target, payload, delete_if_empty=True)


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


def build_tier_index(tier_root: Path, kind: ConfigKind) -> list[Path]:
    """Build both catalogs for one declared company or person home."""
    if kind is ConfigKind.COMPANY:
        tier_kind = SnippetScope.COMPANY
    elif kind is ConfigKind.PERSON:
        tier_kind = SnippetScope.PERSON
    else:
        raise ValueError(_UNSUPPORTED_TIER_KIND.format(kind=kind.value))
    return write_tier_indexes(tier_root, tier_kind)
