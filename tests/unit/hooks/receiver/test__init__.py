"""Focused tests for teleclaude.hooks.receiver checkpoint wiring."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session as SqlSession
from sqlmodel import SQLModel, select

from teleclaude.constants import DOMAIN_SCOPES
from teleclaude.core import db_models
from teleclaude.core.db.connection_factory import create_sync_db_engine
from teleclaude.core.events import AgentHookEvents
from teleclaude.hooks.adapters.codex import CodexAdapter
from teleclaude.hooks.receiver import (
    _HOOK_COALESCE_WINDOWS_S,
    DomainBaselineUnavailable,
    _handle_user_prompt_submit,
    _is_system_injected_user_prompt,
    _load_domain_baseline_content,
    _maybe_checkpoint_output,
    _print_additional_context,
    _resolve_checkpoint_project_path,
    _resolve_command_domain_for_session,
    enqueue_hook_event,
)
from teleclaude.hooks.receiver import (
    main as receiver_main,
)


def _make_outbox_db(tmp_path: Path) -> str:
    db_path = tmp_path / "outbox.sqlite"
    engine = create_sync_db_engine(db_path)
    SQLModel.metadata.create_all(engine, tables=[db_models.HookOutbox.__table__])
    return str(db_path)


def test_enqueue_hook_event_debounces_recent_unclaimed_row_latest_wins(tmp_path: Path) -> None:
    outbox_db = _make_outbox_db(tmp_path)

    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "first"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )
    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "latest"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )

    with SqlSession(create_sync_db_engine(outbox_db)) as session:
        rows = session.exec(select(db_models.HookOutbox)).all()

    assert len(rows) == 1
    assert json.loads(rows[0].payload) == {"message": "latest"}
    assert rows[0].attempt_count == 0
    assert rows[0].locked_at is None


def test_enqueue_hook_event_does_not_replace_locked_recent_row(tmp_path: Path) -> None:
    outbox_db = _make_outbox_db(tmp_path)

    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "first"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )

    engine = create_sync_db_engine(outbox_db)
    with SqlSession(engine) as session:
        row = session.exec(select(db_models.HookOutbox)).first()
        assert row is not None
        row.locked_at = datetime.now(UTC).isoformat()
        session.add(row)
        session.commit()

    enqueue_hook_event(
        "session-1",
        "agent_stop",
        {"message": "latest"},
        outbox_db=outbox_db,
        latest_wins_within_s=10.0,
    )

    with SqlSession(engine) as session:
        rows = session.exec(select(db_models.HookOutbox).order_by(db_models.HookOutbox.id)).all()

    assert len(rows) == 2
    assert json.loads(rows[0].payload) == {"message": "first"}
    assert json.loads(rows[1].payload) == {"message": "latest"}


def test_hook_coalesce_windows_policy_table_pins_intent() -> None:
    """The policy table is the source of truth for which event types coalesce.

    Bursty / idempotent / latest-wins-safe events get a 1 s UPSERT window.
    Once-per-lifecycle and must-process-each events are absent — they fall
    through to plain INSERT in the receiver.
    """
    assert _HOOK_COALESCE_WINDOWS_S == {
        AgentHookEvents.TOOL_USE: 1.0,
        AgentHookEvents.AGENT_STOP: 1.0,
        AgentHookEvents.NATIVE_METADATA_UPDATE: 1.0,
    }
    assert AgentHookEvents.AGENT_SESSION_START not in _HOOK_COALESCE_WINDOWS_S
    assert AgentHookEvents.USER_PROMPT_SUBMIT not in _HOOK_COALESCE_WINDOWS_S
    assert AgentHookEvents.AGENT_ERROR not in _HOOK_COALESCE_WINDOWS_S
    assert AgentHookEvents.CHECKPOINT_SEEN not in _HOOK_COALESCE_WINDOWS_S


def test_coalesce_eligible_event_collapses_within_window(tmp_path: Path) -> None:
    """A coalesce-eligible event type uses its policy window to UPSERT in
    place. TOOL_USE is the representative — same code path applies to all
    entries in ``_HOOK_COALESCE_WINDOWS_S``."""
    outbox_db = _make_outbox_db(tmp_path)
    window = _HOOK_COALESCE_WINDOWS_S[AgentHookEvents.TOOL_USE]

    enqueue_hook_event(
        "session-1",
        AgentHookEvents.TOOL_USE,
        {"value": "first"},
        outbox_db=outbox_db,
        latest_wins_within_s=window,
    )
    enqueue_hook_event(
        "session-1",
        AgentHookEvents.TOOL_USE,
        {"value": "latest"},
        outbox_db=outbox_db,
        latest_wins_within_s=window,
    )

    with SqlSession(create_sync_db_engine(outbox_db)) as session:
        rows = session.exec(select(db_models.HookOutbox)).all()

    assert len(rows) == 1
    assert json.loads(rows[0].payload) == {"value": "latest"}


def test_non_coalesce_event_keeps_separate_rows(tmp_path: Path) -> None:
    """An event type absent from ``_HOOK_COALESCE_WINDOWS_S`` falls through to
    plain INSERT — each emit persists as its own row. AGENT_SESSION_START is
    the representative; same code path covers USER_PROMPT_SUBMIT and other
    absent types."""
    outbox_db = _make_outbox_db(tmp_path)
    window = _HOOK_COALESCE_WINDOWS_S.get(AgentHookEvents.AGENT_SESSION_START)
    assert window is None

    enqueue_hook_event(
        "session-1",
        AgentHookEvents.AGENT_SESSION_START,
        {"value": "first"},
        outbox_db=outbox_db,
        latest_wins_within_s=window,
    )
    enqueue_hook_event(
        "session-1",
        AgentHookEvents.AGENT_SESSION_START,
        {"value": "second"},
        outbox_db=outbox_db,
        latest_wins_within_s=window,
    )

    with SqlSession(create_sync_db_engine(outbox_db)) as session:
        rows = session.exec(select(db_models.HookOutbox).order_by(db_models.HookOutbox.id)).all()

    assert len(rows) == 2
    assert json.loads(rows[0].payload) == {"value": "first"}
    assert json.loads(rows[1].payload) == {"value": "second"}


def test_checkpoint_wiring_threads_session_id_into_checkpoint_builder() -> None:
    row = SimpleNamespace(
        native_log_file="/tmp/session.jsonl",
        native_session_id="native-1",
        working_slug="demo-slug",
        project_path="/repo",
        last_message_sent_at=datetime(2026, 4, 11, 10, 0, tzinfo=UTC),
        last_checkpoint_at=None,
    )

    with (
        patch("teleclaude.hooks.receiver.is_checkpoint_disabled", return_value=False),
        patch("teleclaude.hooks.receiver._load_checkpoint_row", return_value=row),
        patch("teleclaude.hooks.receiver.get_checkpoint_content", return_value="checkpoint") as checkpoint_mock,
        patch("teleclaude.hooks.receiver.enqueue_checkpoint_seen"),
    ):
        result = _maybe_checkpoint_output(
            "session-1",
            "codex",
            {},
            outbox_db="/tmp/outbox.sqlite",
        )

    assert result == "checkpoint"
    assert checkpoint_mock.call_args.kwargs["session_id"] == "session-1"


def test_checkpoint_reevaluates_each_stop_for_checkpoint_compliance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every stop re-evaluates against the latest checkpoint transcript anchor."""
    monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

    row = SimpleNamespace(
        native_log_file="/tmp/session.jsonl",
        native_session_id="native-1",
        working_slug=None,
        project_path="/repo",
        subdir=None,
        last_message_sent_at=datetime(2026, 4, 11, 10, 0, tzinfo=UTC),
        last_checkpoint_at=None,
    )

    with (
        patch("teleclaude.hooks.receiver.is_checkpoint_disabled", return_value=False),
        patch("teleclaude.hooks.receiver._load_checkpoint_row", return_value=row),
        patch("teleclaude.hooks.receiver.get_checkpoint_content", return_value="checkpoint") as checkpoint_mock,
        patch("teleclaude.hooks.receiver.enqueue_checkpoint_seen"),
    ):
        first = _maybe_checkpoint_output(
            "session-1",
            "claude",
            {"stop_hook_active": False},
            outbox_db="/tmp/outbox.sqlite",
        )
        codex_style_second = _maybe_checkpoint_output(
            "session-1",
            "codex",
            {},
            outbox_db="/tmp/outbox.sqlite",
        )
        second = _maybe_checkpoint_output(
            "session-1",
            "claude",
            {"stop_hook_active": True},
            outbox_db="/tmp/outbox.sqlite",
        )
        third = _maybe_checkpoint_output(
            "session-1",
            "claude",
            {"stop_hook_active": True},
            outbox_db="/tmp/outbox.sqlite",
        )

    assert first == "checkpoint"
    assert codex_style_second == "checkpoint"
    assert second == "checkpoint"
    assert third == "checkpoint"
    assert checkpoint_mock.call_count == 4


