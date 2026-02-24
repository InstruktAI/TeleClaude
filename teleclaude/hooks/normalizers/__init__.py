"""Inbound normalizers."""

from __future__ import annotations

from teleclaude.hooks.inbound import NormalizerRegistry
from teleclaude.hooks.normalizers.github import normalize_github


def register_builtin_normalizers(registry: NormalizerRegistry) -> None:
    """Register all built-in platform normalizers."""
    registry.register("github", normalize_github)
