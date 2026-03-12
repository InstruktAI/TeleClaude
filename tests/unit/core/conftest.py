"""Conftest for tests/unit/core — sets TELECLAUDE_CONFIG_PATH before db.py loads.

tests/unit/conftest.py overrides _isolate_test_environment with a no-op (no DB
access assumed).  Tests in this package DO import teleclaude.core.db for static
method testing, so they need a valid config path before the module is imported.
"""

from __future__ import annotations

import os
from pathlib import Path

# Point to the real config.yml that exists in the worktree root.
# This must run at module-import time (before any test imports db.py).
_worktree_root = Path(__file__).resolve().parents[3]
os.environ["TELECLAUDE_CONFIG_PATH"] = str(_worktree_root / "config.yml")
