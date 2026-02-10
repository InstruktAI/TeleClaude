"""Unit tests for identity resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.config.schema import PersonEntry
from teleclaude.core.identity import IdentityContext, IdentityResolver, get_identity_resolver


def test_identity_context_creation() -> None:
    ctx = IdentityContext(
        email="alice@example.com",
        role="admin",
        username="alice",
        resolution_source="token",
    )
    assert ctx.email == "alice@example.com"
    assert ctx.role == "admin"
    assert ctx.username == "alice"
    assert ctx.resolution_source == "token"


def test_resolver_lookup_by_email() -> None:
    people = [
        PersonEntry(name="Alice", email="alice@example.com", username="alice", role="admin"),
        PersonEntry(name="Bob", email="bob@example.com", role="member"),
    ]
    resolver = IdentityResolver(people)

    # Found
    ctx = resolver.resolve_by_email("alice@example.com")
    assert ctx is not None
    assert ctx.email == "alice@example.com"
    assert ctx.role == "admin"
    assert ctx.username == "alice"
    assert ctx.resolution_source == "email"

    # Case insensitive
    ctx = resolver.resolve_by_email("ALICE@example.com")
    assert ctx is not None
    assert ctx.email == "alice@example.com"

    # Not found
    assert resolver.resolve_by_email("unknown@example.com") is None


def test_resolver_lookup_by_username() -> None:
    people = [
        PersonEntry(name="Alice", email="alice@example.com", username="alice", role="admin"),
        PersonEntry(name="Bob", email="bob@example.com", role="member"),
    ]
    resolver = IdentityResolver(people)

    # Found
    ctx = resolver.resolve_by_username("alice")
    assert ctx is not None
    assert ctx.email == "alice@example.com"
    assert ctx.role == "admin"
    assert ctx.username == "alice"
    assert ctx.resolution_source == "username"

    # Case insensitive
    ctx = resolver.resolve_by_username("ALICE")
    assert ctx is not None
    assert ctx.username == "alice"

    # Not found
    assert resolver.resolve_by_username("unknown") is None
    # Bob has no username
    assert resolver.resolve_by_username("bob") is None


def test_get_identity_resolver_bootstrap(tmp_path: Path) -> None:
    # Use global_config fixture or similar?
    # For now, patch load_global_config to return mock data.
    from teleclaude.config.schema import GlobalConfig

    mock_config = GlobalConfig(
        people=[
            PersonEntry(name="Alice", email="alice@example.com", username="alice", role="admin"),
        ]
    )

    with patch("teleclaude.core.identity.load_global_config", return_value=mock_config):
        # Reset singleton for test
        import teleclaude.core.identity as identity_mod

        identity_mod._resolver = None

        resolver = get_identity_resolver()
        assert resolver is not None
        assert resolver.resolve_by_email("alice@example.com") is not None


def test_person_entry_invalid_role() -> None:
    with pytest.raises(ValueError, match="Input should be 'admin', 'member', 'contributor' or 'newcomer'"):
        PersonEntry(name="Alice", email="alice@example.com", role="invalid")  # type: ignore
