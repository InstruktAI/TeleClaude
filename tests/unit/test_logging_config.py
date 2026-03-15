"""Characterization tests for teleclaude.logging_config."""

from __future__ import annotations

import importlib
import logging
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _import_logging_config(configure_logging_mock: MagicMock) -> types.ModuleType:
    stub = types.ModuleType("instrukt_ai_logging")
    stub.configure_logging = configure_logging_mock
    sys.modules.pop("teleclaude.logging_config", None)
    with patch.dict(sys.modules, {"instrukt_ai_logging": stub}):
        return importlib.import_module("teleclaude.logging_config")


def test_setup_logging_sets_override_calls_configure_and_syncs_sibling_level(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_logging_mock = MagicMock(
        side_effect=lambda _name: logging.getLogger("teleclaude").setLevel(logging.DEBUG)
    )
    module = _import_logging_config(configure_logging_mock)
    teleclaude_logger = logging.getLogger("teleclaude")
    events_logger = logging.getLogger("teleclaude.events")
    previous_app_level = teleclaude_logger.level
    previous_events_level = events_logger.level
    monkeypatch.delenv("TELECLAUDE_LOG_LEVEL", raising=False)

    try:
        teleclaude_logger.setLevel(logging.WARNING)
        events_logger.setLevel(logging.ERROR)

        module.setup_logging("DEBUG")

        configure_logging_mock.assert_called_once_with("teleclaude")
        assert module.os.environ["TELECLAUDE_LOG_LEVEL"] == "DEBUG"
        assert events_logger.level == logging.DEBUG
    finally:
        teleclaude_logger.setLevel(previous_app_level)
        events_logger.setLevel(previous_events_level)


def test_setup_logging_without_override_keeps_env_unset_and_uses_configured_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_logging_mock = MagicMock(side_effect=lambda _name: logging.getLogger("teleclaude").setLevel(logging.INFO))
    module = _import_logging_config(configure_logging_mock)
    teleclaude_logger = logging.getLogger("teleclaude")
    events_logger = logging.getLogger("teleclaude.events")
    previous_app_level = teleclaude_logger.level
    previous_events_level = events_logger.level
    monkeypatch.delenv("TELECLAUDE_LOG_LEVEL", raising=False)

    try:
        teleclaude_logger.setLevel(logging.ERROR)
        events_logger.setLevel(logging.CRITICAL)

        module.setup_logging()

        configure_logging_mock.assert_called_once_with("teleclaude")
        assert "TELECLAUDE_LOG_LEVEL" not in module.os.environ
        assert events_logger.level == logging.INFO
    finally:
        teleclaude_logger.setLevel(previous_app_level)
        events_logger.setLevel(previous_events_level)
