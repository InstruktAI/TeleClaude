"""Functional coverage for per-person output visibility projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from teleclaude.api.sessions_actions_routes import _project_session_messages
from teleclaude.api.streaming import _load_live_transcript_events
from teleclaude.config.loader import load_person_config, resolve_person_output_visibility_settings
from teleclaude.config.schema import (
    OUTPUT_VISIBILITY_BOTH,
    OUTPUT_VISIBILITY_MOBILE,
    OUTPUT_VISIBILITY_OFF,
    OUTPUT_VISIBILITY_WEB,
    OutputVisibilitySettings,
    PersonConfig,
    PersonEntry,
)
from teleclaude.constants import CHECKPOINT_MESSAGE, HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, format_system_message
from teleclaude.core.conversation_messages import (
    TeleClaudeNotificationLabel,
    format_identity_header,
    format_peer_header,
)
from teleclaude.core.models import JsonDict, Session
from teleclaude.core.polling_coordinator import _build_transcript_output_update
from teleclaude.output_projection.conversation_projector import project_entries
from teleclaude.output_projection.models import (
    ProjectedBlock,
    ProjectionSurface,
    VisibilityPolicy,
    visibility_policy_for_recipient,
)
from teleclaude.output_projection.visibility import ProjectedTextCategory, classify_projected_text
from teleclaude.utils.transcript import TranscriptTailCursor

pytestmark = pytest.mark.functional


def _user_entry(content: str) -> JsonDict:
    return {"message": {"role": "user", "content": content}}


def _projected_blocks(entries: list[JsonDict], policy: VisibilityPolicy) -> list[ProjectedBlock]:
    return list(project_entries(entries, policy))


def _write_claude_transcript(path: Path, entries: list[JsonDict]) -> None:
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")


def _person_entry(*, name: str, email: str, role: str, username: str | None = None) -> PersonEntry:
    return PersonEntry(name=name, email=email, role=role, username=username)


def _tool_use_entry() -> JsonDict:
    return {
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Bash",
                    "input": {},
                }
            ],
        }
    }


def _timestamped_user_entry() -> JsonDict:
    return {
        "timestamp": "2026-01-01T00:00:01+00:00",
        "message": {"role": "user", "content": "Start"},
    }


def _timestamped_tool_use_entry() -> JsonDict:
    return {
        "timestamp": "2026-01-01T00:00:02+00:00",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Bash",
                    "input": {},
                }
            ],
        },
    }


def _tool_result_entry() -> JsonDict:
    return {
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "result body",
                }
            ],
        }
    }


def test_person_config_accepts_output_visibility_settings_from_person_overlay(tmp_path: Path) -> None:
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "\n".join(
            [
                "settings:",
                "  output_visibility:",
                "    notifications: mobile",
                "    system_messages: web",
                "    tool_calls: off",
                "",
            ]
        ),
        encoding="utf-8",
    )

    person_config = load_person_config(config_path)

    assert person_config.settings.output_visibility.notifications == OUTPUT_VISIBILITY_MOBILE
    assert person_config.settings.output_visibility.system_messages == OUTPUT_VISIBILITY_WEB
    assert person_config.settings.output_visibility.tool_calls == OUTPUT_VISIBILITY_OFF


def test_person_config_output_visibility_defaults_to_role_based_policy() -> None:
    person_config = PersonConfig.model_validate({})

    assert person_config.settings.output_visibility.notifications is None
    assert person_config.settings.output_visibility.system_messages is None
    assert person_config.settings.output_visibility.tool_calls is None


def test_person_config_rejects_invalid_output_visibility_values(tmp_path: Path) -> None:
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        "\n".join(
            [
                "settings:",
                "  output_visibility:",
                "    tool_calls: terminal",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_person_config(config_path)


def test_output_visibility_resolver_returns_defaults_when_person_overlay_is_missing(tmp_path: Path) -> None:
    people = [
        _person_entry(name="Admin Human", email="admin@example.test", role=HUMAN_ROLE_ADMIN),
        _person_entry(name="Member Human", email="member@example.test", role=HUMAN_ROLE_MEMBER),
    ]

    admin_settings = resolve_person_output_visibility_settings(
        person_email="admin@example.test",
        people=people,
        people_dir=tmp_path,
    )
    member_settings = resolve_person_output_visibility_settings(
        person_email="member@example.test",
        people=people,
        people_dir=tmp_path,
    )

    assert admin_settings is None
    assert member_settings is None


def test_output_visibility_resolver_loads_matched_person_overlay(tmp_path: Path) -> None:
    person_dir = tmp_path / "morriz"
    person_dir.mkdir()
    (person_dir / "teleclaude.yml").write_text(
        "\n".join(
            [
                "settings:",
                "  output_visibility:",
                "    notifications: web",
                "",
            ]
        ),
        encoding="utf-8",
    )
    people = [
        _person_entry(
            name="Mor Riz",
            email="morriz@example.test",
            role=HUMAN_ROLE_ADMIN,
            username="morriz",
        )
    ]

    settings = resolve_person_output_visibility_settings(
        person_email="morriz@example.test",
        people=people,
        people_dir=tmp_path,
    )

    assert settings is not None
    assert settings.notifications == OUTPUT_VISIBILITY_WEB


def test_admin_output_visibility_defaults_include_system_messages_and_tool_calls() -> None:
    mobile_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.MOBILE,
    )
    web_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.WEB,
    )

    assert mobile_policy.include_tools
    assert mobile_policy.include_system_messages
    assert not mobile_policy.include_notifications
    assert not mobile_policy.include_tool_results
    assert web_policy.include_tools
    assert web_policy.include_system_messages
    assert not web_policy.include_notifications
    assert not web_policy.include_tool_results


def test_member_output_visibility_defaults_hide_configurable_categories() -> None:
    policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.WEB,
    )

    assert not policy.include_tools
    assert not policy.include_system_messages
    assert not policy.include_notifications
    assert not policy.include_tool_results


def test_output_visibility_settings_override_role_defaults_by_surface() -> None:
    settings = OutputVisibilitySettings(
        notifications=OUTPUT_VISIBILITY_MOBILE,
        system_messages=OUTPUT_VISIBILITY_WEB,
        tool_calls=OUTPUT_VISIBILITY_BOTH,
    )

    mobile_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.MOBILE,
        settings=settings,
    )
    web_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.WEB,
        settings=settings,
    )

    assert mobile_policy.include_notifications
    assert not mobile_policy.include_system_messages
    assert mobile_policy.include_tools
    assert not mobile_policy.include_tool_results
    assert not web_policy.include_notifications
    assert web_policy.include_system_messages
    assert web_policy.include_tools
    assert not web_policy.include_tool_results


def test_output_visibility_off_overrides_admin_defaults_on_every_surface() -> None:
    settings = OutputVisibilitySettings(
        notifications=OUTPUT_VISIBILITY_OFF,
        system_messages=OUTPUT_VISIBILITY_OFF,
        tool_calls=OUTPUT_VISIBILITY_OFF,
    )

    mobile_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.MOBILE,
        settings=settings,
    )
    web_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.WEB,
        settings=settings,
    )

    assert not mobile_policy.include_notifications
    assert not mobile_policy.include_system_messages
    assert not mobile_policy.include_tools
    assert not mobile_policy.include_tool_results
    assert not web_policy.include_notifications
    assert not web_policy.include_system_messages
    assert not web_policy.include_tools
    assert not web_policy.include_tool_results


def test_projected_text_classifier_distinguishes_teleclaude_marker_families() -> None:
    peer_text = format_peer_header(sender_session_id="session-a", sender_computer="local")
    notification_text = format_system_message(
        TeleClaudeNotificationLabel.NOTIFICATION,
        "build completed",
    )
    input_request_text = format_system_message(
        TeleClaudeNotificationLabel.INPUT_REQUEST,
        "choose a path",
    )

    assert classify_projected_text(peer_text) is ProjectedTextCategory.PEER_CROSS_SHARE
    assert classify_projected_text(notification_text) is ProjectedTextCategory.NOTIFICATION
    assert classify_projected_text(input_request_text) is ProjectedTextCategory.NOTIFICATION
    assert classify_projected_text(CHECKPOINT_MESSAGE) is ProjectedTextCategory.SIDE_CHANNEL


def test_projected_text_classifier_identifies_machine_role_headers() -> None:
    orchestrator_text = format_identity_header(role="Orchestrator", session_id="session-a", computer="local")
    integrator_text = format_identity_header(role="Integrator", session_id="session-a", computer="local")
    system_text = format_identity_header(role="System", session_id="session-a", computer="local")

    assert classify_projected_text(orchestrator_text) is ProjectedTextCategory.SYSTEM_MESSAGE
    assert classify_projected_text(integrator_text) is ProjectedTextCategory.SYSTEM_MESSAGE
    assert classify_projected_text(system_text) is ProjectedTextCategory.SYSTEM_MESSAGE


def test_projector_hides_notifications_by_default_for_admin_and_member() -> None:
    entries = [
        _user_entry(
            format_system_message(
                TeleClaudeNotificationLabel.NOTIFICATION,
                "build completed",
            )
        )
    ]
    admin_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.WEB,
    )
    member_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.WEB,
    )

    assert not _projected_blocks(entries, admin_policy)
    assert not _projected_blocks(entries, member_policy)


def test_projector_applies_system_message_policy_by_role() -> None:
    entries = [_user_entry(format_identity_header(role="Orchestrator", session_id="session-a", computer="local"))]
    admin_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.MOBILE,
    )
    member_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.MOBILE,
    )

    assert len(_projected_blocks(entries, admin_policy)) == 1
    assert not _projected_blocks(entries, member_policy)


def test_projector_preserves_peer_cross_share_and_drops_checkpoint_artifacts() -> None:
    entries = [
        _user_entry(format_peer_header(sender_session_id="session-a", sender_computer="local")),
        _user_entry(CHECKPOINT_MESSAGE),
    ]
    member_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.WEB,
    )

    projected = _projected_blocks(entries, member_policy)

    assert len(projected) == 1


def test_tool_results_are_hidden_even_when_tool_calls_are_enabled() -> None:
    settings = OutputVisibilitySettings(tool_calls=OUTPUT_VISIBILITY_BOTH)
    policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.WEB,
        settings=settings,
    )

    assert policy.include_tools
    assert not policy.include_tool_results
    assert not _projected_blocks([_tool_result_entry()], policy)


def test_agent_cli_side_channel_artifacts_are_dropped_from_projected_output() -> None:
    policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.WEB,
    )

    assert not _projected_blocks([_user_entry("Stop hook feedback: internal detail")], policy)
    assert not _projected_blocks([_user_entry("<system-reminder>internal detail</system-reminder>")], policy)


def test_history_api_projection_uses_recipient_policy(tmp_path: Path) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    _write_claude_transcript(
        transcript_path,
        [
            _user_entry(format_identity_header(role="Orchestrator", session_id="session-a", computer="local")),
            _user_entry(
                format_system_message(
                    TeleClaudeNotificationLabel.NOTIFICATION,
                    "build completed",
                )
            ),
            _tool_use_entry(),
        ],
    )

    admin_messages = _project_session_messages(
        [str(transcript_path)],
        active_agent="claude",
        recipient_email="admin@example.test",
        recipient_role=HUMAN_ROLE_ADMIN,
        include_tools=None,
        include_thinking=False,
        since=None,
    )
    admin_without_tools = _project_session_messages(
        [str(transcript_path)],
        active_agent="claude",
        recipient_email="admin@example.test",
        recipient_role=HUMAN_ROLE_ADMIN,
        include_tools=False,
        include_thinking=False,
        since=None,
    )
    member_messages = _project_session_messages(
        [str(transcript_path)],
        active_agent="claude",
        recipient_email="member@example.test",
        recipient_role=HUMAN_ROLE_MEMBER,
        include_tools=True,
        include_thinking=False,
        since=None,
    )

    assert len(admin_messages) == 2
    assert len(admin_without_tools) == 1
    assert not member_messages


@pytest.mark.asyncio
async def test_web_live_projection_uses_recipient_policy(tmp_path: Path) -> None:
    transcript_path = tmp_path / "live.jsonl"
    _write_claude_transcript(
        transcript_path,
        [_user_entry(format_identity_header(role="Orchestrator", session_id="session-a", computer="local"))],
    )
    admin_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_ADMIN,
        surface=ProjectionSurface.WEB,
    )
    member_policy = visibility_policy_for_recipient(
        human_role=HUMAN_ROLE_MEMBER,
        surface=ProjectionSurface.WEB,
    )

    _admin_cursor, admin_events = await _load_live_transcript_events(
        str(transcript_path),
        cursor=TranscriptTailCursor(),
        session_id="session-a",
        policy=admin_policy,
    )
    _member_cursor, member_events = await _load_live_transcript_events(
        str(transcript_path),
        cursor=TranscriptTailCursor(),
        session_id="session-a",
        policy=member_policy,
    )

    assert admin_events
    assert not member_events


def test_mobile_transcript_output_uses_session_recipient_policy(tmp_path: Path) -> None:
    transcript_path = tmp_path / "mobile-output.jsonl"
    _write_claude_transcript(
        transcript_path,
        [
            _timestamped_user_entry(),
            _timestamped_tool_use_entry(),
        ],
    )
    admin_session = Session(
        session_id="admin-session",
        computer_name="local",
        title="Admin Session",
        tmux_session_name="tmux-admin",
        native_log_file=str(transcript_path),
        active_agent="claude",
        human_email="admin@example.test",
        human_role=HUMAN_ROLE_ADMIN,
    )
    member_session = Session(
        session_id="member-session",
        computer_name="local",
        title="Member Session",
        tmux_session_name="tmux-member",
        native_log_file=str(transcript_path),
        active_agent="claude",
        human_email="member@example.test",
        human_role=HUMAN_ROLE_MEMBER,
    )

    assert _build_transcript_output_update(admin_session) is not None
    assert _build_transcript_output_update(member_session) is None
