"""Resolve registered documentation publishers and their source ownership."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import NamedTuple

import yaml

from teleclaude.domains import publishes_for_root
from teleclaude.paths import GLOBAL_DOCS_DIR, REPO_ROOT, ConfigFileName
from teleclaude.project_manifest import load_roots
from teleclaude.slug import normalize_slug

_DOMAIN_AGNOSTIC_DIR = "general"
_SNIPPETS_DIR = "snippets"


class DocsPublisherResolutionError(ValueError):
    """A deployed documentation path has no unambiguous publisher source."""


class Publisher(NamedTuple):
    """A registered project's global-documentation contribution."""

    slug: str
    docs_global: Path
    publishes: frozenset[str]


class PublisherRegistry(NamedTuple):
    """The resolved publisher ownership used by one reference-resolution pass."""

    owners: dict[str, Publisher]
    mother: Publisher | None


_PUBLISHER_REGISTRY: ContextVar[PublisherRegistry | None] = ContextVar("publisher_registry", default=None)


def project_slug(project_root: Path) -> str:
    """Read the canonical project slug without importing the full config loader."""
    config_file = project_root / ConfigFileName.OVERLAY
    if config_file.is_file():
        try:
            payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            payload = None
        if isinstance(payload, dict):
            slug = payload.get("project_slug")
            if isinstance(slug, str) and slug.strip():
                return slug.strip()
            name = payload.get("project_name")
            if isinstance(name, str) and name.strip():
                return normalize_slug(name)
    return normalize_slug(project_root.name)


def git_common_root(project_root: Path) -> Path:
    """Resolve a worktree to its shared git root when one is available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return project_root
    if result.returncode != 0:
        return project_root
    common_dir = result.stdout.strip()
    if not common_dir:
        return project_root
    common_path = Path(common_dir).resolve()
    return common_path.parent if common_path.name == ".git" else project_root


def gather_publishers(project_root: Path, current_docs_global: Path) -> list[Publisher]:
    """Collect every registered project that contributes global documentation."""
    publishers = [
        Publisher(project_slug(project_root), current_docs_global, frozenset(publishes_for_root(project_root)))
    ]
    seen = {project_root.resolve(), git_common_root(project_root).resolve()}
    for root in load_roots():
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        docs_global = root / "docs" / "global"
        if docs_global.is_dir():
            publishers.append(Publisher(project_slug(root), docs_global, frozenset(publishes_for_root(root))))
    return publishers


def mother_publisher(publishers: list[Publisher]) -> Publisher | None:
    """Identify the publisher whose docs source belongs to Mother's canonical checkout.

    The cross-cutting ``general`` domain is Mother-owned, identified by comparing
    git canonical roots rather than exact ``docs_global`` paths. ``REPO_ROOT``
    can reflect a different linked worktree than a publisher's live source even
    when both belong to Mother, so raw-path comparison would lose ownership.
    """
    mother_root = git_common_root(REPO_ROOT).resolve()
    for publisher in publishers:
        if git_common_root(publisher.docs_global.parent.parent).resolve() == mother_root:
            return publisher
    return None


def domain_owners(publishers: list[Publisher], *, mother: Publisher | None = None) -> dict[str, Publisher]:
    """Return one publisher per domain or raise for split ownership."""
    owners: dict[str, Publisher] = {}
    resolved_mother = mother if mother is not None else mother_publisher(publishers)
    if resolved_mother is not None:
        owners[_DOMAIN_AGNOSTIC_DIR] = resolved_mother
    for publisher in publishers:
        for domain in sorted(publisher.publishes):
            existing = owners.get(domain)
            if existing is not None and existing.slug != publisher.slug:
                raise DocsPublisherResolutionError(
                    f"split domain ownership: {domain} claimed by {existing.slug} and {publisher.slug}"
                )
            owners[domain] = publisher
    if resolved_mother is not None and not (resolved_mother.docs_global / _DOMAIN_AGNOSTIC_DIR).is_dir():
        owners.pop(_DOMAIN_AGNOSTIC_DIR, None)
    return owners


@contextmanager
def publisher_resolution(
    project_root: Path, *, publishers: list[Publisher] | None = None
) -> Generator[PublisherRegistry, None, None]:
    """Cache publisher ownership for every global reference in one processing pass."""
    resolved_publishers = (
        publishers if publishers is not None else gather_publishers(project_root, project_root / "docs" / "global")
    )
    mother = mother_publisher(resolved_publishers)
    registry = PublisherRegistry(domain_owners(resolved_publishers, mother=mother), mother)
    token = _PUBLISHER_REGISTRY.set(registry)
    try:
        yield registry
    finally:
        _PUBLISHER_REGISTRY.reset(token)


def resolve_global_doc_source(project_root: Path, candidate: Path) -> Path:
    """Map a deployed global-doc path to its registered publisher source.

    The merged index has no single source file and remains deployed. Domain and
    Mother-owned support paths resolve directly to their publisher trees even
    before a host has published its first documentation generation.
    """
    try:
        relative_path = candidate.expanduser().relative_to(GLOBAL_DOCS_DIR)
    except ValueError:
        return candidate
    if not relative_path.parts or relative_path.name == "index.yaml":
        return candidate
    registry = _PUBLISHER_REGISTRY.get()
    if registry is None:
        publishers = gather_publishers(project_root, project_root / "docs" / "global")
        mother = mother_publisher(publishers)
        registry = PublisherRegistry(domain_owners(publishers, mother=mother), mother)
    root_name, *tail = relative_path.parts
    if root_name == _SNIPPETS_DIR:
        if registry.mother is None:
            raise DocsPublisherResolutionError("Mother publisher is unavailable for global snippets")
        return registry.mother.docs_global / _SNIPPETS_DIR / Path(*tail)
    owner = registry.owners.get(root_name)
    if owner is None:
        return candidate
    return owner.docs_global / root_name / Path(*tail)
