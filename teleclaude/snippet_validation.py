"""Validate snippet IDs, paths, and inline references against the taxonomy."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import yaml

from teleclaude.config.loader import load_declared_project_config
from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.domains import publishes_for_root, valid_domains
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_DOCS_DIR, PEOPLE_DIR
from teleclaude.slug import normalize_slug
from teleclaude.snippet_scope import HOME_SCOPES, RESERVED_HOME_IDENTITY_PREFIXES, home_identity_prefix
from teleclaude.snippet_scope import SnippetScope as SnippetScope

ALLOWED_TAXONOMIES = frozenset(TAXONOMY_TYPES)
#: The generated bundle the documentation pipeline writes into each published
#: domain's deployed directory.
GENERATED_DOMAIN_BUNDLE_FILENAME = "bundle.md"
#: The bundle filename a retired generator wrote; recognised only so leftovers
#: are retired rather than read as snippets.
RETIRED_DOMAIN_BUNDLE_FILENAME = "domain-baseline-bundle.md"
_GENERATED_DOMAIN_ARTIFACT_NAMES: frozenset[str] = frozenset(
    {GENERATED_DOMAIN_BUNDLE_FILENAME, RETIRED_DOMAIN_BUNDLE_FILENAME}
)
_MARKDOWN_SUFFIX = ".md"
_BASELINE_INDEX_FILENAME = "index.md"
_BASELINE_FILE_PREFIX = "baseline"
_COMPANION_NAME_SEPARATOR = "."


class SnippetTaxonomy(StrEnum):
    """Closed taxonomy values for documentation snippets."""

    PRINCIPLE = "principle"
    CONCEPT = "concept"
    POLICY = "policy"
    PROCEDURE = "procedure"
    DESIGN = "design"
    SPEC = "spec"
    ADR = "adr"


class TierAuthoredClassificationKey(StrEnum):
    """Classification fields that tier snippet sources must derive from paths."""

    ID = "id"
    TYPE = "type"
    SCOPE = "scope"
    DOMAIN = "domain"


#: Snippet-id prefixes reserved by the identity grammar, never a domain name:
#: reserved home identity prefixes, owned by ``RESERVED_HOME_IDENTITY_PREFIXES``,
#: the home-kind domain literals, and the structural
#: markers that are not domains (``third-party``, ``baseline``).
RESERVED_SNIPPET_ID_PREFIXES: frozenset[str] = (
    frozenset({"third-party", "baseline"})
    | RESERVED_HOME_IDENTITY_PREFIXES
    | frozenset(scope.value for scope in HOME_SCOPES)
)

_DOCS_DIRNAME = "docs"
_GLOBAL_HALF = "global"
_LOCAL_HALF = "local"
_PATH_TRAVERSAL_SEGMENTS: frozenset[str] = frozenset({".", ".."})
_INVALID_PROJECT_LOCAL_REF_PATH = "invalid_project_local_ref_path"
#: The two halves of every documentation home, in classification order.
DOCS_HALVES: tuple[str, str] = (_GLOBAL_HALF, _LOCAL_HALF)
_BASELINE_MANIFEST_NAMES: frozenset[str] = frozenset({"baseline.md", "baseline-progressive.md"})
_BASELINE_SEGMENT = "baseline"
_TIER_CLASSIFICATION_KEY_SEPARATOR: Final[str] = ", "
_PROJECT_DECLARATION_SUBJECT = "project"
_PROJECT_SLUG_KEY = "project_slug"
_PROJECT_NAME_KEY = "project_name"
_UNDECLARED_PROJECT_SLUG_MESSAGE = (
    "Project at {root} declares neither project_slug nor project_name in teleclaude.yml; "
    "its local snippet identities cannot be minted."
)


class UndeclaredProjectSlugError(ValueError):
    """A project root declares no slug, so no local identity can be minted for it."""

    def __init__(self, root: Path) -> None:
        super().__init__(_UNDECLARED_PROJECT_SLUG_MESSAGE.format(root=root))
        self.root = root


@dataclass(frozen=True)
class SnippetIdParts:
    """Parsed components of a snippet ID.

    ``owner`` is set only for home snippets, whose identity carries the home
    prefix and its owning slug (``local/projects/<slug>/…`` or
    ``people|companies/<slug>/…``);
    a domain snippet renders ``<domain>/<taxonomy>/<rest>``.
    """

    scope: str
    taxonomy: str
    rest: str
    owner: str | None = None
    local: bool = False

    def value(self) -> str:
        """Return the full snippet ID string."""
        if self.owner:
            prefix = home_identity_prefix(SnippetScope(self.scope), local=self.local)
            base = f"{prefix}/{self.owner}/{self.taxonomy}"
        else:
            base = f"{self.scope}/{self.taxonomy}"
        if self.rest:
            return f"{base}/{self.rest}"
        return base


@dataclass(frozen=True)
class SnippetClassification:
    """Path-derived snippet classification materialized by the index."""

    id: str
    type: SnippetTaxonomy
    scope: SnippetScope
    domain: str


def load_domains(project_root: Path) -> set[str]:
    """Return the valid domain scopes for classifying ``project_root``'s snippets.

    The set is the union of every registered publisher's ``business.publishes``
    plus ``project_root``'s own declarations, so a project can always classify
    its own snippets — even before it is registered in the manifest.
    """
    return valid_domains() | publishes_for_root(project_root)


def _split_parts(value: str) -> tuple[list[str], bool]:
    raw = value.strip().strip("/")
    if not raw:
        return [], True
    parts = raw.split("/")
    has_empty = any(not part for part in parts)
    return parts, has_empty


def _allowed_scopes(domains: Iterable[str]) -> set[str]:
    return {SnippetScope.PROJECT.value, SnippetScope.PERSON.value, SnippetScope.COMPANY.value, *domains}


def companion_shape(path: Path) -> tuple[str, str] | None:
    """Return the parent stem and slug-shaped suffix, without checking the parent."""
    if not path.name.endswith(_MARKDOWN_SUFFIX):
        return None
    base = path.name[: -len(_MARKDOWN_SUFFIX)]
    if _COMPANION_NAME_SEPARATOR not in base:
        return None
    stem, slug = base.rsplit(_COMPANION_NAME_SEPARATOR, 1)
    if not stem or not slug:
        return None
    return stem, slug


def companion_slug(path: Path) -> str | None:
    """Sole owner of the companion filename grammar.

    A companion is ``<stem>.<slug>.md`` — a sibling of an existing ``<stem>.md``.
    Snippet stems and slugs are kebab-case (dot-free), so a companion is the only
    ``.md`` file whose name carries a dot before the extension; the segment before
    that final dot names the parent stem, the segment after names the delivering
    slug. Returns the slug when ``path`` is a companion, else ``None``. A companion
    is either a replacement body or, when zero bytes, the retirement carrier for
    its parent. Both deliberately share the parent's id, so id↔path checks exempt it.
    """
    shape = companion_shape(path)
    if shape is None:
        return None
    stem, slug = shape
    if not (path.parent / (stem + _MARKDOWN_SUFFIX)).exists():
        return None
    return slug


def is_retirement_companion(path: Path) -> bool:
    """Whether a valid companion is the zero-byte retirement carrier for its parent."""
    return companion_slug(path) is not None and path.is_file() and path.stat().st_size == 0


def companion_parent(path: Path) -> Path | None:
    """The parent ``<stem>.md`` of a companion ``<stem>.<slug>.md``, or ``None``."""
    if companion_slug(path) is None:
        return None
    stem = path.name[:-3].rsplit(".", 1)[0]
    return path.parent / f"{stem}.md"


def is_companion(path: Path) -> bool:
    """Whether ``path`` is a companion ``<stem>.<slug>.md`` (see :func:`companion_slug`)."""
    return companion_slug(path) is not None


def read_declared_project_slug(project_root: Path) -> str:
    """Return the slug a project declares, for minting its local snippet identities.

    Reads ``project_slug``, else the normalized ``project_name``, from the root's
    own loaded project configuration. Never falls back to the directory name,
    which is not an identity on a publication snapshot or a clone. Raises
    :class:`UndeclaredProjectSlugError` when neither is declared.
    """
    declared = load_declared_project_config(project_root)
    if declared is not None:
        if declared.project_slug:
            return declared.project_slug
        if declared.project_name and normalize_slug(declared.project_name):
            return normalize_slug(declared.project_name)
    raise UndeclaredProjectSlugError(project_root)


def is_half_root_baseline_manifest(path: Path, *, docs_root: Path) -> bool:
    """Whether ``path`` is a baseline manifest at the root of a home's ``docs/<half>``.

    ``docs/global/baseline*.md`` and ``docs/local/baseline*.md`` list snippets for
    assembly; they are manifests, never snippets, and carry no classification.
    """
    if path.name not in _BASELINE_MANIFEST_NAMES:
        return False
    parent = path.parent
    return parent.name in DOCS_HALVES and parent.parent == docs_root


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
    if len(parts) < 2 or parts[0] != _DOCS_DIRNAME:
        return None, "not_under_docs_root"

    if parts[1] == "third-party":
        return None, None

    if parts[1] == _GLOBAL_HALF:
        return _expected_from_global(parts, path, domains)

    if parts[1] == _LOCAL_HALF:
        return _expected_from_local(parts, path, project_root=project_root)

    return None, "invalid_docs_root"


def tier_root_kind(root: Path) -> SnippetScope | None:
    """Whether ``root`` is a declared company or person tier's documentation home.

    A tier root is a direct child of a directory named ``companies`` or
    ``people`` — structural, not tied to the real machine's platform home, so a
    root under a publication snapshot or an isolated fixture classifies the same
    way a root under the live home does. Dispatch reads the root's own location
    rather than a caller-supplied flag, so every caller of
    :func:`derive_snippet_classification` classifies a tier file the same way it
    classifies a project file, with no second entry point to keep in agreement.
    Public: also consumed by ``docs_publishers`` to resolve a Required-read
    reference into a sibling tier from within a validated tier file.
    """
    resolved = root.expanduser().resolve()
    if resolved.parent.name == COMPANIES_ROOT.name:
        return SnippetScope.COMPANY
    if resolved.parent.name == PEOPLE_DIR.name:
        return SnippetScope.PERSON
    return None


def authored_tier_classification_keys(path: Path, tier_root: Path, metadata: Mapping[str, object]) -> str | None:
    """Return classification keys authored by an indexable tier source."""
    if tier_root_kind(tier_root) is None:
        return None
    docs_root = tier_root / _DOCS_DIRNAME
    if _BASELINE_SEGMENT in path.relative_to(docs_root).parent.parts or is_half_root_baseline_manifest(
        path, docs_root=docs_root
    ):
        return None
    authored = [key.value for key in TierAuthoredClassificationKey if key in metadata]
    return _TIER_CLASSIFICATION_KEY_SEPARATOR.join(authored) if authored else None


def is_baseline_index(path: Path) -> bool:
    """Whether a Markdown file is a baseline manifest or index."""
    return (path.name == _BASELINE_INDEX_FILENAME and _BASELINE_SEGMENT in path.parts) or (
        path.name.startswith(_BASELINE_FILE_PREFIX)
        and path.name.endswith(_MARKDOWN_SUFFIX)
        and (path.parent.name in DOCS_HALVES or path.parent.parent.name in DOCS_HALVES)
    )


def derive_snippet_classification(
    path: Path,
    *,
    project_root: Path,
    domains: Iterable[str],
) -> tuple[SnippetClassification | None, str | None]:
    """Derive snippet classification from its filesystem path.

    For a declared company or person tier, ``project_root`` is the tier root and
    the layout is ``<tier root>/docs/{global,local}/<taxonomy>/<rest>`` — no domain
    segment; each half derives a distinct identity. See
    :func:`tier_root_kind`.
    """
    tier_kind = tier_root_kind(project_root)
    if tier_kind is not None:
        return derive_tier_snippet_classification(path, tier_root=project_root, tier_kind=tier_kind)

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

    domain = scope.value if scope in HOME_SCOPES else snippet_id.split("/", 1)[0]
    return (
        SnippetClassification(
            id=snippet_id,
            type=taxonomy,
            scope=scope,
            domain=domain,
        ),
        None,
    )


def derive_tier_snippet_classification(
    path: Path,
    *,
    tier_root: Path,
    tier_kind: SnippetScope,
) -> tuple[SnippetClassification | None, str | None]:
    """Derive a tier snippet's classification from its path under either half.

    Path-derived, never authored: ``<tier root>/docs/{global,local}/<taxonomy>/<rest>``
    → ``people|companies/<slug>/<taxonomy>/<rest>`` for the published half and
    ``local/people|companies/<slug>/<taxonomy>/<rest>`` for the local half. The
    tier's slug is its folder name, the identity the tier
    is discovered and registered by. The domain is the tier's kind literal.
    """
    id_path = companion_parent(path) or path
    docs_root = tier_root / _DOCS_DIRNAME
    rel: Path | None = None
    matched_half: str | None = None
    for half in DOCS_HALVES:
        try:
            rel = id_path.resolve().relative_to((docs_root / half).resolve())
            matched_half = half
            break
        except (ValueError, OSError):
            continue
    if rel is None:
        return None, "not_under_tier_docs_root"
    parts = rel.parts
    if len(parts) < 2:
        return None, "missing_taxonomy_or_slug"
    raw_taxonomy = parts[0]
    if raw_taxonomy not in ALLOWED_TAXONOMIES:
        return None, "invalid_taxonomy"
    rest = "/".join(parts[1:])
    if rest.endswith(_MARKDOWN_SUFFIX):
        rest = rest[: -len(_MARKDOWN_SUFFIX)]
    if not rest:
        return None, "missing_slug"
    owner_slug = tier_root.expanduser().resolve().name
    snippet_id = SnippetIdParts(
        scope=tier_kind.value,
        taxonomy=raw_taxonomy,
        rest=rest,
        owner=owner_slug,
        local=matched_half == _LOCAL_HALF,
    ).value()
    return (
        SnippetClassification(
            id=snippet_id, type=SnippetTaxonomy(raw_taxonomy), scope=tier_kind, domain=tier_kind.value
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
    if len(parts) >= 4 and parts[0] == _DOCS_DIRNAME and parts[1] == _GLOBAL_HALF:
        raw_taxonomy = parts[3]
    elif len(parts) >= 3 and parts[0] == _DOCS_DIRNAME and parts[1] == _LOCAL_HALF:
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
    if len(parts) < 2 or parts[0] != _DOCS_DIRNAME:
        return None, "not_under_docs_root"
    if parts[1] == _GLOBAL_HALF:
        return SnippetScope.GLOBAL, None
    if parts[1] == _LOCAL_HALF:
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
    # Domain-level baseline: docs/global/<domain>/baseline.md (e.g. general,
    # sdlc). Treated as a manifest — no frontmatter required. The deploy
    # pipeline inflates it into the composed docs root at
    # ~/.teleclaude/docs/<domain>/bundle.md for codex-readable consumption.
    if path.name in {"baseline.md", "baseline-progressive.md"} and path.parent.name == scope_segment:
        return None, None
    if scope_segment == "baseline":
        if len(parts) < 5:
            return None, "baseline_missing_taxonomy"
        taxonomy = parts[3]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return None, "invalid_taxonomy"
        return None, None
    if scope_segment == "snippets":
        return None, None

    if scope_segment not in _allowed_scopes(domains):
        return None, "invalid_scope"
    if len(parts) < 5:
        return None, "missing_taxonomy"
    taxonomy = parts[3]
    if taxonomy not in ALLOWED_TAXONOMIES:
        return None, "invalid_taxonomy"
    rest = _tail(parts, 4, path)
    if not rest:
        return None, "missing_slug"
    return SnippetIdParts(scope=scope_segment, taxonomy=taxonomy, rest=rest).value(), None


def _expected_from_local(
    parts: tuple[str, ...],
    path: Path,
    *,
    project_root: Path,
) -> tuple[str | None, str | None]:
    if len(parts) < 3:
        return None, "missing_taxonomy"
    if is_half_root_baseline_manifest(path, docs_root=project_root / _DOCS_DIRNAME):
        return None, None
    if parts[2] == "baseline":
        return None, "project_baseline_only_index"
    taxonomy = parts[2]
    if taxonomy not in ALLOWED_TAXONOMIES:
        return None, "invalid_taxonomy"
    rest = _tail(parts, 3, path)
    if not rest:
        return None, "missing_slug"
    try:
        owner = read_declared_project_slug(project_root)
    except UndeclaredProjectSlugError:
        return None, "undeclared_project_slug"
    return (
        SnippetIdParts(
            scope=SnippetScope.PROJECT.value,
            taxonomy=taxonomy,
            rest=rest,
            owner=owner,
            local=True,
        ).value(),
        None,
    )


def _tail(parts: tuple[str, ...], start_idx: int, path: Path) -> str:
    name = path.stem if path.suffix else parts[-1]
    tail_parts = list(parts[start_idx:-1]) + [name]
    return "/".join([p for p in tail_parts if p])


def validate_inline_ref_format(ref: str, *, domains: Iterable[str], project_root: Path) -> str | None:
    """Validate an inline @ref and return an error code or None if valid."""
    if not ref:
        return "missing_ref"
    if not ref.startswith("@"):
        return "missing_at_prefix"
    if ref.startswith("@docs/"):
        return _validate_project_ref(ref[len("@docs/") :], domains, project_root=project_root)
    for abs_prefix in _global_ref_prefixes():
        if ref.startswith(abs_prefix):
            return _validate_global_ref(ref, ref[len(abs_prefix) :], domains)
    return "invalid_prefix"


def _global_ref_prefixes() -> tuple[str, ...]:
    """Return valid absolute prefixes for global documentation refs."""
    configured_prefix = f"@{GLOBAL_DOCS_DIR}/"
    home_prefix = f"@{Path.home()}/.teleclaude/docs/"
    tilde_prefix = "@~/.teleclaude/docs/"
    return tuple(dict.fromkeys((configured_prefix, home_prefix, tilde_prefix)))


def snippet_body_digest_for(repo_root: str) -> Callable[[str], str]:
    """Return a digest seam bound to the project whose snippets it resolves."""
    project_index = Path(repo_root) / _DOCS_DIRNAME / _LOCAL_HALF / "index.yaml"

    def snippet_body_digest(snippet_id: str) -> str:
        """Return SHA256 of snippet content, excluding delivered_by frontmatter churn."""
        snippet_path = _resolve_snippet_path(snippet_id, project_index=project_index)
        if snippet_path is None:
            return ""
        try:
            content = snippet_path.read_text(encoding="utf-8")
        except OSError:
            return ""
        filtered = _strip_delivered_by_frontmatter(content)
        return hashlib.sha256(filtered.encode("utf-8")).hexdigest()

    return snippet_body_digest


def _resolve_snippet_path(snippet_id: str, *, project_index: Path) -> Path | None:
    """Resolve a canonical snippet ID through project then global snippet indexes."""
    global_index = GLOBAL_DOCS_DIR / "index.yaml"
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


def _validate_project_ref(rel: str, domains: Iterable[str], *, project_root: Path) -> str | None:
    if rel.startswith("docs/"):
        return "nested_docs_root"
    parts, has_empty = _split_parts(rel)
    if has_empty:
        return "empty_segment"
    if any(part in _PATH_TRAVERSAL_SEGMENTS for part in parts):
        return _INVALID_PROJECT_LOCAL_REF_PATH
    if rel == "baseline.md":
        return None
    if rel == f"{_LOCAL_HALF}/baseline.md":
        return _validate_project_local_ref_path(rel, project_root=project_root)
    if len(parts) < 3:
        return "missing_segments"
    if parts[0] != _LOCAL_HALF:
        return "invalid_project_scope"
    path_error = _validate_project_local_ref_path(rel, project_root=project_root)
    if path_error is not None:
        return path_error
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


def _validate_project_local_ref_path(rel: str, *, project_root: Path) -> str | None:
    try:
        resolved_project_root = project_root.resolve()
        docs_root = (project_root / _DOCS_DIRNAME).resolve()
        local_docs_root = (project_root / _DOCS_DIRNAME / _LOCAL_HALF).resolve()
        global_docs_root = (project_root / _DOCS_DIRNAME / _GLOBAL_HALF).resolve()
        snippet_path = (project_root / _DOCS_DIRNAME / rel).resolve()
    except (OSError, RuntimeError, ValueError):
        return _INVALID_PROJECT_LOCAL_REF_PATH
    if not docs_root.is_relative_to(resolved_project_root):
        return _INVALID_PROJECT_LOCAL_REF_PATH
    if not local_docs_root.is_relative_to(docs_root):
        return _INVALID_PROJECT_LOCAL_REF_PATH
    if not snippet_path.is_relative_to(local_docs_root):
        return _INVALID_PROJECT_LOCAL_REF_PATH
    if snippet_path.is_relative_to(global_docs_root):
        return _INVALID_PROJECT_LOCAL_REF_PATH
    return None


def is_generated_global_doc_artifact(relative_path: Path) -> bool:
    """Whether a deployed-global-docs-root-relative path names a generated artifact.

    Covers the two artifacts the documentation pipeline writes and that no
    publisher source tree owns: the merged index, matched by filename at any
    depth, and a domain's baseline bundle, matched as a two-segment
    ``<domain>/bundle.md`` path. Structural only — it does not re-check domain
    publication, which the caller's own registry lookup settles.
    """
    if relative_path.name == "index.yaml":
        return True
    return len(relative_path.parts) == 2 and relative_path.parts[1] == GENERATED_DOMAIN_BUNDLE_FILENAME


def is_generated_domain_artifact_source(path: Path) -> bool:
    """Whether a docs-tree file sits in a generated domain-bundle position.

    The position is a Markdown file directly in a domain directory under a
    ``global`` docs root (``<…>/global/<domain>/<name>``) carrying the generated
    bundle name or the retired one. A file of that name under a taxonomy
    directory — including a tier home's domainless ``docs/global/<taxonomy>/`` —
    is an ordinary snippet.
    """
    return (
        path.name in _GENERATED_DOMAIN_ARTIFACT_NAMES
        and len(path.parts) >= 3
        and path.parent.parent.name == _GLOBAL_HALF
        and path.parent.name not in ALLOWED_TAXONOMIES
    )


def generated_domain_bundle_domain(ref: str, *, domains: Iterable[str]) -> str | None:
    """Return the published domain for one canonical generated-bundle ref."""
    for prefix in _global_ref_prefixes():
        if not ref.startswith(prefix):
            continue
        parts, has_empty = _split_parts(ref[len(prefix) :])
        if has_empty or len(parts) != 2:
            return None
        domain, filename = parts
        if filename != GENERATED_DOMAIN_BUNDLE_FILENAME or domain not in set(domains):
            return None
        return domain
    return None


_TIER_ADDRESS_DIRNAMES: frozenset[str] = frozenset({COMPANIES_ROOT.name, PEOPLE_DIR.name})


def _validate_global_ref(ref: str, rel: str, domains: Iterable[str]) -> str | None:
    if rel.startswith("docs/"):
        return "nested_docs_root"
    if generated_domain_bundle_domain(ref, domains=domains) is not None:
        return None
    parts, has_empty = _split_parts(rel)
    if has_empty:
        return "empty_segment"
    if parts[0] in _TIER_ADDRESS_DIRNAMES:
        # A tier's published address: companies/<slug>/<taxonomy>/<rest> or
        # people/<slug>/<taxonomy>/<rest> — the deployed directory layout, not
        # the singular scope vocabulary a snippet id renders.
        if len(parts) < 4:
            return "missing_segments"
        taxonomy = parts[2]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return "invalid_taxonomy"
        if not parts[-1].endswith(".md"):
            return "missing_md_extension"
        return None
    if len(parts) < 3:
        return "missing_segments"
    if parts[0] == "baseline":
        taxonomy = parts[1]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return "invalid_taxonomy"
    else:
        if parts[0] not in _allowed_scopes(domains):
            return "invalid_scope"
        taxonomy = parts[1]
        if taxonomy not in ALLOWED_TAXONOMIES:
            return "invalid_taxonomy"
    if not parts[-1].endswith(".md"):
        return "missing_md_extension"
    return None
