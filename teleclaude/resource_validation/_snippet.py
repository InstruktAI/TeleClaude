"""Snippet validation, inline ref helpers, and third-party doc validation."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path

from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.constants import (
    SNIPPET_VISIBILITY_VALUES,
    TYPE_SUFFIX,
)
from teleclaude.core.workflow_store import StorePresenceKind, local_store_presence
from teleclaude.docs_publishers import DocsPublisherResolutionError, resolve_global_doc_source
from teleclaude.paths import GLOBAL_DOCS_ROOTS
from teleclaude.required_reads import extract_required_reads
from teleclaude.resource_validation._activation import (
    validate_activation_mode_exclusivity,
    validate_activation_trigger,
    validate_entry_declarations,
    validate_subscriptions,
)
from teleclaude.resource_validation._markdown import markdown_read_scope, parse_markdown, read_markdown
from teleclaude.resource_validation._markers import (
    validate_marker_structure,
    validate_planned_change_markers,
)
from teleclaude.resource_validation._models import (
    _ARTIFACT_REF_ORDER,
    _CODE_FENCE_LINE,
    _H1_LINE,
    _H2_LINE,
    _HEADER_LINE,
    _HTML_COMMENT_LINE,
    _INLINE_CODE_SPAN,
    _INLINE_REF_LINE,
    _REQUIRED_READS_HEADER,
    _SCHEMA,
    _SEE_ALSO_HEADER,
    _SEE_ALSO_LIST_LINE,
    _SOURCES_HEADER,
    _as_str_list,
    _error,
    _first_out_of_order_ref,
)
from teleclaude.resource_validation._todo_status import TodoStatusFact, build_todo_status_facts, is_pending_marker_stale
from teleclaude.snippet_roots import is_excluded_snippet_path, iter_snippet_roots, iter_tier_snippet_roots
from teleclaude.snippet_validation import (
    UNREGISTERED_DOMAIN_REF,
    SnippetClassification,
    SnippetTaxonomy,
    authored_tier_classification_keys,
    derive_snippet_classification,
    generated_domain_bundle_domain,
    global_ref_domain,
    is_baseline_index,
    is_companion,
    is_generated_domain_artifact_source,
    is_retirement_companion,
    load_domains,
    project_slug_resolution,
    validate_inline_ref_format,
)

_MARKDOWN_LINK_RE = re.compile(r"^\[([^\]]+)\]\((https?://[^)]+)\)$")
INCLUDE_DIRECTIVE_RE = re.compile(r"<!--\s*@include:\s*(.+?\.md)\s*-->")
_THIRD_PARTY_TYPE = "third-party"
_THIRD_PARTY_INDEX_NAMES = frozenset({"index.md", "index.yaml"})
_INLINE_REF_PREFIX = "@"
_LOCAL_HALF = "local"
_DOCS_DIRNAME = "docs"
_BASELINE_SEGMENT = "baseline"
_TIER_CLASSIFICATION_AUTHORED_FINDING = "snippet_tier_classification_authored"
_INLINE_REF_DOMAIN_UNREGISTERED_FINDING = "snippet_inline_ref_domain_publisher_unregistered"
# ---------------------------------------------------------------------------
# Shared ref resolution
# ---------------------------------------------------------------------------


def resolve_ref_path(ref: str, *, root_path: Path, current_path: Path) -> Path | None:
    """Resolve an ``@`` reference to an absolute path.

    Handles absolute paths, ``~/`` expansion, ``docs/`` relative paths with
    local/global fallback, and paths relative to the referencing file.
    """
    if "://" in ref:
        return None
    candidate = Path(ref).expanduser()
    if not candidate.is_absolute():
        if str(candidate).startswith("docs/"):
            candidate = (root_path / candidate).resolve()
            if not candidate.exists():
                tail = Path(ref).relative_to("docs")
                project_candidate = (root_path / "docs" / _LOCAL_HALF / tail).resolve()
                if project_candidate.exists():
                    candidate = project_candidate
                else:
                    global_candidate = (root_path / "docs" / "global" / tail).resolve()
                    if global_candidate.exists():
                        candidate = global_candidate
        else:
            candidate = (current_path.parent / candidate).resolve()
    else:
        raw_candidate = candidate
        candidate = candidate.resolve()
        mapped_candidate = resolve_global_doc_source(root_path, raw_candidate)
        return mapped_candidate if mapped_candidate != raw_candidate else candidate
    return resolve_global_doc_source(root_path, candidate)


# ---------------------------------------------------------------------------
# Inline ref helpers
# ---------------------------------------------------------------------------


def iter_inline_refs(lines: list[str]) -> list[str]:
    """Extract ``@`` refs from lines, skipping code fences."""
    refs: list[str] = []
    in_code_block = False
    for line in lines:
        if _CODE_FENCE_LINE.match(line.strip()):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not _INLINE_REF_LINE.match(line):
            continue
        ref = line.strip().lstrip("-").strip()
        refs.append(ref)
    return refs


def _get_allowed_ref_prefixes() -> tuple[str, ...]:
    home = str(Path.home())
    return f"@{home}/.teleclaude/docs/", "@~/.teleclaude/docs/", "@docs/"


def collect_inline_ref_errors(
    project_root: Path, snippet_path: Path, lines: list[str], *, domains: set[str]
) -> list[dict[str, str]]:
    """Validate inline ``@`` refs for format and existence."""
    errors: list[dict[str, str]] = []
    allowed_prefixes = _get_allowed_ref_prefixes()
    for ref in iter_inline_refs(lines):
        if not ref.startswith(allowed_prefixes):
            errors.append({"code": "snippet_invalid_inline_ref", "path": str(snippet_path), "ref": ref})
            continue
        format_error = validate_inline_ref_format(ref, domains=domains, project_root=project_root)
        if format_error == UNREGISTERED_DOMAIN_REF:
            domain = global_ref_domain(ref)
            assert domain is not None
            errors.append(
                {
                    "code": _INLINE_REF_DOMAIN_UNREGISTERED_FINDING,
                    "path": str(snippet_path),
                    "ref": ref,
                    "reason": str(unregistered_referent(ReferentKind.DOMAIN, domain)),
                }
            )
            continue
        if format_error:
            errors.append(
                {
                    "code": "snippet_inline_ref_format_invalid",
                    "path": str(snippet_path),
                    "ref": ref,
                    "reason": format_error,
                }
            )
            continue
        generated_bundle_domain = generated_domain_bundle_domain(ref, domains=domains)
        try:
            resolved = _resolve_snippet_ref(project_root, snippet_path, ref)
        except DocsPublisherResolutionError as exc:
            errors.append(
                {
                    "code": "snippet_global_source_resolution_failed",
                    "path": str(snippet_path),
                    "ref": ref,
                    "reason": str(exc),
                }
            )
            continue
        if resolved is None:
            errors.append({"code": "snippet_invalid_inline_ref", "path": str(snippet_path), "ref": ref})
            continue
        if not resolved.exists():
            if generated_bundle_domain is not None:
                continue
            errors.append(
                {
                    "code": "snippet_inline_ref_missing",
                    "path": str(snippet_path),
                    "ref": ref,
                    "resolved": str(resolved),
                }
            )
            continue
        if not resolved.is_file():
            errors.append(
                {
                    "code": "snippet_inline_ref_not_file",
                    "path": str(snippet_path),
                    "ref": ref,
                    "resolved": str(resolved),
                }
            )
    return errors


def _resolve_home_doc_source_ref(project_root: Path, candidate: Path) -> Path:
    return resolve_global_doc_source(project_root, candidate)


def _resolve_snippet_ref(project_root: Path, snippet_path: Path, ref: str) -> Path | None:  # pylint: disable=unused-argument
    if not ref.startswith("@"):
        return None
    target = ref[1:]
    if target.startswith("~"):
        return _resolve_home_doc_source_ref(project_root, Path(target).expanduser())
    if target.startswith("./") or target.startswith("/"):
        return _resolve_home_doc_source_ref(project_root, Path(target))
    if target.startswith("../"):
        raise NotImplementedError("Relative refs with .. not supported")
    return (project_root / target).resolve()


# ---------------------------------------------------------------------------
# Snippet validation
# ---------------------------------------------------------------------------


def _normalize_section_title(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", title).strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def _snippet_type_for_validation(classification: SnippetClassification | None) -> str | None:
    return classification.type.value if classification is not None else None


def _validate_visibility(path: Path, meta: Mapping[str, object]) -> None:
    raw_visibility = meta.get("visibility")
    if raw_visibility is None:
        return
    if not isinstance(raw_visibility, str) or raw_visibility not in SNIPPET_VISIBILITY_VALUES:
        _error("snippet_invalid_visibility_value", path=str(path), value=str(raw_visibility))


def _validate_delivered_by(
    path: Path,
    meta: Mapping[str, object],
) -> None:
    raw_delivered_by = meta.get("delivered_by")
    if raw_delivered_by is None:
        return
    delivered_by = _as_str_list(raw_delivered_by)
    if not delivered_by:
        _error("snippet_delivered_by_invalid_shape", path=str(path))


def _validate_delivered_by_todo(
    path: Path,
    meta: Mapping[str, object],
    todo_status_facts: Mapping[str, TodoStatusFact],
    project_root: Path,
) -> None:
    """Flag a delivered_by slug only when its delivery commit is in this checkout."""
    delivered_by = _as_str_list(meta.get("delivered_by"))
    for slug in delivered_by:
        if not is_pending_marker_stale(slug, todo_status_facts, project_root):
            continue
        status = todo_status_facts[slug].status.value
        _error(
            "snippet_delivered_by_invalid_slug", path=str(path), slug=slug, reason=f"todo is {status}, not in flight"
        )


def validate_snippet(
    path: Path,
    content: str,
    project_root: Path,
    *,
    domains: set[str],
    todo_status_facts: Mapping[str, TodoStatusFact] | None = None,
) -> None:
    """Validate a single doc snippet. Collects validation findings via ``_error``.

    When ``todo_status_facts`` is provided, a delivered slug is reported only
    when its recorded delivery commit is contained by the validated checkout.
    Uncontained or unrecorded commits are tolerated; when ``None`` the snippet
    is validated for shape only (todo-agnostic callers).
    """
    if is_retirement_companion(path):
        return
    if _is_third_party_doc(path, project_root):
        validate_third_party_doc(path, content, project_root)
        return
    if is_generated_domain_artifact_source(path):
        # Generated deploy artifact (one merged inflated bundle per domain),
        # not an authored snippet — no frontmatter or taxonomy contract applies.
        return
    has_frontmatter = content.lstrip().startswith("---")
    if has_frontmatter:
        try:
            post = parse_markdown(content)
            meta: Mapping[str, object] = post.metadata or {}
            body = post.content
        except Exception:  # pylint: disable=broad-exception-caught
            meta = {}
            body = content
    else:
        meta = {}
        body = content
    if authored_keys := authored_tier_classification_keys(path, project_root, meta):
        _error(_TIER_CLASSIFICATION_AUTHORED_FINDING, path=str(path), keys=authored_keys)
    if is_baseline_index(path):
        _validate_baseline_index(path, content, project_root, domains=domains)
        return
    lines = body.splitlines()

    classification, path_error = derive_snippet_classification(path, project_root=project_root, domains=domains)
    if path_error and not is_companion(path):
        _error("snippet_invalid_path", path=str(path), reason=path_error)

    _validate_visibility(path, meta)
    snippet_type = _snippet_type_for_validation(classification)
    validate_activation_trigger(path, meta, snippet_type=snippet_type)
    validate_subscriptions(path, meta, classification, snippet_type=snippet_type)
    validate_entry_declarations(path, meta, snippet_type=snippet_type)
    validate_activation_mode_exclusivity(path, meta)
    _validate_delivered_by(path, meta)
    if todo_status_facts is not None:
        _validate_delivered_by_todo(path, meta, todo_status_facts, project_root)
    validate_planned_change_markers(path, body, todo_status_facts, project_root)
    validate_marker_structure(path, body)
    _validate_snippet_structure(path, lines, meta, has_frontmatter, domains=domains, classification=classification)
    _validate_snippet_refs(path, lines, project_root, domains=domains)
    _validate_snippet_sections(path, lines, meta, classification=classification)


def _validate_baseline_index(path: Path, content: str, project_root: Path, *, domains: set[str]) -> None:
    if content.lstrip().startswith("---"):
        try:
            post = parse_markdown(content)
            content = post.content
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    lines = [line for line in content.splitlines() if line.strip()]
    ref_lines = [line for line in lines if line.startswith("@")]
    for line in lines:
        if not line.startswith("@"):
            # Only report if the file also contains @ refs — mixed content is suspicious.
            # A pure-instruction baseline file (no @ lines) is intentionally prose-only.
            if ref_lines:
                _error("snippet_baseline_index_invalid_line", path=str(path), line=line)
    bad_ref = _first_out_of_order_ref(ref_lines)
    if bad_ref is not None:
        _error(
            "snippet_baseline_index_out_of_order",
            path=str(path),
            line=bad_ref,
            expected_order=" → ".join(_ARTIFACT_REF_ORDER),
        )
    for error in collect_inline_ref_errors(project_root, path, lines, domains=domains):
        _error(error["code"], **{k: v for k, v in error.items() if k != "code"})


def _validate_h1(path: Path, lines: list[str], classification: SnippetClassification | None) -> None:
    first_non_empty = next((line for line in lines if line.strip()), "")
    first_h1_match = _H1_LINE.match(first_non_empty)
    if not first_h1_match:
        _error("snippet_missing_h1", path=str(path))
    else:
        expected_suffix = TYPE_SUFFIX.get(classification.type.value) if classification is not None else None
        if expected_suffix and not first_non_empty.endswith(f" — {expected_suffix}"):
            _error(
                "snippet_title_suffix_invalid",
                path=str(path),
                reason=f"first H1 must end with — {expected_suffix}",
            )
    if _SCHEMA["global_"].get("require_h1_first", True):
        if first_non_empty and not first_h1_match:
            _error("snippet_h1_not_first", path=str(path))


def _validate_snippet_structure(  # pylint: disable=too-many-branches,unused-argument
    path: Path,
    lines: list[str],
    meta: Mapping[str, object],
    has_frontmatter: bool,
    *,
    domains: set[str],
    classification: SnippetClassification | None,
) -> None:
    if _SCHEMA["global_"].get("require_h1", True):
        _validate_h1(path, lines, classification)
    if not any(_H2_LINE.match(line) for line in lines):
        _error("snippet_missing_h2", path=str(path))

    required_reads_found = False
    required_reads_header_idx = None
    required_reads_text_header = False
    sources_found = False
    sources_header_idx = None
    for idx, line in enumerate(lines):
        if _REQUIRED_READS_HEADER.match(line):
            required_reads_found = True
            required_reads_header_idx = idx
            break
    for line in lines:
        if line.strip().lower() == "required reads:":
            required_reads_text_header = True
            break
    for idx, line in enumerate(lines):
        if _SOURCES_HEADER.match(line):
            sources_found = True
            sources_header_idx = idx
            break
    if _SCHEMA["global_"].get("require_required_reads", True):
        if not required_reads_found:
            _error("snippet_required_reads_missing", path=str(path))
        if required_reads_text_header:
            _error("snippet_required_reads_text_header", path=str(path))
        if required_reads_found and required_reads_header_idx is not None:
            if not lines[required_reads_header_idx].startswith("## "):
                _error("snippet_required_reads_header_level", path=str(path))
            h2_indices = [i for i, line in enumerate(lines) if _H2_LINE.match(line)]
            if h2_indices and h2_indices[0] != required_reads_header_idx:
                _error("snippet_required_reads_not_first_h2", path=str(path))

    if sources_found and sources_header_idx is not None:
        if not lines[sources_header_idx].startswith("## "):
            _error("snippet_sources_header_level", path=str(path))


def _is_global_doc(path: Path) -> bool:
    return "global" in path.parts


def _global_docs_prefixes() -> tuple[str, ...]:
    absolute_prefixes = tuple(f"{root}/" for root in GLOBAL_DOCS_ROOTS)
    return ("~/.teleclaude/docs/", *absolute_prefixes)


def _resolve_see_also_ref(ref: str, project_root: Path) -> Path | None:
    """Resolve a See Also soft reference to an absolute path for existence check."""
    if ref.startswith("~"):
        expanded = str(Path(ref).expanduser())
        absolute_prefixes = _global_docs_prefixes()[1:]
        if expanded.startswith(absolute_prefixes):
            return resolve_global_doc_source(project_root, Path(expanded))
        return Path(expanded).resolve()
    absolute_prefixes = _global_docs_prefixes()[1:]
    if ref.startswith(absolute_prefixes):
        return resolve_global_doc_source(project_root, Path(ref))
    if ref.startswith("docs/"):
        return (project_root / ref).resolve()
    return None


def _validate_see_also_ref(ref_line: str, path: Path, project_root: Path) -> None:
    """Validate a single list item inside a ``## See Also`` section."""
    raw = ref_line.split("\u2014")[0].split(" -- ")[0].strip()
    if not raw:
        return
    if raw.startswith("http://") or raw.startswith("https://"):
        return

    is_global = _is_global_doc(path)
    prefixes = _global_docs_prefixes()

    if is_global:
        if not raw.startswith(prefixes):
            _error(
                "snippet_see_also_bad_prefix",
                path=str(path),
                ref=raw,
                expected="~/.teleclaude/docs/...",
            )
            return
    else:
        if not raw.startswith("docs/") and not raw.startswith(prefixes):
            _error(
                "snippet_see_also_bad_prefix",
                path=str(path),
                ref=raw,
                expected="docs/... or ~/.teleclaude/docs/...",
            )
            return

    if not raw.endswith(".md"):
        _error("snippet_see_also_missing_extension", path=str(path), ref=raw)
        return

    try:
        resolved = _resolve_see_also_ref(raw, project_root)
    except DocsPublisherResolutionError as exc:
        _error("snippet_global_source_resolution_failed", path=str(path), ref=raw, reason=str(exc))
        return
    if resolved is None:
        _error("snippet_see_also_unresolvable", path=str(path), ref=raw)
        return
    if not resolved.exists():
        _error("snippet_see_also_missing", path=str(path), ref=raw, resolved=str(resolved))


