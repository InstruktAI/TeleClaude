"""Derive the set of valid global domains from registered publishers.

The valid-domain set is dynamic: it is exactly the union of every registered
project's ``business.publishes`` declarations. Each domain has exactly one
owning publisher — a domain declared by two registered projects is a split, and
sync hard-blocks on it — so the union defines validity with one owner per domain.

Each publisher's ``business`` section is read from its loaded project
configuration; loading migrates in memory and writes nothing, so discovering
domains never changes another publisher's configuration.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from teleclaude.config.loader import load_declared_project_config
from teleclaude.config.schema import BusinessConfig
from teleclaude.project_manifest import load_roots
from teleclaude.project_root import declaration_root

_RESOLUTION_SCOPE = "domain_business_resolution"
_BUSINESS: ContextVar[dict[Path, BusinessConfig] | None] = ContextVar(_RESOLUTION_SCOPE, default=None)


@contextmanager
def domain_resolution() -> Iterator[None]:
    """Reuse successful publisher declarations within one synchronous operation."""
    if _BUSINESS.get() is not None:
        yield
        return
    token = _BUSINESS.set({})
    try:
        yield
    finally:
        _BUSINESS.reset(token)


def publishes_for_root(root: Path) -> set[str]:
    """Return the domain slugs declared in ``root``'s ``business.publishes``.

    A missing ``teleclaude.yml`` is a legitimate non-publisher (empty set). A
    present-but-invalid or unreadable publisher declaration fails loudly —
    silently dropping a publisher's domains would let them disappear from the
    valid-domain set and the merge without any signal. Each entry's ``trigger``
    is validated here but is not returned; see :func:`triggers_for_root`.
    """
    business = _business_for_root(root)
    if business is None:
        return set()
    return {entry.slug for entry in business.publishes}


def triggers_for_root(root: Path) -> dict[str, str]:
    """Return the domain → activation-trigger mapping declared in ``root``'s ``business.publishes``.

    A missing ``teleclaude.yml`` is a legitimate non-publisher (empty mapping).
    Each trigger is validated while extracting the publisher declaration, so a
    published domain reaching this mapping always carries a usable trigger.
    """
    business = _business_for_root(root)
    if business is None:
        return {}
    return {entry.slug: entry.trigger for entry in business.publishes}


def _business_for_root(root: Path) -> BusinessConfig | None:
    """Read one publisher's business declaration from its loaded project configuration.

    The declaration is read from the checkout that owns ``root``: a linked
    worktree carries a branch copy and is never authoritative for it.
    """
    declarations = _BUSINESS.get()
    key = declaration_root(root).expanduser().absolute()
    if declarations is not None and key in declarations:
        return declarations[key]
    declared = load_declared_project_config(key)
    if declared is None:
        return None
    if declarations is not None:
        declarations[key] = declared.business
    return declared.business


def valid_domains() -> set[str]:
    """Return the union of every registered project's ``business.publishes``."""
    domains: set[str] = set()
    for root in load_roots():
        domains |= publishes_for_root(root)
    return domains
