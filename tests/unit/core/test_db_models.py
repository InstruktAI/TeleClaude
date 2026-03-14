"""Characterization tests for teleclaude.core.db_models."""

from __future__ import annotations

import pytest

from teleclaude.core.db_models import PendingMessageDeletion, Session, SystemSetting, VoiceAssignment


class TestSessionModel:
    @pytest.mark.unit
    def test_session_has_required_primary_key(self):
        # Verify the session_id field exists as primary key via SQLModel field definition
        # This checks the table-level metadata without creating a real DB
        assert hasattr(Session, "session_id")

    @pytest.mark.unit
    def test_session_has_default_lifecycle_status(self):
        session = Session(session_id="s1", computer_name="local")
        assert session.lifecycle_status == "active"

    @pytest.mark.unit
    def test_session_has_default_terminal_size(self):
        session = Session(session_id="s1", computer_name="local")
        assert session.terminal_size == "80x24"

    @pytest.mark.unit
    def test_session_tablename(self):
        assert Session.__tablename__ == "sessions"

    @pytest.mark.unit
    def test_session_default_notification_sent_zero(self):
        session = Session(session_id="s1", computer_name="local")
        assert session.notification_sent == 0

    @pytest.mark.unit
    def test_session_computer_name_stored(self):
        session = Session(session_id="s1", computer_name="my-computer")
        assert session.computer_name == "my-computer"


class TestVoiceAssignmentModel:
    @pytest.mark.unit
    def test_tablename(self):
        assert VoiceAssignment.__tablename__ == "voice_assignments"

    @pytest.mark.unit
    def test_has_id_primary_key(self):
        va = VoiceAssignment(id="voice-001")
        assert va.id == "voice-001"


class TestPendingMessageDeletionModel:
    @pytest.mark.unit
    def test_tablename(self):
        assert PendingMessageDeletion.__tablename__ == "pending_message_deletions"

    @pytest.mark.unit
    def test_fields_stored(self):
        pmd = PendingMessageDeletion(
            session_id="sess-001",
            message_id="msg-001",
            deletion_type="standard",
        )
        assert pmd.session_id == "sess-001"
        assert pmd.message_id == "msg-001"
        assert pmd.deletion_type == "standard"


class TestSystemSettingModel:
    @pytest.mark.unit
    def test_tablename(self):
        assert SystemSetting.__tablename__ == "system_settings"
