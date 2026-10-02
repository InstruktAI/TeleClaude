"""Closed quality-check family vocabulary shared across gate composition."""

from enum import StrEnum


class QualityCheckFamily(StrEnum):
    """Capability families selected inside TeleClaude's guardrails lane."""

    CODE = "code"
    DOCUMENTATION = "docs"
    AGENTS = "agents"


__all__ = ["QualityCheckFamily"]
