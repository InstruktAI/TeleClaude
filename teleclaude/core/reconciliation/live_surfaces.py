"""The live surfaces that address the active release through ``current``.

Nothing live names a release: every surface points at the installation's ``current`` pointer, so
switching it rewrites no service definition, hook command or link
(``local/projects/teleclaude/design/architecture/installation``).
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from teleclaude.core.reconciliation.installation import InstallationLayout

_PUBLISHED_EXECUTABLE = Path(".local") / "bin" / "telec"
_EXECUTABLE_DIRECTORY = "bin"
_EXECUTABLE_NAME = "telec"
_STAGED_LINK_PREFIX = ".telec."


def through_current(path: Path, layout: InstallationLayout | None = None) -> Path:
    """Map a path inside an installed release to the same path under ``current``; any other path is unchanged.

    A live surface that needs a path inside a release names it through ``current``, so a switch rewrites
    nothing and a pruned release breaks nothing that runs.
    """
    resolved_layout = layout or InstallationLayout()
    try:
        relative = path.resolve().relative_to(resolved_layout.releases.resolve())
    except ValueError:
        return path
    return resolved_layout.current.joinpath(*relative.parts[1:])


def published_telec_path() -> Path:
    """Where the global ``telec`` is published for the person's shell."""
    return Path.home() / _PUBLISHED_EXECUTABLE


def publish_telec(layout: InstallationLayout) -> Path:
    """Publish ``~/.local/bin/telec`` as a link to the active release's executable, through ``current``."""
    link = published_telec_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    staged = link.with_name(f"{_STAGED_LINK_PREFIX}{uuid4().hex}")
    staged.symlink_to(layout.current / _EXECUTABLE_DIRECTORY / _EXECUTABLE_NAME)
    try:
        os.replace(staged, link)
    except OSError:
        staged.unlink(missing_ok=True)
        raise
    return link