def _validate_snippet_refs(path: Path, lines: list[str], project_root: Path, *, domains: set[str]) -> None:  # pylint: disable=too-many-branches
    in_required_reads = False
    in_see_also = False
    in_code_block = False
    for line in lines:
        if _CODE_FENCE_LINE.match(line.strip()):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if _REQUIRED_READS_HEADER.match(line):
            in_required_reads = True
            in_see_also = False
            continue
        if _SEE_ALSO_HEADER.match(line):
            in_required_reads = False
            in_see_also = True
            continue
        if _H2_LINE.match(line):
            in_required_reads = False
            in_see_also = False
            continue
        if _HTML_COMMENT_LINE.match(line):
            continue
        line_without_inline = _INLINE_CODE_SPAN.sub("", line)
        if "@" in line_without_inline:
            if in_see_also:
                _error("snippet_see_also_inline_ref", path=str(path), line=line.strip())
            elif not in_required_reads:
                _error("snippet_required_reads_outside_section", path=str(path), line=line.strip())
        if in_see_also:
            m = _SEE_ALSO_LIST_LINE.match(line)
            if m:
                _validate_see_also_ref(m.group(1), path, project_root)

    for error in collect_inline_ref_errors(project_root, path, lines, domains=domains):
        _error(error["code"], **{k: v for k, v in error.items() if k != "code"})


