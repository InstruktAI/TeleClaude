from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.utils import expand_env_vars

ALLOWED_TAXONOMIES = frozenset(TAXONOMY_TYPES)
_DEFAULT_DOMAINS = {"software-development"}


@dataclass(frozen=True)
class SnippetIdParts:
    scope: str
    taxonomy: str
    rest: str

    def value(self) -> str:
        if self.rest:
            return f"{self.scope}/{self.taxonomy}/{self.rest}"
        return f"{self.scope}/{self.taxonomy}"


def load_domains(project_root: Path) -> set[str]:
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return set(_DEFAULT_DOMAINS)
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return set(_DEFAULT_DOMAINS)
    if not isinstance(payload, dict):
        return set(_DEFAULT_DOMAINS)
    payload = expand_env_vars(payload)
    if not isinstance(payload, dict):
        return set(_DEFAULT_DOMAINS)
    business = payload.get("business")
    if not isinstance(business, dict):
        return set(_DEFAULT_DOMAINS)
    domains = business.get("domains")
    if isinstance(domains, list):
        clean = {d for d in domains if isinstance(d, str) and d.strip()}
        return clean or set(_DEFAULT_DOMAINS)
    if isinstance(domains, dict):
        clean = {k for k in domains.keys() if isinstance(k, str) and k.strip()}
        return clean or set(_DEFAULT_DOMAINS)
    return set(_DEFAULT_DOMAINS)


def _split_parts(value: str) -> tuple[list[str], bool]:
    raw = value.strip().strip("/")
    if not raw:
        return [], True
    parts = raw.split("/")
    has_empty = any(part == "" for part in parts)
    return parts, has_empty


def _allowed_scopes(domains: Iterable[str]) -> set[str]:
    return {"general", "project", *domains}


def validate_snippet_id_format(value: str, *, domains: Iterable[str]) -> tuple[SnippetIdParts | None, str | None]:
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


def expected_snippet_id_for_path(
    path: Path, *, project_root: Path, domains: Iterable[str]
) -> tuple[str | None, str | None]:
    try:
        rel = path.resolve().relative_to(project_root.resolve())
    except Exception:
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


def _expected_from_global(parts: tuple[str, ...], path: Path, domains: Iterable[str]) -> tuple[str | None, str | None]:
    if len(parts) < 3:
        return None, "missing_global_scope"
    scope_segment = parts[2]
    if scope_segment == "baseline":
        if path.name == "index.md" and len(parts) == 4:
            return None, None
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
    if path.name == "index.md":
        return None, "index_not_allowed"
    rest = _tail(parts, 4, path)
    if not rest:
        return None, "missing_slug"
    return SnippetIdParts(scope=scope, taxonomy=taxonomy, rest=rest).value(), None


def _expected_from_project(parts: tuple[str, ...], path: Path) -> tuple[str | None, str | None]:
    if len(parts) < 3:
        return None, "missing_taxonomy"
    if parts[2] == "baseline":
        if path.name == "index.md" and len(parts) == 4:
            return None, None
        return None, "project_baseline_only_index"
    taxonomy = parts[2]
    if taxonomy not in ALLOWED_TAXONOMIES:
        return None, "invalid_taxonomy"
    if path.name == "index.md":
        return None, "index_not_allowed"
    rest = _tail(parts, 3, path)
    if not rest:
        return None, "missing_slug"
    return SnippetIdParts(scope="project", taxonomy=taxonomy, rest=rest).value(), None


def _tail(parts: tuple[str, ...], start_idx: int, path: Path) -> str:
    name = path.stem if path.suffix else parts[-1]
    tail_parts = list(parts[start_idx:-1]) + [name]
    return "/".join([p for p in tail_parts if p])


def validate_inline_ref_format(ref: str, *, domains: Iterable[str]) -> str | None:
    if not ref:
        return "missing_ref"
    if not ref.startswith("@"):
        return "missing_at_prefix"
    if ref.startswith("@docs/"):
        return _validate_project_ref(ref[len("@docs/") :], domains)
    abs_prefix = f"@{Path.home()}/.teleclaude/docs/"
    if ref.startswith(abs_prefix):
        return _validate_global_ref(ref[len(abs_prefix) :], domains)
    return "invalid_prefix"


def _validate_project_ref(rel: str, domains: Iterable[str]) -> str | None:
    if rel.startswith("docs/"):
        return "nested_docs_root"
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
