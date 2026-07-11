"""TTS packaging boundary: the baseline install and the `tts` extra resolve the right deps."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.process

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERSION_SEP = "=="
_ELEVENLABS = "elevenlabs"
_MLX_PIPELINE = ("misaki", "num2words", "phonemizer-fork")
_TTS_EXCLUSIVE = frozenset({_ELEVENLABS, *_MLX_PIPELINE})
_HOST_HAS_MLX = sys.platform == "darwin" and platform.machine() == "arm64"


def _exported_packages(*extra_args: str) -> set[str]:
    """Resolve the locked install set for the host, returning top-level package names.

    Mirrors the real baseline install surface: ``uv sync`` / ``make install`` pull the
    default ``dev`` group, so the export keeps it too — a TTS-exclusive package leaking
    in transitively through dev would still be caught.
    """
    result = subprocess.run(
        ["uv", "export", "--frozen", "--no-emit-project", *extra_args],
        cwd=str(_REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    names: set[str] = set()
    for raw in result.stdout.splitlines():
        tokens = raw.split()
        if not tokens:
            continue
        name, sep, _ = tokens[0].partition(_VERSION_SEP)
        if sep:
            names.add(name)
    return names


def test_baseline_install_excludes_tts_exclusive_deps() -> None:
    """A baseline (no-extra) locked install must not pull the TTS-exclusive deps."""
    baseline = _exported_packages()
    leaked = _TTS_EXCLUSIVE & baseline
    assert leaked == frozenset()


def test_tts_extra_includes_tts_exclusive_deps() -> None:
    """`--extra tts` adds the TTS-exclusive deps (mlx text pipeline marker-gated)."""
    with_extra = _exported_packages("--extra", "tts")
    # elevenlabs is cross-platform — always present once the extra is selected.
    assert {_ELEVENLABS} <= with_extra
    # The mlx text pipeline carries a darwin/arm64 marker; present only on that host.
    mlx_present = set(_MLX_PIPELINE) & with_extra
    expected = set(_MLX_PIPELINE) if _HOST_HAS_MLX else set()
    assert mlx_present == expected