def _validate_snippet_sections(  # pylint: disable=too-many-locals,too-many-branches
    path: Path,
    lines: list[str],
    meta: Mapping[str, object],
    *,
    classification: SnippetClassification | None,
) -> None:
    h2_titles: list[str] = []
    in_code_block = False
    for line in lines:
        if _CODE_FENCE_LINE.match(line.strip()):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if _H2_LINE.match(line):
            h2_titles.append(line.lstrip("#").strip())
    normalized_titles = [_normalize_section_title(t) for t in h2_titles]

    if "see also" in normalized_titles:
        last_h2 = normalized_titles[-1] if normalized_titles else ""
        if last_h2 != "see also":
            _error("snippet_see_also_not_last", path=str(path))

    if "baseline" not in path.parts:
        for field in ("description",):
            if not isinstance(meta.get(field), str) or not meta.get(field):
                _error("snippet_missing_frontmatter_field", path=str(path), field=field)

    visibility_val = meta.get("visibility")
    if visibility_val is not None:
        if not isinstance(visibility_val, str) or visibility_val not in SNIPPET_VISIBILITY_VALUES:
            _error("snippet_invalid_visibility_value", path=str(path), value=str(visibility_val))

    snippet_type = _snippet_type_for_validation(classification)
    if snippet_type:
        type_key = str(snippet_type).lower()
        section_rules = _SCHEMA["sections"].get(type_key, {})  # type: ignore[var-annotated]
        required = [_normalize_section_title(s) for s in section_rules.get("required", [])]
        allowed = [_normalize_section_title(s) for s in section_rules.get("allowed", [])]
        for req in required:
            if req not in normalized_titles:
                _error("snippet_missing_required_section", path=str(path), section=req)
        for title in normalized_titles:
            if title in ("required reads", "see also", "sources"):
                continue
            if title not in allowed:
                _error("snippet_unknown_section", path=str(path), section=title)


