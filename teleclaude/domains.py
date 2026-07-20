"""Derive the set of valid global domains from registered publishers.

The valid-domain set is dynamic: it is exactly the union of every registered
project's ``business.publishes`` declarations. Each domain has exactly one
owning publisher — a domain declared by two registered projects is a split, and
sync hard-blocks on it — so the union defines validity with one owner per domain.

The heavy ``config.loader`` (pydantic) import is deferred into the functions so
that ``import teleclaude.domains`` stays cheap on the CLI help path (this module
is pulled transitively by ``snippet_validation`` and ``surface``).
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.project_manifest import load_roots


def publishes_for_root(root: Path) -> set[str]:
    """Return the domain slugs declared in ``root``'s ``business.publishes``.

    A missing ``teleclaude.yml`` is a legitimate non-publisher (empty set). A
    present-but-invalid or unreadable config fails loudly — silently dropping a
    publisher's domains would let them disappear from the valid-domain set and
    the merge without any signal. Each entry's ``trigger`` is validated at
    config load (required, single-line, bounded length) but is not returned
    here; see :func:`triggers_for_root`.
    """
    from teleclaude.config.loader import (  # noqa: PLC0415 - deferred: keep pydantic config.loader off the CLI-help import path
        load_project_config,
    )

    config_path = root / "teleclaude.yml"
    if not config_path.is_file():
        return set()
    config = load_project_config(config_path)
    return {entry.slug for entry in config.business.publishes}


def triggers_for_root(root: Path) -> dict[str, str]:
    """Return the domain → activation-trigger mapping declared in ``root``'s ``business.publishes``.

    A missing ``teleclaude.yml`` is a legitimate non-publisher (empty mapping).
    Each trigger is already validated (required, single-line, bounded length)
    at config load, so a published domain reaching this mapping always carries
    a usable trigger.
    """
    from teleclaude.config.loader import (  # noqa: PLC0415 - deferred: keep pydantic config.loader off the CLI-help import path
        load_project_config,
    )

    config_path = root / "teleclaude.yml"
    if not config_path.is_file():
        return {}
    config = load_project_config(config_path)
    return {entry.slug: entry.trigger for entry in config.business.publishes}


def valid_domains() -> set[str]:
    """Return the union of every registered project's ``business.publishes``."""
    domains: set[str] = set()
    for root in load_roots():
        domains |= publishes_for_root(root)
    return domains
