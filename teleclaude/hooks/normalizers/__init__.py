"""Inbound normalizers."""

from __future__ import annotations

from teleclaude.hooks.inbound import NormalizerRegistry
from teleclaude.hooks.normalizers.github import normalize_github
from teleclaude.hooks.normalizers.whatsapp import normalize_whatsapp_webhook


def register_builtin_normalizers(registry: NormalizerRegistry) -> None:
    """Register all built-in platform normalizers."""
    registry.register("github", normalize_github)
    registry.register("whatsapp", normalize_whatsapp_webhook)
