"""Select the activated or authoring documentation view for one checkout invocation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.checkout_association import CheckoutPurpose
from teleclaude.core.checkout_roots import resolve_checkout_roots
from teleclaude.core.worktree_layout import development_context_docs_for_checkout
from teleclaude.paths import GLOBAL_DOCS_DIR, PROJECTS_MANIFEST_PATH, TELECLAUDE_SOURCE_HOME

_INDEX_FILE_NAME = "index.yaml"
_AUTHORING_VIEW_UNAVAILABLE_MESSAGE = (
    "The authoring documentation generation is unavailable for {active}; run telec sync from {authoring} to publish it."
)


class ContextViewUnavailableError(ValueError):
    """An associated development checkout has no complete authoring generation to select."""


@dataclass(frozen=True)
class SelectedContextView:
    """The roots a single invocation uses for project context and published documentation."""

    active_root: Path
    installed_root: Path
    authoring_root: Path
    global_docs_root: Path
    purpose: CheckoutPurpose | None

    @property
    def uses_authoring_view(self) -> bool:
        """Whether this invocation selects the development checkout's published contracts."""
        return self.purpose is CheckoutPurpose.DEVELOPMENT


def select_context_view(project_root: Path) -> SelectedContextView:
    """Select one complete view by recorded checkout purpose; an absent dev generation is an error."""
    roots = resolve_checkout_roots(project_root, registry_path=TELECLAUDE_SOURCE_HOME / PROJECTS_MANIFEST_PATH.name)
    if roots.purpose is CheckoutPurpose.DEVELOPMENT:
        docs_root = development_context_docs_for_checkout(roots.authoring)
        if not docs_root.is_dir() or not (docs_root / _INDEX_FILE_NAME).is_file():
            raise ContextViewUnavailableError(
                _AUTHORING_VIEW_UNAVAILABLE_MESSAGE.format(active=roots.active, authoring=roots.authoring)
            )
        return SelectedContextView(
            active_root=roots.active,
            installed_root=roots.installed,
            authoring_root=roots.authoring,
            global_docs_root=docs_root,
            purpose=roots.purpose,
        )
    return SelectedContextView(
        active_root=roots.active,
        installed_root=roots.installed,
        authoring_root=roots.authoring,
        global_docs_root=GLOBAL_DOCS_DIR,
        purpose=roots.purpose,
    )
