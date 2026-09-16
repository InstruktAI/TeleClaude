"""Resolved invocation context shared by the ``telec code`` commit-path commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.capabilities import Capabilities, TierPermissions, resolve_capabilities, resolve_tier_permissions
from teleclaude.project_root import declaration_root, resolve_invocation_roots


@dataclass(frozen=True)
class InvocationState:
    """Resolved roots and capability declaration for one code invocation."""

    context_root: Path | None
    repository_root: Path
    tier_permissions: TierPermissions | None

    @property
    def project_root(self) -> Path:
        """Return the repository root retained by existing code paths."""
        return self.repository_root

    @property
    def capabilities(self) -> Capabilities:
        """Return subscriptions from the acting tier, or legacy repository state."""
        if self.tier_permissions is not None:
            return self.tier_permissions.project_subscriptions
        return resolve_capabilities(self.repository_root)

    @property
    def is_invocation_context(self) -> bool:
        """Return whether this invocation has a declared acting context."""
        return self.tier_permissions is not None and self.tier_permissions.invocation_context

    @property
    def is_non_project_invocation_context(self) -> bool:
        """Return whether the acting context is a non-project tier root."""
        return self.is_invocation_context and not self.capabilities.is_target


def resolve_invocation_state() -> InvocationState:
    """Resolve the acting context and containing repository for one command."""
    roots = resolve_invocation_roots()
    permissions = (
        resolve_tier_permissions(declaration_root(roots.context_root)) if roots.context_root is not None else None
    )
    return InvocationState(
        context_root=roots.context_root,
        repository_root=roots.repository_root,
        tier_permissions=permissions,
    )