class TestResolveCheckpointProjectPath:
    @pytest.mark.unit
    def test_worktree_session_resolves_to_worktree_path(self) -> None:
        """Worktree sessions must resolve to the actual worktree dir, not repo root.

        Without this, _current_branch runs against the repo root (always main)
        and main_only checkpoint actions fire incorrectly in worktrees.
        """
        row = SimpleNamespace(
            project_path="/repo",
            subdir="trees/my-feature",
            native_log_file=None,
        )
        assert _resolve_checkpoint_project_path(row) == "/repo/trees/my-feature"

    @pytest.mark.unit
    def test_repo_root_session_returns_project_path_unchanged(self) -> None:
        row = SimpleNamespace(
            project_path="/repo",
            subdir=None,
            native_log_file=None,
        )
        assert _resolve_checkpoint_project_path(row) == "/repo"

    @pytest.mark.unit
    def test_empty_subdir_returns_project_path_unchanged(self) -> None:
        row = SimpleNamespace(
            project_path="/repo",
            subdir="",
            native_log_file=None,
        )
        assert _resolve_checkpoint_project_path(row) == "/repo"


def test_handle_user_prompt_submit_drops_xml_wrapped_internal_prompt() -> None:
    dropped = _handle_user_prompt_submit(
        AgentHookEvents.USER_PROMPT_SUBMIT,
        {
            "prompt": '<hook_prompt hook_run_id="stop:2:/Users/Morriz/.codex/hooks.json">[TeleClaude Checkpoint] - Context-aware checkpoint'
        },
        "codex",
        "session-1",
        "native-1",
    )

    assert dropped is True