# ---------------------------------------------------------------------------
# Third-party validation
# ---------------------------------------------------------------------------


def _is_third_party_doc(path: Path, project_root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(project_root.resolve())
    except (OSError, ValueError):
        return False
    return len(rel.parts) >= 3 and rel.parts[0] == "docs" and rel.parts[1] == _THIRD_PARTY_TYPE


def _extract_sources_section(lines: list[str]) -> list[str]:
    in_sources = False
    sources: list[str] = []
    for line in lines:
        if _SOURCES_HEADER.match(line):
            in_sources = True
            continue
        if in_sources:
            if _HEADER_LINE.match(line):
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                sources.append(stripped[2:].strip())
    return sources


def _is_context7_id(value: str) -> bool:
    return bool(re.match(r"^/[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$", value))


def _is_web_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _extract_markdown_link_url(value: str) -> str | None:
    """Extract URL from a markdown link like [text](https://...)."""
    m = _MARKDOWN_LINK_RE.match(value)
    return m.group(2) if m else None


def _validate_third_party_frontmatter(path: Path, meta: Mapping[str, object], project_root: Path) -> None:
    for field in ("description",):
        if not isinstance(meta.get(field), str) or not meta.get(field):
            _error("snippet_missing_frontmatter_field", path=str(path), field=field)


def _validate_third_party_sources(path: Path, lines: list[str]) -> None:
    sources = _extract_sources_section(lines)
    for source in sources:
        if _is_context7_id(source):
            continue
        url = source
        md_url = _extract_markdown_link_url(source)
        if md_url:
            url = md_url
        if _is_web_url(url):
            continue
        _error("third_party_source_invalid", path=str(path), source=source)


def validate_third_party_doc(path: Path, content: str, project_root: Path) -> None:
    """Validate one third-party doc snippet."""
    if path.name in _THIRD_PARTY_INDEX_NAMES:
        return
    if content.lstrip().startswith("---"):
        try:
            post = parse_markdown(content)
            meta: Mapping[str, object] = post.metadata or {}
            body = post.content
        except Exception:  # pylint: disable=broad-exception-caught
            meta = {}
            body = content
    else:
        meta = {}
        body = content

    lines = body.splitlines()
    first_non_empty = next((line for line in lines if line.strip()), "")
    if not _H1_LINE.match(first_non_empty):
        _error("snippet_missing_h1", path=str(path))
    if not any(_H2_LINE.match(line) for line in lines):
        _error("snippet_missing_h2", path=str(path))

    _validate_third_party_frontmatter(path, meta, project_root)
    _validate_third_party_sources(path, lines)


def validate_third_party_docs(project_root: Path) -> None:
    """Validate third-party doc frontmatter and sources."""
    third_party_root = project_root / "docs" / "third-party"
    if not third_party_root.exists():
        return
    for path in sorted(third_party_root.rglob("*.md")):
        if path.name in _THIRD_PARTY_INDEX_NAMES:
            continue
        try:
            text = read_markdown(path)
        except OSError as exc:
            _error("third_party_read_failed", path=str(path), error=str(exc))
            continue
        validate_third_party_doc(path, text, project_root)


# ---------------------------------------------------------------------------
# Snippet entry points
# ---------------------------------------------------------------------------


def _iter_snippet_roots(project_root: Path) -> list[Path]:
    """Find all snippet root directories under the project."""
    return iter_snippet_roots(project_root)


_BASELINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")


def _domain_baseline_ids(domain: str, project_root: Path) -> set[str]:
    """Snippet ids inflated by a domain's resident baseline manifest."""
    baseline = project_root / "docs" / "global" / domain / "baseline.md"
    if not baseline.exists():
        return set()
    domains = load_domains(project_root)
    ids: set[str] = set()
    for ref in _BASELINE_REF_RE.findall(read_markdown(baseline)):
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=baseline)
        if resolved and resolved.exists():
            classification, _ = derive_snippet_classification(resolved, project_root=project_root, domains=domains)
            if classification is not None:
                ids.add(classification.id)
    return ids


