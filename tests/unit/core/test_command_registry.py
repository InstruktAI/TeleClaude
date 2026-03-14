"""Characterization tests for teleclaude.core.command_registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.core.command_registry import (
    get_command_service,
    init_command_service,
    reset_command_service,
)


def _make_mock_service():
    return MagicMock()


class TestInitCommandService:
    @pytest.mark.unit
    def test_init_returns_service(self):
        reset_command_service()
        svc = _make_mock_service()
        result = init_command_service(svc)
        assert result is svc
        reset_command_service()

    @pytest.mark.unit
    def test_double_init_raises_without_force(self):
        reset_command_service()
        svc = _make_mock_service()
        init_command_service(svc)
        with pytest.raises(RuntimeError):
            init_command_service(_make_mock_service())
        reset_command_service()

    @pytest.mark.unit
    def test_double_init_with_force_succeeds(self):
        reset_command_service()
        svc1 = _make_mock_service()
        svc2 = _make_mock_service()
        init_command_service(svc1)
        result = init_command_service(svc2, force=True)
        assert result is svc2
        reset_command_service()


class TestGetCommandService:
    @pytest.mark.unit
    def test_get_before_init_raises(self):
        reset_command_service()
        with pytest.raises(RuntimeError):
            get_command_service()

    @pytest.mark.unit
    def test_get_after_init_returns_service(self):
        reset_command_service()
        svc = _make_mock_service()
        init_command_service(svc)
        assert get_command_service() is svc
        reset_command_service()


class TestResetCommandService:
    @pytest.mark.unit
    def test_reset_clears_singleton(self):
        svc = _make_mock_service()
        init_command_service(svc, force=True)
        reset_command_service()
        with pytest.raises(RuntimeError):
            get_command_service()