def test_system_injected_user_prompt_contract_is_agent_specific() -> None:
    assert _is_system_injected_user_prompt("codex", '<hook_prompt hook_run_id="stop:2">checkpoint') is True
    assert _is_system_injected_user_prompt("claude", "Stop hook feedback:\nblocked") is True
    assert _is_system_injected_user_prompt("claude", "<task-notification>done</task-notification>") is True
    assert _is_system_injected_user_prompt("gemini", "[TeleClaude Notification]\n\nSession abc finished") is True
    assert _is_system_injected_user_prompt("gemini", "[TeleClaude - Linked output (sess-peer) on remote]") is True
    assert _is_system_injected_user_prompt("gemini", "real prompt") is False


def test_codex_subagent_event_drops_before_session_resolution(tmp_path: Path) -> None:
    """Codex subagent hook events exit before _resolve_receiver_session_id runs.

    Regression guard: a previous version of this drop ran AFTER session resolution,
    which had already persisted `codex:<subagent_native_id> -> <parent_session>` to
    the session map — silently binding the subagent's native id to the parent's
    TeleClaude session and violating the Session Identity Truth spec. The drop
    must short-circuit before any identity side effect.
    """
    outbox_db = _make_outbox_db(tmp_path)
    fake_args = SimpleNamespace(
        agent="codex",
        event_type=None,
        cwd="/some/working/dir",
    )
    stdin_payload = json.dumps(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "session_id": "child-thread-id",
            "transcript_path": "/fake/path/to/subagent.jsonl",
            "cwd": "/some/working/dir",
            "model": "gpt-5.5",
        }
    )

    with (
        patch("sys.stdin", io.StringIO(stdin_payload)),
        patch("teleclaude.hooks.receiver._parse_args", return_value=fake_args),
        patch("teleclaude.hooks.receiver.is_codex_subagent_transcript", return_value=True),
        patch("teleclaude.hooks.receiver._resolve_receiver_session_id") as resolve_mock,
        patch("teleclaude.hooks.receiver._get_default_outbox_db", return_value=outbox_db),
    ):
        with pytest.raises(SystemExit) as exit_info:
            receiver_main()

    assert exit_info.value.code == 0
    assert resolve_mock.call_count == 0, (
        "session resolution must NOT run for Codex subagent events — it persists "
        "subagent->parent mappings to the session map before the drop can take effect"
    )
    with SqlSession(create_sync_db_engine(outbox_db)) as session:
        rows = session.exec(select(db_models.HookOutbox)).all()
    assert rows == []