def _iter_reachable_refs(start: Path, project_root: Path, seen: set[Path]) -> Iterator[tuple[str, Path]]:
    """Yield (snippet_id, containing_file) for every snippet transitively @-referenced from start."""
    try:
        text = read_markdown(start)
    except OSError:
        return
    domains = load_domains(project_root)
    for ref in _BASELINE_REF_RE.findall(text):
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=start)
        if not resolved or not resolved.exists() or resolved in seen:
            continue
        seen.add(resolved)
        classification, _ = derive_snippet_classification(resolved, project_root=project_root, domains=domains)
        if classification is not None:
            yield classification.id, start
        yield from _iter_reachable_refs(resolved, project_root, seen)


def _validate_baseline_dedup(project_root: Path, *, paths: list[Path] | None = None) -> None:
    """Fail when either baseline delivery mechanism also includes baseline content."""
    domains = load_domains(project_root)
    for snippets_root in _iter_snippet_roots(project_root):
        candidates = (
            (path for path in paths if path.is_relative_to(snippets_root))
            if paths is not None
            else snippets_root.rglob("*.md")
        )
        for path in sorted(candidates):
            if path.name == "index.yaml" or is_excluded_snippet_path(path, snippets_root):
                continue
            try:
                text = read_markdown(path)
            except OSError:
                continue
            classification, _ = derive_snippet_classification(path, project_root=project_root, domains=domains)
            if classification is None:
                continue
            if classification.type is not SnippetTaxonomy.PROCEDURE:
                continue
            required_refs, _ = extract_required_reads(text)
            for required_ref in required_refs:
                domain = generated_domain_bundle_domain(f"{_INLINE_REF_PREFIX}{required_ref}", domains=domains)
                if domain is None:
                    continue
                try:
                    baseline_ids = _domain_baseline_ids(domain, project_root)
                    bundle_path = resolve_ref_path(required_ref, root_path=project_root, current_path=path)
                    seen = {bundle_path} if bundle_path is not None else set()
                    for snippet_id, container in _iter_reachable_refs(path, project_root, seen):
                        if snippet_id in baseline_ids:
                            _error(
                                "baseline_dedup_violation", path=str(container), snippet_id=snippet_id, domain=domain
                            )
                except DocsPublisherResolutionError as exc:
                    _error(
                        "snippet_global_source_resolution_failed",
                        path=str(path),
                        ref=required_ref,
                        reason=str(exc),
                    )


