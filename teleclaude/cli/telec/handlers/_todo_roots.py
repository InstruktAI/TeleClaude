"""Resolve the invocation project root for local todo commands."""

from __future__ import annotations

import sys
from pathlib import Path

from teleclaude.project_root import resolve_invocation_roots

__all__ = ["_resolve_project_root_or_exit"]

_PROJECT_ROOT_REFUSAL_TEMPLATE = "Error: {detail}"


def _resolve_project_root_or_exit() -> Path:
    """Resolve the invocation project root, or exit with a clean CLI error.

    ``require_project_root`` raises ``FileNotFoundError`` when the
    invocation cwd does not resolve to a project checkout; surfaced as a raw
    traceback otherwise, unlike the daemon API's equivalent clean 400.
    """
    try:
        return resolve_invocation_roots().require_project_root()
    except FileNotFoundError as exc:
        print(_PROJECT_ROOT_REFUSAL_TEMPLATE.format(detail=exc), file=sys.stderr)
        raise SystemExit(1) from exc
