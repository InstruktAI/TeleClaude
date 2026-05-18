"""Characterization tests for teleclaude.core.identity."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import teleclaude.core.identity as identity_module
from teleclaude.core.identity import IdentityContext, IdentityResolver, get_identity_resolver

ALICE_NAME = "Alice"
ALICE_EMAIL = "alice@example.com"
ADMIN_ROLE = "admin"
BOB_NAME = "Bob"
BOB_EMAIL = "bob@example.com"
CAROL_NAME = "Carol"
CAROL_EMAIL = "carol@example.com"
CUSTOMER_ROLE = "customer"
DISCORD_NICK = "Morriz"
DISCORD_ORIGIN = "discord"
DISCORD_PLATFORM_USER_ID = "discord-user-123"
MEMBER_ROLE = "member"
NO_ONE_EMAIL = "nobody@example.com"
TELEGRAM_ORIGIN = "telegram"
TELEGRAM_PLATFORM_USER_ID = "12345"
TERMINAL_ORIGIN = "terminal"
UNKNOWN_EMAIL = "unknown@example.com"
UNKNOWN_ORIGIN = "unknown_origin"
UNKNOWN_USER_ID = "unknown-user-999"


class TestIdentityContext:
    # IdentityContext is a plain dataclass with no computed properties.
    # Behavioral use of IdentityContext is covered by TestIdentityResolver.
    @pytest.mark.unit
    def test_default_fields_are_none(self):
        ctx = IdentityContext()
        assert ctx.person_name is None
        assert ctx.person_email is None
        assert ctx.person_role is None
        assert ctx.display_name_override is None
        assert ctx.platform is None
        assert ctx.platform_user_id is None

    @pytest.mark.unit
    def test_empty_context_has_no_display_name(self):
        ctx = IdentityContext()
        with pytest.raises(ValueError):
            _ = ctx.display_name

    @pytest.mark.unit
    def test_fields_can_be_set(self):
        ctx = IdentityContext(
            person_name=ALICE_NAME,
            person_email=ALICE_EMAIL,
            person_role=ADMIN_ROLE,
            platform=TELEGRAM_ORIGIN,
            platform_user_id=TELEGRAM_PLATFORM_USER_ID,
        )
        assert ctx.person_name == ALICE_NAME
        assert ctx.person_role == ADMIN_ROLE
        assert ctx.platform == TELEGRAM_ORIGIN


class TestIdentityResolver:
    @pytest.mark.unit
    def test_unknown_origin_returns_empty_context(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve(UNKNOWN_ORIGIN, {})
        assert ctx.person_role is None

    @pytest.mark.unit
    def test_discord_origin_unknown_user_returns_customer(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve(DISCORD_ORIGIN, {"user_id": UNKNOWN_USER_ID})
        assert ctx.person_role == CUSTOMER_ROLE
        assert ctx.platform == DISCORD_ORIGIN

    @pytest.mark.unit
    def test_empty_metadata_returns_empty_context(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve(TELEGRAM_ORIGIN, {})
        assert ctx.person_role is None

    @pytest.mark.unit
    def test_discord_origin_uses_configured_nick_as_display_name(self):
        person = MagicMock()
        person.name = ALICE_NAME
        person.email = ALICE_EMAIL
        person.role = ADMIN_ROLE
        person.username = None
        person_config = SimpleNamespace(
            creds=SimpleNamespace(
                telegram=None,
                discord=SimpleNamespace(user_id=DISCORD_PLATFORM_USER_ID, nick=DISCORD_NICK),
                whatsapp=None,
            )
        )
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity.load_person_config", return_value=person_config),
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
            patch("teleclaude.core.identity.PEOPLE_DIR") as mock_people_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[person])
            mock_dir.glob.return_value = [Path("/people/Alice/teleclaude.yml")]
            mock_people_dir.glob.return_value = [Path("/people/Alice/teleclaude.yml")]
            resolver = IdentityResolver()
            ctx = resolver.resolve(DISCORD_ORIGIN, {"user_id": DISCORD_PLATFORM_USER_ID})
        assert ctx.person_name == ALICE_NAME
        assert ctx.display_name == DISCORD_NICK

    @pytest.mark.unit
    def test_email_resolution_uses_configured_discord_nick_as_display_name(self):
        person = MagicMock()
        person.name = ALICE_NAME
        person.email = ALICE_EMAIL
        person.role = ADMIN_ROLE
        person.username = None
        person_config = SimpleNamespace(
            creds=SimpleNamespace(
                telegram=None,
                discord=SimpleNamespace(user_id=DISCORD_PLATFORM_USER_ID, nick=DISCORD_NICK),
                whatsapp=None,
            )
        )
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity.load_person_config", return_value=person_config),
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
            patch("teleclaude.core.identity.PEOPLE_DIR") as mock_people_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[person])
            mock_dir.glob.return_value = [Path("/people/Alice/teleclaude.yml")]
            mock_people_dir.glob.return_value = [Path("/people/Alice/teleclaude.yml")]
            resolver = IdentityResolver()
            ctx = resolver.resolve_by_email(ALICE_EMAIL)
        assert ctx.person_name == ALICE_NAME
        assert ctx.display_name == DISCORD_NICK


class TestResolveByEmail:
    @pytest.mark.unit
    def test_known_email_returns_identity(self):
        person = MagicMock()
        person.name = ALICE_NAME
        person.email = ALICE_EMAIL
        person.role = ADMIN_ROLE
        person.username = None
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[person])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve_by_email(ALICE_EMAIL)
        assert ctx.person_name == ALICE_NAME
        assert ctx.person_email == ALICE_EMAIL
        assert ctx.person_role == ADMIN_ROLE

    @pytest.mark.unit
    def test_unknown_email_returns_empty_context(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve_by_email(NO_ONE_EMAIL)
        assert ctx.person_name is None
        assert ctx.person_role is None

    @pytest.mark.unit
    def test_email_lookup_is_case_insensitive(self):
        person = MagicMock()
        person.name = BOB_NAME
        person.email = BOB_EMAIL
        person.role = MEMBER_ROLE
        person.username = None
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[person])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve_by_email(BOB_EMAIL.upper())
        assert ctx.person_name == BOB_NAME
        assert ctx.person_role == MEMBER_ROLE


class TestResolveTerminalOrigin:
    @pytest.mark.unit
    def test_terminal_origin_with_matching_email_returns_resolved_identity(self):
        person = MagicMock()
        person.name = CAROL_NAME
        person.email = CAROL_EMAIL
        person.role = ADMIN_ROLE
        person.username = None
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[person])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve(TERMINAL_ORIGIN, {"email": CAROL_EMAIL})
        assert ctx.person_name == CAROL_NAME
        assert ctx.person_role == ADMIN_ROLE
        assert ctx.platform == TERMINAL_ORIGIN
        assert ctx.platform_user_id == CAROL_EMAIL

    @pytest.mark.unit
    def test_terminal_origin_with_unrecognized_email_returns_empty_context(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve(TERMINAL_ORIGIN, {"email": UNKNOWN_EMAIL})
        assert ctx.person_role is None

    @pytest.mark.unit
    def test_terminal_origin_with_no_email_returns_empty_context(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            resolver = IdentityResolver()
            ctx = resolver.resolve(TERMINAL_ORIGIN, {})
        assert ctx.person_role is None


class TestGetIdentityResolver:
    @pytest.mark.unit
    def test_returns_identity_resolver_instance(self):
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []
            identity_module._resolver_instance = None
            resolver = get_identity_resolver()
        assert isinstance(resolver, IdentityResolver)
