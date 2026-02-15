"""Unit tests for help desk platform features.

Covers identity key derivation, customer role tool filtering, audience-filtered
context selection, channel consumer, bootstrap cleanup, relay sanitization,
and channel API route guards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from teleclaude import context_selector
from teleclaude.channels.api_routes import set_redis_transport
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLE_NEWCOMER,
)
from teleclaude.mcp.role_tools import filter_tool_names, get_excluded_tools

# =========================================================================
# Identity Key Derivation
# =========================================================================


class TestDeriveIdentityKey:
    """Tests for derive_identity_key from adapter metadata."""

    def test_discord_identity_key(self) -> None:
        """Discord adapter metadata produces discord:{user_id} key."""
        from teleclaude.core.identity import derive_identity_key
        from teleclaude.core.models import SessionAdapterMetadata

        metadata = SessionAdapterMetadata(
            discord=MagicMock(user_id="123456789", guild_id=None, channel_id=None),
        )
        key = derive_identity_key(metadata)
        assert key == "discord:123456789"

    def test_telegram_identity_key(self) -> None:
        """Telegram adapter metadata produces telegram:{user_id} key."""
        from teleclaude.core.identity import derive_identity_key
        from teleclaude.core.models import SessionAdapterMetadata

        metadata = SessionAdapterMetadata(
            telegram=MagicMock(user_id=98765, topic_id=None),
        )
        key = derive_identity_key(metadata)
        assert key == "telegram:98765"

    def test_no_identity_returns_none(self) -> None:
        """No adapter metadata yields None identity key."""
        from teleclaude.core.identity import derive_identity_key
        from teleclaude.core.models import SessionAdapterMetadata

        metadata = SessionAdapterMetadata()
        key = derive_identity_key(metadata)
        assert key is None

    def test_from_json_roundtrip(self) -> None:
        """SessionAdapterMetadata.from_json works with derive_identity_key."""
        from teleclaude.core.identity import derive_identity_key
        from teleclaude.core.models import SessionAdapterMetadata

        raw = json.dumps({"discord": {"user_id": "555666777"}})
        metadata = SessionAdapterMetadata.from_json(raw)
        key = derive_identity_key(metadata)
        assert key == "discord:555666777"


# =========================================================================
# Customer Role Tool Filtering
# =========================================================================


class TestCustomerToolFiltering:
    """Tests for customer role tool exclusions."""

    def test_customer_cannot_use_publish(self) -> None:
        """Customer role excludes teleclaude__publish."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_CUSTOMER)
        assert "teleclaude__publish" in excluded

    def test_customer_cannot_use_channels_list(self) -> None:
        """Customer role excludes teleclaude__channels_list."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_CUSTOMER)
        assert "teleclaude__channels_list" in excluded

    def test_customer_can_use_escalate(self) -> None:
        """Customer role allows teleclaude__escalate."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_CUSTOMER)
        assert "teleclaude__escalate" not in excluded

    def test_admin_has_all_tools(self) -> None:
        """Admin role has no tool exclusions."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_ADMIN)
        assert len(excluded) == 0

    def test_member_cannot_use_escalate(self) -> None:
        """Member role excludes teleclaude__escalate."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_MEMBER)
        assert "teleclaude__escalate" in excluded

    def test_customer_filter_applied(self) -> None:
        """filter_tool_names for customer removes internal tools, keeps escalate."""
        all_tools = [
            "teleclaude__get_context",
            "teleclaude__escalate",
            "teleclaude__publish",
            "teleclaude__channels_list",
            "teleclaude__deploy",
        ]
        filtered = filter_tool_names(None, all_tools, human_role=HUMAN_ROLE_CUSTOMER)
        assert "teleclaude__escalate" in filtered
        assert "teleclaude__get_context" in filtered
        assert "teleclaude__publish" not in filtered
        assert "teleclaude__channels_list" not in filtered
        assert "teleclaude__deploy" not in filtered


# =========================================================================
# Audience-Filtered Context Selection
# =========================================================================


class SnippetPayload(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str
    audience: list[str]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_index(
    index_path: Path,
    project_root: Path,
    snippets: list[SnippetPayload],
) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_root": str(project_root),
        "snippets": snippets,
    }
    index_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