def _resolve_todo_status_facts(project_root: Path) -> dict[str, TodoStatusFact] | None:
    """Load validation todo facts, or ``None`` when no todos DB is reachable.

    Returning ``None`` (DB genuinely absent — fresh clone, CI without state) skips
    the delivered_by todo-validity check rather than flagging every slug as
    missing. An empty map with a present DB is a real empty todo and still runs.
    """
    if local_store_presence(project_root).kind is not StorePresenceKind.ABSENT:
        return build_todo_status_facts(project_root)
    return None


def _containing_tier_root(path: Path, tier_roots: list[Path]) -> Path | None:
    """The declared tier root whose documentation home contains ``path``, or ``None``."""
    for root in tier_roots:
        try:
            path.resolve().relative_to((root / _DOCS_DIRNAME).resolve())
            return root
        except ValueError:
            continue
    return None


def _validate_scoped_paths(
    project_root: Path,
    paths: list[Path],
    *,
    snippet_roots: list[Path],
    tier_roots: list[Path],
    domains: set[str],
    todo_status_facts: Mapping[str, TodoStatusFact] | None = None,
) -> None:
    """Validate an explicit path list, matching each against project then tier roots."""
    for path in paths:
        if path.name == "index.yaml" or path.suffix != ".md":
            continue
        if _is_third_party_doc(path, project_root):
            try:
                text = read_markdown(path)
            except OSError as exc:
                _error("snippet_read_failed", path=str(path), error=str(exc))
                continue
            validate_third_party_doc(path, text, project_root)
            continue
        containing_root: Path | None = None
        for root in snippet_roots:
            try:
                path.resolve().relative_to(root.resolve())
                containing_root = root
                break
            except ValueError:
                continue
        if containing_root is not None:
            if is_excluded_snippet_path(path, containing_root):
                continue
            try:
                text = read_markdown(path)
            except OSError as exc:
                _error("snippet_read_failed", path=str(path), error=str(exc))
                continue
            validate_snippet(path, text, project_root, domains=domains, todo_status_facts=todo_status_facts)
            continue
        tier_root = _containing_tier_root(path, tier_roots)
        if tier_root is None:
            continue
        if is_excluded_snippet_path(path, tier_root / _DOCS_DIRNAME):
            continue
        try:
            text = read_markdown(path)
        except OSError as exc:
            _error("snippet_read_failed", path=str(path), error=str(exc))
            continue
        validate_snippet(path, text, tier_root, domains=domains, todo_status_facts=todo_status_facts)


