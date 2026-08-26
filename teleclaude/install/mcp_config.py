"""Resolve TeleClaude-managed MCP server names for agent CLI installers."""

from __future__ import annotations

from pathlib import Path

from teleclaude.mcp.registry import load_effective_registry


def load_managed_mcp_server_names(repo_root: Path) -> set[str]:
    """Return all TeleClaude-owned MCP server slugs from the effective registry."""
    return set(load_effective_registry(repo_root).servers)
