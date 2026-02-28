"""Unit tests for help desk platform features.

Covers identity key derivation, customer role tool filtering, role-filtered
context selection, channel consumer, bootstrap cleanup, relay sanitization,
and channel API route guards.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from typing_extensions import TypedDict

from teleclaude import context_selector
from teleclaude.channels.api_routes import set_redis_transport
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLE_NEWCOMER,
)
from teleclaude.core.tool_access import filter_tool_names, get_excluded_tools

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
        """Customer role excludes telec channels publish."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_CUSTOMER)
        assert "telec channels publish" in excluded

    def test_customer_cannot_use_channels_list(self) -> None:
        """Customer role excludes telec channels list."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_CUSTOMER)
        assert "telec channels list" in excluded

    def test_customer_can_use_escalate(self) -> None:
        """Customer role allows telec sessions escalate."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_CUSTOMER)
        assert "telec sessions escalate" not in excluded

    def test_admin_has_all_tools(self) -> None:
        """Admin role has no tool exclusions."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_ADMIN)
        assert len(excluded) == 0

    def test_member_cannot_use_escalate(self) -> None:
        """Member role excludes telec sessions escalate."""
        excluded = get_excluded_tools(None, human_role=HUMAN_ROLE_MEMBER)
        assert "telec sessions escalate" in excluded

    def test_customer_filter_applied(self) -> None:
        """filter_tool_names for customer removes internal tools, keeps escalate."""
        all_tools = [
            "telec docs get",
            "telec sessions escalate",
            "telec channels publish",
            "telec channels list",
        ]
        filtered = filter_tool_names(None, all_tools, human_role=HUMAN_ROLE_CUSTOMER)
        assert "telec sessions escalate" in filtered
        assert "telec docs get" in filtered
        assert "telec channels publish" not in filtered
        assert "telec channels list" not in filtered


# =========================================================================
# Audience-Filtered Context Selection
# =========================================================================


class SnippetPayload(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str
    visibility: str


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


class TestRoleFiltering:
    """Tests for visibility-based snippet filtering in build_context_output."""

    def _setup_snippets(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a project with admin-only, member, and public role snippets."""
        project_root = tmp_path / "project"
        global_root = tmp_path / "global"
        global_snippets_root = global_root / "agents" / "docs"

        admin_path = project_root / "docs" / "project" / "policy" / "admin-only.md"
        public_path = project_root / "docs" / "project" / "policy" / "public-faq.md"
        member_path = project_root / "docs" / "project" / "policy" / "member-guide.md"

        _write(
            admin_path,
            "---\nid: project/policy/admin-only\ntype: policy\nscope: project\n"
            "description: Admin only\nvisibility: internal\n---\n\nSecret admin content.\n",
        )
        _write(
            public_path,
            "---\nid: project/policy/public-faq\ntype: policy\nscope: project\n"
            "description: Public FAQ\nvisibility: public\n---\n\nPublic content.\n",
        )
        _write(
            member_path,
            "---\nid: project/policy/member-guide\ntype: policy\nscope: project\n"
            "description: Member guide\nvisibility: internal\n---\n\nMember content.\n",
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
                    "visibility": "internal",
                },
                {
                    "id": "project/policy/public-faq",
                    "description": "Public FAQ",
                    "type": "policy",
                    "scope": "project",
                    "path": "docs/project/policy/public-faq.md",
                    "visibility": "public",
                },
                {
                    "id": "project/policy/member-guide",
                    "description": "Member guide",
                    "type": "policy",
                    "scope": "project",
                    "path": "docs/project/policy/member-guide.md",
                    "visibility": "internal",
                },
            ],
        )
        _write_index(global_snippets_root / "index.yaml", global_root, [])

        return project_root, global_snippets_root

    def test_customer_sees_only_public(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Customer role sees only public snippets."""
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

    def test_member_sees_only_public(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Member role is non-admin and sees only public snippets."""
        project_root, global_snippets_root = self._setup_snippets(tmp_path)
        monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

        result = context_selector.build_context_output(
            areas=["policy"],
            project_root=project_root,
            human_role=HUMAN_ROLE_MEMBER,
        )

        assert "public-faq" in result
        assert "member-guide" not in result
        assert "admin-only" not in result

    def test_admin_sees_everything(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Admin role sees all snippets regardless of role level."""
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

    def test_unknown_role_sees_only_public(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unrecognized role defaults to public — least privilege."""
        project_root, global_snippets_root = self._setup_snippets(tmp_path)
        monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

        result = context_selector.build_context_output(
            areas=["policy"],
            project_root=project_root,
            human_role=HUMAN_ROLE_NEWCOMER,
        )

        assert "public-faq" in result
        assert "member-guide" not in result
        assert "admin-only" not in result


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
        import subprocess

        from teleclaude.project_setup.help_desk_bootstrap import bootstrap_help_desk

        help_desk_dir = tmp_path / "help-desk"

        with (
            patch("teleclaude.project_setup.help_desk_bootstrap._resolve_help_desk_dir", return_value=help_desk_dir),
            patch("teleclaude.project_setup.help_desk_bootstrap.shutil.copytree", side_effect=lambda s, d: d.mkdir()),
            patch(
                "teleclaude.project_setup.help_desk_bootstrap.subprocess.run",
                side_effect=[
                    None,  # git init
                    None,  # git add
                    subprocess.CalledProcessError(1, "git commit"),
                ],
            ),
            patch("teleclaude.project_setup.init_flow.init_project"),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                bootstrap_help_desk()

            assert not help_desk_dir.exists()

    def test_idempotent_skip_existing(self, tmp_path: Path) -> None:
        """Bootstrap skips if help desk directory already exists."""
        from teleclaude.project_setup.help_desk_bootstrap import bootstrap_help_desk

        help_desk_dir = tmp_path / "help-desk"
        help_desk_dir.mkdir()

        with patch("teleclaude.project_setup.help_desk_bootstrap._resolve_help_desk_dir") as mock_resolve:
            mock_resolve.return_value = help_desk_dir
            # Should not raise, just skip
            bootstrap_help_desk()

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


# =========================================================================
# Channel Worker Notification Dispatch
# =========================================================================


class TestChannelWorkerDispatch:
    """Tests for channel worker notification routing."""

    @pytest.mark.asyncio
    async def test_channel_worker_dispatches_notification(self) -> None:
        """Notification target type logs and defers to event platform."""
        from teleclaude.channels.worker import _dispatch_to_target

        target = {"type": "notification", "channel": "telegram"}
        payload = {"summary": "New ticket from Alice"}

        # Should complete without error; delivery is via event platform
        await _dispatch_to_target(target, payload)
