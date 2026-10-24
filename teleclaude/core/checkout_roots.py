"""Resolve the workflow and purpose roots for an associated checkout pair."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.checkout_association import CheckoutPurpose, checkout_association_for
from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.paths import TELECLAUDE_SOURCE_HOME
from teleclaude.project_root import resolve_git_root
from teleclaude.slug import validate_slug


@dataclass(frozen=True)
class CheckoutRoots:
    """Physical invocation location and the logical project's owned roots."""

    active: Path
    workflow_state: Path
    authoring: Path
    installed: Path
    purpose: CheckoutPurpose | None


def resolve_checkout_roots(
    start: str | Path,
    *,
    registry_path: Path = TELECLAUDE_SOURCE_HOME / "projects.yaml",
) -> CheckoutRoots:
    """Resolve all checkout-backed roots from one association observation."""
    active = resolve_git_root(start)
    owning = resolve_project_state_root(active)
    association = checkout_association_for(active, registry_path)
    if association is None:
        return CheckoutRoots(active, owning, owning, owning, None)

    purpose = CheckoutPurpose.INSTALLED if active == association.project_root else CheckoutPurpose.DEVELOPMENT
    return CheckoutRoots(
        active=active,
        workflow_state=association.project_root,
        authoring=association.development_checkout,
        installed=association.project_root,
        purpose=purpose,
    )


def worktree_location(start: str | Path, slug: str) -> tuple[Path, Path]:
    """Return an existing worktree in place, or the authoring location for a new one."""
    validate_slug(slug)
    roots = resolve_checkout_roots(start)
    for checkout in dict.fromkeys((roots.installed, roots.authoring)):
        candidate = checkout / WORKTREE_DIR / slug
        if candidate.exists():
            return candidate, checkout
    return roots.authoring / WORKTREE_DIR / slug, roots.authoring