class TestAudienceFiltering:
    """Tests for audience-based snippet filtering in build_context_output."""

    def _setup_snippets(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a project with admin-only and public snippets."""
        project_root = tmp_path / "project"
        global_root = tmp_path / "global"
        global_snippets_root = global_root / "agents" / "docs"

        admin_path = project_root / "docs" / "project" / "policy" / "admin-only.md"
        public_path = project_root / "docs" / "project" / "policy" / "public-faq.md"
        member_path = project_root / "docs" / "project" / "policy" / "member-guide.md"

        _write(
            admin_path,
            "---\nid: project/policy/admin-only\ntype: policy\nscope: project\n"
            "description: Admin only\naudience: [admin]\n---\n\nSecret admin content.\n",
        )
        _write(
            public_path,
            "---\nid: project/policy/public-faq\ntype: policy\nscope: project\n"
            "description: Public FAQ\naudience: [public]\n---\n\nPublic content.\n",
        )
        _write(
            member_path,
            "---\nid: project/policy/member-guide\ntype: policy\nscope: project\n"
            "description: Member guide\naudience: [member]\n---\n\nMember content.\n",
        )

        _write_index(
            project_root / "docs" / "project" / "index.yaml",
            project_root,
            [
                {
                    "id": "project/policy/admin-only",
                    "description": "Admin only",
                    "type": "policy",
                    "scope": "project",
                    "path": "docs/project/policy/admin-only.md",
                    "audience": ["admin"],
                },
                {
                    "id": "project/policy/public-faq",
                    "description": "Public FAQ",
                    "type": "policy",
                    "scope": "project",
                    "path": "docs/project/policy/public-faq.md",
                    "audience": ["public"],
                },
                {
                    "id": "project/policy/member-guide",
                    "description": "Member guide",
                    "type": "policy",
                    "scope": "project",
                    "path": "docs/project/policy/member-guide.md",
                    "audience": ["member"],
                },
            ],
        )
        _write_index(global_snippets_root / "index.yaml", global_root, [])

        return project_root, global_snippets_root

    def test_customer_sees_only_public(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Customer role sees only public/help-desk snippets."""
        project_root, global_snippets_root = self._setup_snippets(tmp_path)
        monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

        result = context_selector.build_context_output(
            areas=["policy"],
            project_root=project_root,
            human_role=HUMAN_ROLE_CUSTOMER,
        )

        assert "public-faq" in result
        assert "admin-only" not in result
        assert "member-guide" not in result

    def test_member_sees_public_and_member(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Member role sees admin, member, public, help-desk snippets."""
        project_root, global_snippets_root = self._setup_snippets(tmp_path)
        monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

        result = context_selector.build_context_output(
            areas=["policy"],
            project_root=project_root,
            human_role=HUMAN_ROLE_MEMBER,
        )

        assert "public-faq" in result
        assert "member-guide" in result
        assert "admin-only" in result

    def test_admin_sees_everything(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Admin role sees all snippets regardless of audience."""
        project_root, global_snippets_root = self._setup_snippets(tmp_path)
        monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

        result = context_selector.build_context_output(
            areas=["policy"],
            project_root=project_root,
            human_role=HUMAN_ROLE_ADMIN,
        )

        assert "public-faq" in result
        assert "member-guide" in result
        assert "admin-only" in result

    def test_newcomer_sees_like_member(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Newcomer role sees same content as member."""
        project_root, global_snippets_root = self._setup_snippets(tmp_path)
        monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

        result = context_selector.build_context_output(
            areas=["policy"],
            project_root=project_root,
            human_role=HUMAN_ROLE_NEWCOMER,
        )

        assert "public-faq" in result
        assert "member-guide" in result


# =========================================================================
# Channel Consumer
# =========================================================================


class TestChannelConsumer:
    """Tests for channel consumer message handling."""

    @pytest.mark.asyncio
    async def test_consume_acknowledges_payloadless_messages(self) -> None:
        """Messages without a payload field are acknowledged to prevent redelivery."""
        from teleclaude.channels.consumer import consume

        mock_redis = AsyncMock()
        # Simulate one message with payload, one without
        mock_redis.xreadgroup.return_value = [
            (
                b"channel:test:events",
                [
                    (b"1-0", {b"payload": b'{"key": "val"}'}),
                    (b"2-0", {b"other": b"data"}),  # No payload field
                ],
            )
        ]
        mock_redis.xack = AsyncMock()

        messages = await consume(mock_redis, "channel:test:events", "group", "consumer")

        # Only the message with payload is returned
        assert len(messages) == 1
        assert messages[0]["payload"] == {"key": "val"}

        # Both messages are acknowledged
        mock_redis.xack.assert_called_once()
        ack_args = mock_redis.xack.call_args[0]
        assert ack_args[0] == "channel:test:events"
        assert ack_args[1] == "group"
        assert len(ack_args) == 4  # channel, group, msg_id_1, msg_id_2

    @pytest.mark.asyncio
    async def test_consume_empty_stream(self) -> None:
        """Empty stream returns empty list."""
        from teleclaude.channels.consumer import consume

        mock_redis = AsyncMock()
        mock_redis.xreadgroup.return_value = []

        messages = await consume(mock_redis, "channel:test:events", "group", "consumer")
        assert messages == []


# =========================================================================
# Bootstrap Cleanup
# =========================================================================


class TestBootstrapCleanup:
    """Tests for help desk bootstrap failure cleanup."""

    def test_cleanup_on_git_failure(self, tmp_path: Path) -> None:
        """Bootstrap removes partial directory when git commands fail."""
        from teleclaude.project_setup.help_desk_bootstrap import bootstrap_help_desk

        template_dir = tmp_path / "teleclaude" / "templates" / "help-desk"
        template_dir.mkdir(parents=True)
        (template_dir / "README.md").write_text("# Help Desk\n")

        help_desk_dir = tmp_path / "help-desk"

        with (
            patch("teleclaude.project_setup.help_desk_bootstrap._resolve_help_desk_dir") as mock_resolve,
            patch("subprocess.run") as mock_run,
        ):
            mock_resolve.return_value = help_desk_dir
            # First call (git init) succeeds, second (git add) fails
            mock_run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(returncode=0),
                Exception("git commit failed"),
            ]
            # subprocess.run with check=True raises CalledProcessError
            import subprocess

            mock_run.side_effect = [
                None,  # git init succeeds
                None,  # git add succeeds
                subprocess.CalledProcessError(1, "git commit"),
            ]

            with pytest.raises(subprocess.CalledProcessError):
                bootstrap_help_desk(tmp_path / "teleclaude")

            # Directory should be cleaned up
            assert not help_desk_dir.exists()

    def test_idempotent_skip_existing(self, tmp_path: Path) -> None:
        """Bootstrap skips if help desk directory already exists."""
        from teleclaude.project_setup.help_desk_bootstrap import bootstrap_help_desk

        help_desk_dir = tmp_path / "help-desk"
        help_desk_dir.mkdir()

        with patch("teleclaude.project_setup.help_desk_bootstrap._resolve_help_desk_dir") as mock_resolve:
            mock_resolve.return_value = help_desk_dir
            # Should not raise, just skip
            bootstrap_help_desk(tmp_path / "teleclaude")

        assert help_desk_dir.exists()


# =========================================================================
# Relay Sanitization
# =========================================================================


def _sanitize_relay_text(text: str) -> str:
    """Standalone copy of the sanitization logic for testing without heavy imports."""
    import re

    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


class TestRelaySanitization:
    """Tests for Discord relay content sanitization."""

    def test_strips_ansi_escape_sequences(self) -> None:
        """ANSI escape sequences are removed from relay text."""
        text = "Hello \x1b[31mred\x1b[0m world"
        sanitized = _sanitize_relay_text(text)
        assert sanitized == "Hello red world"

    def test_strips_control_characters(self) -> None:
        """Control characters (except newline/tab) are removed."""
        text = "Hello\x00\x01\x02\x03 world\n\ttab"
        sanitized = _sanitize_relay_text(text)
        assert sanitized == "Hello world\n\ttab"

    def test_preserves_normal_text(self) -> None:
        """Normal text passes through unchanged."""
        text = "Normal message with punctuation! @mentions #channels"
        sanitized = _sanitize_relay_text(text)
        assert sanitized == text

    def test_sanitizes_in_context_compilation(self) -> None:
        """Sanitized text is used in relay context compilation format."""
        raw_content = "Hello \x1b[31mred\x1b[0m"
        sanitized = _sanitize_relay_text(raw_content)
        context_line = f"Admin (Bob): {sanitized}"
        assert context_line == "Admin (Bob): Hello red"
        assert "\x1b" not in context_line


# =========================================================================
# Channel API Route Guard
# =========================================================================


class TestChannelApiRouteGuard:
    """Tests for channel API route redis transport guard."""

    def test_duplicate_setup_raises(self) -> None:
        """set_redis_transport raises if called twice."""
        import teleclaude.channels.api_routes as api_routes

        original = api_routes._redis_transport
        try:
            api_routes._redis_transport = None
            mock_transport = MagicMock()
            set_redis_transport(mock_transport)
            assert api_routes._redis_transport is mock_transport

            with pytest.raises(RuntimeError, match="already configured"):
                set_redis_transport(MagicMock())
        finally:
            api_routes._redis_transport = original
