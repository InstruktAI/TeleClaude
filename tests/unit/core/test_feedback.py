"""Characterization tests for teleclaude.core.feedback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.core.feedback import get_last_output_summary


def _make_session(last_output_summary=None, last_output_raw=None):
    session = MagicMock()
    session.last_output_summary = last_output_summary
    session.last_output_raw = last_output_raw
    return session


class TestGetLastOutputSummary:
    @pytest.mark.unit
    def test_returns_summary_when_present(self):
        session = _make_session(last_output_summary="summary text", last_output_raw="raw text")
        result = get_last_output_summary(session)
        assert result == "summary text"

    @pytest.mark.unit
    def test_falls_back_to_raw_when_no_summary(self):
        session = _make_session(last_output_summary=None, last_output_raw="raw text")
        result = get_last_output_summary(session)
        assert result == "raw text"

    @pytest.mark.unit
    def test_returns_none_when_both_absent(self):
        session = _make_session(last_output_summary=None, last_output_raw=None)
        result = get_last_output_summary(session)
        assert result is None

    @pytest.mark.unit
    def test_empty_summary_falls_back_to_raw(self):
        session = _make_session(last_output_summary="", last_output_raw="raw text")
        result = get_last_output_summary(session)
        assert result == "raw text"
