"""Resolve registered documentation publishers and their source ownership."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from teleclaude.config.loader import load_declared_project_config
from teleclaude.domains import publishes_for_root
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_DOCS_DIR, GLOBAL_DOCS_ROOTS, PEOPLE_DIR, REPO_ROOT
from teleclaude.project_manifest import load_roots
from teleclaude.slug import derive_project_slug, normalize_slug
from teleclaude.snippet_validation import is_generated_global_doc_artifact, tier_root_kind

_SNIPPETS_DIR = "snippets"
#: A tier's published half; its deployed address maps back here.
_TIER_PUBLISHED_DOCS = Path("docs") / "global"


class DocsResolutionMode(StrEnum):
    """Where a deployed global-doc address is read from during one expansion."""

    #: A registered publisher's source tree (its working checkout).
    SOURCE = "source"
    #: The deployed corpus, which holds only activated contributions.
    DEPLOYED = "deployed"


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
_RESOLUTION_MODE: ContextVar[DocsResolutionMode] = ContextVar("docs_resolution_mode", default=DocsResolutionMode.SOURCE)


def declared_project_slug(project_root: Path) -> str | None:
    """Return the project slug ``project_root`` declares in its own configuration, if any."""
    declared = load_declared_project_config(project_root)
    if declared is None or not (declared.project_slug or declared.project_name):
        return None
    return derive_project_slug(declared.project_slug, declared.project_name, project_root)


def project_slug(project_root: Path) -> str:
    """Return the project's declared slug, else its directory name."""
    return declared_project_slug(project_root) or normalize_slug(project_root.name)


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
    """Collect every registered project that contributes global documentation.

    The invoking checkout is its own project's publisher: a registered root
    carrying the slug ``project_root`` declares is skipped, whether it shares
    the invoking checkout's git root (a linked worktree) or not (a standalone
    clone). A root that declares no project slug, such as a tier home, skips
    nothing.
    """
    publishers = [
        Publisher(project_slug(project_root), current_docs_global, frozenset(publishes_for_root(project_root)))
    ]
    own_slug = declared_project_slug(project_root)
    seen = {project_root.resolve(), git_common_root(project_root).resolve()}
    for root in load_roots():
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        docs_global = root / "docs" / "global"
        if not docs_global.is_dir():
            continue
        slug = project_slug(root)
        if own_slug is not None and slug == own_slug:
            continue
        publishers.append(Publisher(slug, docs_global, frozenset(publishes_for_root(root))))
    return publishers


def mother_publisher(publishers: list[Publisher]) -> Publisher | None:
    """Identify the publisher whose docs source belongs to Mother's canonical checkout.

    Mother owns the ``snippets/`` support tree, identified by comparing git
    canonical roots rather than exact ``docs_global`` paths. ``REPO_ROOT`` can
    reflect a different linked worktree than a publisher's live source even when
    both belong to Mother, so raw-path comparison would lose ownership.
    """
    mother_root = git_common_root(REPO_ROOT).resolve()
    for publisher in publishers:
        if git_common_root(publisher.docs_global.parent.parent).resolve() == mother_root:
            return publisher
    return None


def domain_owners(publishers: list[Publisher]) -> dict[str, Publisher]:
    """Return one publisher per declared domain or raise for split ownership."""
    owners: dict[str, Publisher] = {}
    for publisher in publishers:
        for domain in sorted(publisher.publishes):
            existing = owners.get(domain)
            if existing is not None and existing.slug != publisher.slug:
                raise DocsPublisherResolutionError(
                    f"split domain ownership: {domain} claimed by {existing.slug} and {publisher.slug}"
                )
            owners[domain] = publisher
    return owners


@contextmanager
def publisher_resolution(
    project_root: Path, *, publishers: list[Publisher] | None = None
) -> Generator[PublisherRegistry, None, None]:
    """Cache publisher ownership for every global reference in one processing pass."""
    resolved_publishers = (
        publishers if publishers is not None else gather_publishers(project_root, project_root / "docs" / "global")
    )
    registry = PublisherRegistry(domain_owners(resolved_publishers), mother_publisher(resolved_publishers))
    token = _PUBLISHER_REGISTRY.set(registry)
    try:
        yield registry
    finally:
        _PUBLISHER_REGISTRY.reset(token)


@contextmanager
def deployed_resolution() -> Generator[None, None, None]:
    """Resolve every deployed global-doc address to the deployed corpus for one expansion.

    Only a tier's own published address, read from that tier's root, still
    maps into the tier's source; the mode is ambient, so transitive reads
    resolve the same way.
    """
    token = _RESOLUTION_MODE.set(DocsResolutionMode.DEPLOYED)
    try:
        yield
    finally:
        _RESOLUTION_MODE.reset(token)


def resolve_global_doc_source(project_root: Path, candidate: Path) -> Path:
    """Map a deployed global-doc path to its registered publisher source.

    A generated documentation artifact — the merged index or a domain's
    baseline bundle — has no single source file and remains deployed. Domain
    and Mother-owned support paths resolve directly to their publisher trees
    even before a host has published its first documentation generation.

    A ``companies/<slug>/...`` or ``people/<slug>/...`` address is a tier's
    published address (``general/policy/referencing-doc-snippets``). It resolves
    to that tier's source — under the same platform home as ``project_root`` —
    only when ``project_root`` is itself that same tier's own documentation
    home; a validated tier snippet's Required reads name only its own tier.
    Any other case, including a reference into a different tier, is left
    unresolved so the caller's existence check reports it.

    Under ``deployed_resolution`` every other address stays deployed.
    """
    expanded_candidate = candidate.expanduser()
    relative_path = None
    for docs_root in GLOBAL_DOCS_ROOTS:
        try:
            relative_path = expanded_candidate.relative_to(docs_root)
            break
        except ValueError:
            continue
    if relative_path is None:
        return candidate
    if not relative_path.parts:
        return candidate
    if is_generated_global_doc_artifact(relative_path):
        return GLOBAL_DOCS_DIR / relative_path
    root_name, *tail = relative_path.parts
    if root_name in (COMPANIES_ROOT.name, PEOPLE_DIR.name):
        if tier_root_kind(project_root) is not None and tail and tail[0] == project_root.name:
            return project_root.parent.parent / root_name / tail[0] / _TIER_PUBLISHED_DOCS / Path(*tail[1:])
        return candidate
    if _RESOLUTION_MODE.get() is DocsResolutionMode.DEPLOYED:
        return candidate
    registry = _PUBLISHER_REGISTRY.get()
    if registry is None:
        publishers = gather_publishers(project_root, project_root / "docs" / "global")
        registry = PublisherRegistry(domain_owners(publishers), mother_publisher(publishers))
    if root_name == _SNIPPETS_DIR:
        if registry.mother is None:
            raise DocsPublisherResolutionError("Mother publisher is unavailable for global snippets")
        return registry.mother.docs_global / _SNIPPETS_DIR / Path(*tail)
    owner = registry.owners.get(root_name)
    if owner is None:
        return candidate
    return owner.docs_global / root_name / Path(*tail)
