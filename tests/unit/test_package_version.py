"""Tests for package runtime version exposure."""

from __future__ import annotations

import re

from teleclaude import __version__


def test_runtime_version_is_semver() -> None:
    """Package root exports a semantic version-like string."""
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", __version__) is not None
