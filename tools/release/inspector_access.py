"""Check declared inspector paths and runtime trees under the actual provider UID."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

_PATHS = "paths"
_TREES = "trees"
_PATH = "path"
_MODE = "mode"
_INVALID = "Inspector bootstrap paths are unavailable or unsafe."
_MAX_REQUEST = 1024 * 1024
_UTF8 = "utf-8"
_ACCESS_BITS = os.R_OK | os.W_OK | os.X_OK


def _walk_error(error: OSError) -> None:
    """Fail instead of silently skipping an inaccessible dependency directory."""
    raise error


def _check_tree(root: Path) -> None:
    """Require readable files/searchable directories and contained runtime symlinks."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError(_INVALID)
    resolved = root.resolve(strict=True)
    for directory, directories, files in os.walk(root, onerror=_walk_error, followlinks=False):
        if not os.access(directory, os.R_OK | os.X_OK):
            raise ValueError(_INVALID)
        for name in directories + files:
            path = Path(directory) / name
            if path.is_symlink() and not path.resolve(strict=True).is_relative_to(resolved):
                raise ValueError(_INVALID)
            mode = os.R_OK | os.X_OK if path.is_dir() else os.R_OK
            if not os.access(path, mode):
                raise ValueError(_INVALID)


def main() -> int:
    """Consume only path/access metadata; emit no paths, file bytes or exception text."""
    try:
        content = sys.stdin.buffer.read(_MAX_REQUEST + 1)
        if len(content) > _MAX_REQUEST:
            raise ValueError(_INVALID)
        payload = json.loads(content.decode(_UTF8))
        if not isinstance(payload, dict) or set(payload) != {_PATHS, _TREES}:
            raise ValueError(_INVALID)
        paths, trees = payload[_PATHS], payload[_TREES]
        if not isinstance(paths, list) or not isinstance(trees, list):
            raise ValueError(_INVALID)
        for item in paths:
            if (
                not isinstance(item, dict)
                or set(item) != {_PATH, _MODE}
                or not isinstance(item[_PATH], str)
                or type(item[_MODE]) is not int
                or not 0 < item[_MODE] <= _ACCESS_BITS
                or not os.access(item[_PATH], item[_MODE])
            ):
                raise ValueError(_INVALID)
        if not all(isinstance(tree, str) for tree in trees):
            raise ValueError(_INVALID)
        for tree in cast(list[str], trees):
            _check_tree(Path(tree))
    except (OSError, RuntimeError, ValueError, UnicodeError):
        print(_INVALID, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