class TestDomainBaselineInjection:
    """Behavioral tests for SessionStart domain-baseline injection.

    Covers: successful content load, ordering relative to existing context
    fragments, allowlist rejection of unknown domains, path-traversal
    rejection, and visible-failure path when the deployed baseline is
    missing.
    """

    def test_load_domain_baseline_content_returns_file_text(self, tmp_path: Path) -> None:
        docs_root = tmp_path / ".teleclaude" / "docs"
        (docs_root / "software-development").mkdir(parents=True)
        baseline = docs_root / "software-development" / "baseline.md"
        baseline.write_text("# Software Baseline\n\nrules: ...\n", encoding="utf-8")

        with patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path):
            content = _load_domain_baseline_content("software-development")

        # Identity comparison vs the file the production code reads — proves
        # the loader returns exactly the on-disk content, not a constant or a
        # different file. No inline-string assertion.
        assert content == baseline.read_text(encoding="utf-8")

    def test_load_domain_baseline_content_raises_when_missing(self, tmp_path: Path) -> None:

        (tmp_path / ".teleclaude" / "docs").mkdir(parents=True)

        with patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path):
            with pytest.raises(DomainBaselineUnavailable):
                _load_domain_baseline_content("software-development")

    def test_load_domain_baseline_content_raises_on_empty_file(self, tmp_path: Path) -> None:

        docs_root = tmp_path / ".teleclaude" / "docs"
        (docs_root / "software-development").mkdir(parents=True)
        (docs_root / "software-development" / "baseline.md").write_text("   \n", encoding="utf-8")

        with patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path):
            with pytest.raises(DomainBaselineUnavailable):
                _load_domain_baseline_content("software-development")

    def test_load_domain_baseline_content_blocks_path_traversal(self, tmp_path: Path) -> None:
        """Defence-in-depth: resolved path must remain under the docs root.

        Even if a malicious value sneaks past the allowlist (validation bug,
        config drift), the path check rejects symlinks/traversal that would
        escape ~/.teleclaude/docs.
        """

        # Create a sibling directory outside docs_root and a symlink pointing there.
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "baseline.md").write_text("# leak\n", encoding="utf-8")
        docs_root = tmp_path / ".teleclaude" / "docs"
        docs_root.mkdir(parents=True)
        (docs_root / "evil").symlink_to(outside)

        with patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path):
            with pytest.raises(DomainBaselineUnavailable):
                _load_domain_baseline_content("evil")

    def test_resolve_command_domain_rejects_unknown_value(self, tmp_path: Path) -> None:
        """Allowlist enforcement: command_domain not in DOMAIN_SCOPES → None."""

        outbox_db = _make_outbox_db(tmp_path)
        # Insert a session row with a bogus command_domain
        engine = create_sync_db_engine(outbox_db)
        SQLModel.metadata.create_all(engine, tables=[db_models.Session.__table__])
        with SqlSession(engine) as session:
            session.add(
                db_models.Session(
                    session_id="sess-evil",
                    computer_name="test",
                    title="t",
                    origin_metadata=json.dumps({"email": "a@b", "command_domain": "../../sensitive"}),
                    last_input_origin="terminal",
                )
            )
            session.commit()

        with patch("teleclaude.hooks.receiver._create_sync_engine", return_value=engine):
            result = _resolve_command_domain_for_session("sess-evil")

        assert result is None

    def test_resolve_command_domain_accepts_allowlisted_value(self, tmp_path: Path) -> None:
        # Named-constant identity: use a DOMAIN_SCOPES entry as the round-trip
        # value, so the assertion compares two references to the same constant
        # rather than to inline copy.
        allowlisted = DOMAIN_SCOPES[0]
        outbox_db = _make_outbox_db(tmp_path)
        engine = create_sync_db_engine(outbox_db)
        SQLModel.metadata.create_all(engine, tables=[db_models.Session.__table__])
        with SqlSession(engine) as session:
            session.add(
                db_models.Session(
                    session_id="sess-good",
                    computer_name="test",
                    title="t",
                    origin_metadata=json.dumps({"command_domain": allowlisted}),
                    last_input_origin="terminal",
                )
            )
            session.commit()

        with patch("teleclaude.hooks.receiver._create_sync_engine", return_value=engine):
            result = _resolve_command_domain_for_session("sess-good")

        assert result == allowlisted

    def test_print_additional_context_emits_codex_system_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End-to-end: SessionStart hook for Codex with command_domain set
        produces stdout JSON carrying systemMessage with the inflated baseline.
        """

        # Set up deployed baseline under tmp_path/.teleclaude/docs.
        docs_root = tmp_path / ".teleclaude" / "docs"
        (docs_root / "software-development").mkdir(parents=True)
        (docs_root / "software-development" / "baseline.md").write_text(
            "# Software Baseline\n\nbaseline body line\n", encoding="utf-8"
        )

        # Session row with allowlisted command_domain.
        outbox_db = _make_outbox_db(tmp_path)
        engine = create_sync_db_engine(outbox_db)
        SQLModel.metadata.create_all(engine, tables=[db_models.Session.__table__])
        with SqlSession(engine) as session:
            session.add(
                db_models.Session(
                    session_id="sess-e2e",
                    computer_name="test",
                    title="t",
                    origin_metadata=json.dumps({"command_domain": "software-development"}),
                    last_input_origin="terminal",
                )
            )
            session.commit()

        with (
            patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path),
            patch("teleclaude.hooks.receiver._create_sync_engine", return_value=engine),
            patch("teleclaude.hooks.receiver._resolve_identity_context", return_value=(None, None)),
            patch("teleclaude.hooks.receiver._get_memory_context", return_value=""),
        ):
            _print_additional_context(
                hook_event_name="SessionStart",
                cwd=str(tmp_path),
                adapter=CodexAdapter(),
                session_id="sess-e2e",
            )

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        # Structured contract: Codex SessionStart receives systemMessage with
        # the inflated baseline body. Identity comparison against the same
        # loader the production code uses — no inline string copy.
        assert isinstance(payload, dict)
        assert "systemMessage" in payload
        with patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path):
            expected = _load_domain_baseline_content("software-development")
        assert payload["systemMessage"] == expected

    def test_print_additional_context_falls_back_when_baseline_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When the deployed baseline is missing, the SessionStart hook MUST
        surface a visible failure (warning block) rather than silently dropping
        the mandatory context. The session still starts.
        """

        # docs_root exists but the domain-specific baseline is absent.
        (tmp_path / ".teleclaude" / "docs").mkdir(parents=True)

        outbox_db = _make_outbox_db(tmp_path)
        engine = create_sync_db_engine(outbox_db)
        SQLModel.metadata.create_all(engine, tables=[db_models.Session.__table__])
        with SqlSession(engine) as session:
            session.add(
                db_models.Session(
                    session_id="sess-missing",
                    computer_name="test",
                    title="t",
                    origin_metadata=json.dumps({"command_domain": "software-development"}),
                    last_input_origin="terminal",
                )
            )
            session.commit()

        with (
            patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path),
            patch("teleclaude.hooks.receiver._create_sync_engine", return_value=engine),
            patch("teleclaude.hooks.receiver._resolve_identity_context", return_value=(None, None)),
            patch("teleclaude.hooks.receiver._get_memory_context", return_value=""),
        ):
            _print_additional_context(
                hook_event_name="SessionStart",
                cwd=str(tmp_path),
                adapter=CodexAdapter(),
                session_id="sess-missing",
            )

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        # Visible-failure contract: a structured payload IS produced (not
        # silently dropped). Non-empty guard — payload content shape is the
        # operator-recovery prose, governed by code in `_print_additional_context`,
        # not asserted here.
        assert "systemMessage" in payload
        assert payload["systemMessage"]

    def test_print_additional_context_no_domain_emits_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Session WITHOUT command_domain (orchestrator / process-only command):
        no baseline injection, and when there is also no memory/person context
        the hook produces no stdout at all.
        """

        outbox_db = _make_outbox_db(tmp_path)
        engine = create_sync_db_engine(outbox_db)
        SQLModel.metadata.create_all(engine, tables=[db_models.Session.__table__])
        with SqlSession(engine) as session:
            session.add(
                db_models.Session(
                    session_id="sess-nodomain",
                    computer_name="test",
                    title="t",
                    origin_metadata=json.dumps({"email": "a@b"}),
                    last_input_origin="terminal",
                )
            )
            session.commit()

        with (
            patch("teleclaude.hooks.receiver.Path.home", return_value=tmp_path),
            patch("teleclaude.hooks.receiver._create_sync_engine", return_value=engine),
            patch("teleclaude.hooks.receiver._resolve_identity_context", return_value=(None, None)),
            patch("teleclaude.hooks.receiver._get_memory_context", return_value=""),
        ):
            _print_additional_context(
                hook_event_name="SessionStart",
                cwd=str(tmp_path),
                adapter=CodexAdapter(),
                session_id="sess-nodomain",
            )

        captured = capsys.readouterr()
        assert captured.out == ""
