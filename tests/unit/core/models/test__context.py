"""Characterization tests for teleclaude.core.models._context."""

from __future__ import annotations

import pytest

from teleclaude.core.models._context import (
    BaseCommandContext,
    FileContext,
    MessageContext,
    NewSessionContext,
    SessionCommandContext,
    SystemCommandContext,
    VoiceContext,
)


class TestBaseCommandContext:
    @pytest.mark.unit
    def test_session_id_stored(self):
        ctx = BaseCommandContext(session_id="abc")
        assert ctx.session_id == "abc"


class TestSessionCommandContext:
    @pytest.mark.unit
    def test_inherits_session_id(self):
        ctx = SessionCommandContext(session_id="sess1")
        assert ctx.session_id == "sess1"


class TestNewSessionContext:
    @pytest.mark.unit
    def test_fields_stored(self):
        ctx = NewSessionContext(session_id="s1", project_path="/p", title="T", message="hello")
        assert ctx.session_id == "s1"
        assert ctx.project_path == "/p"
        assert ctx.title == "T"
        assert ctx.message == "hello"


class TestMessageContext:
    @pytest.mark.unit
    def test_text_stored(self):
        ctx = MessageContext(session_id="s2", text="ping")
        assert ctx.text == "ping"
        assert ctx.session_id == "s2"


class TestVoiceContext:
    @pytest.mark.unit
    def test_audio_path_stored(self):
        ctx = VoiceContext(session_id="s3", audio_path="/tmp/audio.ogg")
        assert ctx.audio_path == "/tmp/audio.ogg"
        assert ctx.session_id == "s3"


class TestFileContext:
    @pytest.mark.unit
    def test_mime_type_defaults_to_none(self):
        ctx = FileContext(session_id="s4", file_path="/tmp/file.txt")
        assert ctx.mime_type is None

    @pytest.mark.unit
    def test_mime_type_can_be_set(self):
        ctx = FileContext(session_id="s4", file_path="/tmp/file.txt", mime_type="text/plain")
        assert ctx.mime_type == "text/plain"

    @pytest.mark.unit
    def test_file_path_stored(self):
        ctx = FileContext(session_id="s4", file_path="/tmp/file.txt")
        assert ctx.file_path == "/tmp/file.txt"


class TestSystemCommandContext:
    @pytest.mark.unit
    def test_default_command_is_empty_string(self):
        ctx = SystemCommandContext()
        assert ctx.command == ""

    @pytest.mark.unit
    def test_default_from_computer_is_unknown(self):
        ctx = SystemCommandContext()
        assert ctx.from_computer == "unknown"

    @pytest.mark.unit
    def test_command_can_be_set(self):
        ctx = SystemCommandContext(command="restart")
        assert ctx.command == "restart"

    @pytest.mark.unit
    def test_from_computer_can_be_set(self):
        ctx = SystemCommandContext(from_computer="node-2")
        assert ctx.from_computer == "node-2"
