"""Record the commit a maintenance run executed against, for the release acceptance journeys."""

from __future__ import annotations

from pathlib import Path

from teleclaude.git import Repo

_MARKER_FILE = ".release-marker"


def main() -> int:
    """Write the full commit of the checkout this action runs in to the marker file."""
    root = Path.cwd()
    (root / _MARKER_FILE).write_text(Repo(str(root)).head.commit.hexsha, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
