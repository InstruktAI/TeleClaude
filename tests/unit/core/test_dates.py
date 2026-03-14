"""Characterization tests for teleclaude.core.dates."""

from __future__ import annotations

from datetime import UTC, datetime, timezone, tzinfo

import pytest

from teleclaude.core.dates import ensure_utc, format_local_datetime, get_local_timezone, parse_iso_datetime


class TestGetLocalTimezone:
    @pytest.mark.unit
    def test_returns_tzinfo(self):
        tz = get_local_timezone()
        assert isinstance(tz, tzinfo)

    @pytest.mark.unit
    def test_returns_non_none(self):
        tz = get_local_timezone()
        assert tz is not None


class TestFormatLocalDatetime:
    @pytest.mark.unit
    def test_returns_time_only_by_default(self):
        dt = datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)
        result = format_local_datetime(dt)
        assert ":" in result
        assert len(result) == 8  # HH:MM:SS

    @pytest.mark.unit
    def test_include_date_produces_longer_string(self):
        dt = datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)
        result = format_local_datetime(dt, include_date=True)
        assert len(result) > 8
        assert "-" in result

    @pytest.mark.unit
    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2024, 6, 15, 12, 30, 45)  # naive
        result = format_local_datetime(dt)
        assert len(result) == 8 and ":" in result  # HH:MM:SS format


class TestEnsureUtc:
    @pytest.mark.unit
    def test_naive_datetime_gets_utc_tzinfo(self):
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = ensure_utc(dt)
        assert result.tzinfo == UTC

    @pytest.mark.unit
    def test_already_utc_stays_utc(self):
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = ensure_utc(dt)
        assert result.tzinfo == UTC

    @pytest.mark.unit
    def test_other_tz_converted_to_utc(self):
        from datetime import timedelta

        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2024, 1, 1, 7, 0, 0, tzinfo=eastern)
        result = ensure_utc(dt)
        assert result.tzinfo == UTC


class TestParseIsodatetime:
    @pytest.mark.unit
    def test_valid_iso_string_returns_utc_datetime(self):
        result = parse_iso_datetime("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.tzinfo == UTC
        assert result.year == 2024
        assert result.month == 1

    @pytest.mark.unit
    def test_iso_string_with_offset_normalized_to_utc(self):
        result = parse_iso_datetime("2024-01-15T12:00:00+02:00")
        assert result is not None
        assert result.tzinfo == UTC

    @pytest.mark.unit
    def test_none_returns_none(self):
        assert parse_iso_datetime(None) is None

    @pytest.mark.unit
    def test_invalid_string_returns_none(self):
        assert parse_iso_datetime("not-a-date") is None

    @pytest.mark.unit
    def test_datetime_object_returned_as_utc(self):
        dt = datetime(2024, 3, 1, 9, 0, 0, tzinfo=UTC)
        result = parse_iso_datetime(dt)
        assert result is not None
        assert result.tzinfo == UTC

    @pytest.mark.unit
    def test_non_string_non_datetime_returns_none(self):
        assert parse_iso_datetime(12345) is None
        assert parse_iso_datetime([]) is None
