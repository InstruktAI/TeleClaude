"""Characterization tests for teleclaude.core.identity."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.identity import IdentityContext, IdentityResolver, get_identity_resolver


class TestIdentityContext:
    # IdentityContext is a plain dataclass with no computed properties.
    # Behavioral use of IdentityContext is covered by TestIdentityResolver.
    @pytest.mark.unit
    def test_default_fields_are_none(self):
        ctx = IdentityContext()
        assert ctx.person_name is None
        assert ctx.person_email is None
        assert ctx.person_role is None
        assert ctx.platform is None
        assert ctx.platform_user_id is None

    @pytest.mark.unit
    def test_fields_can_be_set(self):
        ctx = IdentityContext(
            person_name="Alice",
            person_email="alice@example.com",
            person_role="admin",
            platform="telegram",
            platform_user_id="12345",
        )
        assert ctx.person_name == "Alice"
        assert ctx.person_role == "admin"
        assert ctx.platform == "telegram"


class TestIdentityResolver:
    @pytest.mark.unit
    def test_unknown_origin_returns_customer_role(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve("unknown_origin", {})
        assert ctx.person_role == "customer"

    @pytest.mark.unit
    def test_discord_origin_unknown_user_returns_customer(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve("discord", {"user_id": "unknown-user-999"})
        assert ctx.person_role == "customer"
        assert ctx.platform == "discord"

    @pytest.mark.unit
    def test_empty_metadata_returns_customer(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve("telegram", {})
        assert ctx.person_role == "customer"


class TestGetIdentityResolver:
    @pytest.mark.unit
    def test_returns_identity_resolver_instance(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            import teleclaude.core.identity as identity_module

            identity_module._resolver_instance = None
            resolver = get_identity_resolver()
        assert isinstance(resolver, IdentityResolver)