def _validate_tier_roots(
    tier_roots: list[Path], *, domains: set[str], todo_status_facts: Mapping[str, TodoStatusFact] | None
) -> None:
    """Full-run validation of every declared, participating tier's documentation home.

    Walks both halves; a half-root ``baseline*.md`` manifest is checked as a
    manifest (its inline references), every other file as a snippet.
    """
    for tier_root in tier_roots:
        tier_docs_root = tier_root / _DOCS_DIRNAME
        if not tier_docs_root.exists():
            continue
        for path in sorted(tier_docs_root.rglob("*.md")):
            if path.name == "index.yaml":
                continue
            if is_excluded_snippet_path(path, tier_docs_root):
                continue
            if _BASELINE_SEGMENT in path.relative_to(tier_docs_root).parent.parts:
                continue
            try:
                text = read_markdown(path)
            except OSError as exc:
                _error("snippet_read_failed", path=str(path), error=str(exc))
                continue
            validate_snippet(path, text, tier_root, domains=domains, todo_status_facts=todo_status_facts)


def validate_all_snippets(
    project_root: Path,
    *,
    paths: list[Path] | None = None,
    tier_home: Path | None = None,
    full_run: bool = False,
) -> None:
    """Validate all doc snippets under the project. Collects validation findings.

    When *paths* is provided, only those files are validated (per-file scoped mode).
    Repo-wide passes (_validate_baseline_dedup, validate_third_party_docs) are skipped
    in scoped mode — they require the full repo and stay on full runs only.

    ``tier_home``, when given, additionally walks every declared,
    documentation-participating company and person tier's own documentation
    home under it: in scoped mode a path matching no project root is matched
    against the tier roots next; a full run also walks every tier root
    directly, passing that tier's own root as ``validate_snippet``'s root
    argument so classification, marker validation, and Required-read
    resolution dispatch to the tier the file actually belongs to. Callers pass
    it only for the platform-home publication branch and the home's markdown
    lint; every other repository's run passes none, so a malformed or
    uncommitted home tier file never reaches an unrelated repository's run.
    """
    with project_slug_resolution(), markdown_read_scope():
        _validate_all_snippets(project_root, paths=paths, tier_home=tier_home, full_run=full_run)


