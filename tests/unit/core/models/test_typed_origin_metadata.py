# guard: no-companion
"""Test spec (xfail) for R4: typed origin metadata for web and terminal.

Typed dataclasses must exist for web and terminal origin metadata, following
the existing adapter metadata pattern (from_dict/to_dict, dataclass with typed fields).
The identity resolver must accept these typed instances for resolution.

Remove ``pytestmark = pytest.mark.xfail`` once all tests pass after implementation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestWebOriginMetadata:
    """R4: Web origin metadata type with from_dict/to_dict."""

    @pytest.mark.unit
    def test_web_origin_metadata_exists(self) -> None:
        """A WebOriginMetadata (or equivalent) type must exist."""
        from teleclaude.core.models._adapter import WebOriginMetadata

        meta = WebOriginMetadata()
        assert meta is not None

    @pytest.mark.unit
    def test_web_origin_metadata_has_email_field(self) -> None:
        """Web origin metadata must carry an email field."""
        from teleclaude.core.models._adapter import WebOriginMetadata

        meta = WebOriginMetadata(email="user@example.com")
        assert meta.email == "user@example.com"

    @pytest.mark.unit
    def test_web_origin_metadata_from_dict_round_trip(self) -> None:
        """from_dict/to_dict must round-trip without data loss."""
        from teleclaude.core.models._adapter import WebOriginMetadata

        raw = {"email": "user@example.com"}
        meta = WebOriginMetadata.from_dict(raw)
        assert meta.email == "user@example.com"

        serialized = meta.to_dict()
        assert serialized["email"] == "user@example.com"

    @pytest.mark.unit
    def test_web_origin_metadata_to_dict_excludes_none(self) -> None:
        """to_dict must exclude None fields, matching existing adapter pattern."""
        from teleclaude.core.models._adapter import WebOriginMetadata

        meta = WebOriginMetadata()
        serialized = meta.to_dict()
        assert "email" not in serialized


class TestTerminalOriginMetadata:
    """R4: Terminal origin metadata type with from_dict/to_dict."""

    @pytest.mark.unit
    def test_terminal_origin_metadata_exists(self) -> None:
        """A TerminalOriginMetadata (or equivalent) type must exist."""
        from teleclaude.core.models._adapter import (
            TerminalOriginMetadata,
        )

        meta = TerminalOriginMetadata()
        assert meta is not None

    @pytest.mark.unit
    def test_terminal_origin_metadata_has_email_field(self) -> None:
        """Terminal origin metadata must carry an email field."""
        from teleclaude.core.models._adapter import (
            TerminalOriginMetadata,
        )

        meta = TerminalOriginMetadata(email="admin@example.com")
        assert meta.email == "admin@example.com"

    @pytest.mark.unit
    def test_terminal_origin_metadata_from_dict_round_trip(self) -> None:
        """from_dict/to_dict must round-trip without data loss."""
        from teleclaude.core.models._adapter import (
            TerminalOriginMetadata,
        )

        raw = {"email": "admin@example.com"}
        meta = TerminalOriginMetadata.from_dict(raw)
        assert meta.email == "admin@example.com"

        serialized = meta.to_dict()
        assert serialized["email"] == "admin@example.com"

    @pytest.mark.unit
    def test_terminal_origin_metadata_to_dict_excludes_none(self) -> None:
        """to_dict must exclude None fields, matching existing adapter pattern."""
        from teleclaude.core.models._adapter import (
            TerminalOriginMetadata,
        )

        meta = TerminalOriginMetadata()
        serialized = meta.to_dict()
        assert "email" not in serialized


class TestIdentityResolverReadsTypedMetadata:
    """R4: Identity resolver can read from typed web/terminal origin metadata instances."""

    @pytest.mark.unit
    def test_resolver_resolves_identity_from_web_origin_metadata_instance(self) -> None:
        """Identity resolver must accept a WebOriginMetadata instance for resolution.

        Passes a typed instance (not a raw dict) to resolver.resolve(). This test
        xfails before R4 wires the typed schemas into the resolver; it becomes green
        when the resolver can consume typed metadata objects.
        """
        from teleclaude.core.models._adapter import WebOriginMetadata

        meta = WebOriginMetadata(email="webuser@example.com")

        person = MagicMock()
        person.name = "WebUser"
        person.email = "webuser@example.com"
        person.role = "member"
        person.username = None
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[person])
            mock_dir.glob.return_value = []

            from teleclaude.core.identity import IdentityResolver

            resolver = IdentityResolver()
            ctx = resolver.resolve("web", meta)
        assert ctx.person_name == "WebUser"
        assert ctx.person_role == "member"
        assert ctx.platform == "web"

    @pytest.mark.unit
    def test_resolver_resolves_identity_from_terminal_origin_metadata_instance(self) -> None:
        """Identity resolver must accept a TerminalOriginMetadata instance for resolution.

        Passes a typed instance (not a raw dict) to resolver.resolve(). This test
        xfails before R4 wires the typed schemas into the resolver; it becomes green
        when the resolver can consume typed metadata objects.
        """
        from teleclaude.core.models._adapter import (
            TerminalOriginMetadata,
        )

        meta = TerminalOriginMetadata(email="termuser@example.com")

        person = MagicMock()
        person.name = "TermUser"
        person.email = "termuser@example.com"
        person.role = "admin"
        person.username = None
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[person])
            mock_dir.glob.return_value = []

            from teleclaude.core.identity import IdentityResolver

            resolver = IdentityResolver()
            ctx = resolver.resolve("terminal", meta)
        assert ctx.person_name == "TermUser"
        assert ctx.person_role == "admin"
        assert ctx.platform == "terminal"
