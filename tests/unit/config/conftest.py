"""Shared helpers for daemon-config (`_build_config`) tests."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import pytest

import teleclaude.config as config_module
from teleclaude.config import Config

BuildConfig = Callable[[dict[str, object]], Config]  # guard: loose-dict - YAML-style test input


@pytest.fixture
def build_config() -> BuildConfig:
    """Return a builder that constructs a daemon `Config` from override dicts.

    The base merges a minimal valid computer + agents section onto
    ``DEFAULT_CONFIG``; callers layer their own overrides on top. Binary
    resolution is patched so tests do not depend on installed agent CLIs.
    """

    def _build(overrides: dict[str, object]) -> Config:  # guard: loose-dict - YAML-style test input
        raw = config_module._deep_merge(
            config_module.DEFAULT_CONFIG,
            {
                "computer": {
                    "name": "local-box",
                    "user": "dev",
                    "role": "builder",
                    "host": "localhost",
                    "default_working_dir": "/workspace/teleclaude",
                },
                "agents": {
                    "default": "claude",
                    "claude": {"enabled": True},
                    "gemini": {"enabled": False},
                    "codex": {"enabled": False},
                },
            },
        )
        raw = config_module._deep_merge(raw, overrides)

        with (
            patch.object(config_module, "resolve_tmux_binary", return_value="tmux"),
            patch.object(config_module, "resolve_agent_binary", side_effect=lambda name: f"/usr/bin/{name}"),
        ):
            return config_module._build_config(raw)

    return _build