def _validate_all_snippets(
    project_root: Path,
    *,
    paths: list[Path] | None,
    tier_home: Path | None,
    full_run: bool,
) -> None:
    """Run the unchanged checks within the caller's declared-identity scope."""
    domains = load_domains(project_root)
    tier_roots = [root for root, _kind in iter_tier_snippet_roots(tier_home)] if tier_home is not None else []

    if paths is not None:
        snippet_roots = _iter_snippet_roots(project_root)
        _validate_scoped_paths(
            project_root,
            paths,
            snippet_roots=snippet_roots,
            tier_roots=tier_roots,
            domains=domains,
            todo_status_facts=_resolve_todo_status_facts(project_root) if full_run else None,
        )
        if full_run:
            _validate_baseline_dedup(project_root, paths=paths)
        return

    todo_status_facts = _resolve_todo_status_facts(project_root)
    snippet_roots = _iter_snippet_roots(project_root)
    for snippets_root in snippet_roots:
        try:
            rel_path = snippets_root.relative_to(project_root)
            include_baseline = str(rel_path) in ("docs/global", "agents/docs")
        except ValueError:
            include_baseline = False
        for path in sorted(snippets_root.rglob("*.md")):
            if path.name == "index.yaml":
                continue
            if is_excluded_snippet_path(path, snippets_root):
                continue
            if not include_baseline and "baseline" in str(path):
                continue
            try:
                text = read_markdown(path)
            except OSError as exc:
                _error("snippet_read_failed", path=str(path), error=str(exc))
                continue
            validate_snippet(path, text, project_root, domains=domains, todo_status_facts=todo_status_facts)
    _validate_tier_roots(tier_roots, domains=domains, todo_status_facts=todo_status_facts)
    _validate_baseline_dedup(project_root)
    validate_third_party_docs(project_root)
