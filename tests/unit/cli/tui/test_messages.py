from __future__ import annotations

import pytest

from teleclaude.cli.tui.messages import CreateSessionRequest, DataRefreshed, PreviewChanged


@pytest.mark.unit
def test_datarefreshed_preserves_optional_chiptunes_state_fields() -> None:
    message = DataRefreshed(
        [],
        [],
        [],
        [],
        {},
        [],
        True,
        chiptunes_loaded=True,
        chiptunes_track="song.sid",
        chiptunes_state_version=2,
    )

    assert message.tts_enabled is True
    assert message.chiptunes_loaded is True
    assert message.chiptunes_track == "song.sid"
    assert message.chiptunes_state_version == 2


@pytest.mark.unit
def test_preview_and_create_session_messages_keep_constructor_values() -> None:
    preview = PreviewChanged("session-1", request_focus=True)
    create = CreateSessionRequest("computer-1", "/repo", agent="codex", native_session_id="native-1")

    assert preview.session_id == "session-1"
    assert preview.request_focus is True
    assert create.computer == "computer-1"
    assert create.project_path == "/repo"
    assert create.agent == "codex"
    assert create.native_session_id == "native-1"
    assert create.revive_session_id is None
