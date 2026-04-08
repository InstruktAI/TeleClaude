"""Tests for teleclaude.chiptunes.songlengths."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from teleclaude.chiptunes.songlengths import _parse_duration, load_songlengths, lookup_duration


@pytest.mark.unit
class TestParseDuration:
    def test_minutes_seconds(self) -> None:
        assert _parse_duration("3:57") == 237.0

    def test_with_milliseconds(self) -> None:
        assert _parse_duration("1:02.500") == 62.5

    def test_single_digit_millis(self) -> None:
        # "0:46.9" → 0.9 is padded to 900ms
        assert _parse_duration("0:46.9") == pytest.approx(46.9)

    def test_zero(self) -> None:
        assert _parse_duration("0:00") == 0.0

    def test_invalid(self) -> None:
        assert _parse_duration("garbage") == 0.0


@pytest.mark.unit
class TestLoadSonglengths:
    def test_parses_database(self, tmp_path: Path) -> None:
        db_file = tmp_path / "Songlengths.md5"
        db_file.write_text(
            "[Database]\n"
            "; /MUSICIANS/Test/Song.sid\n"
            "abcdef1234567890abcdef1234567890=3:57 1:02\n"
            "; /MUSICIANS/Test/Other.sid\n"
            "1234567890abcdef1234567890abcdef=0:30\n",
            encoding="utf-8",
        )
        db = load_songlengths(db_file)
        assert len(db) == 2
        assert db["abcdef1234567890abcdef1234567890"] == [237.0, 62.0]
        assert db["1234567890abcdef1234567890abcdef"] == [30.0]

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        db = load_songlengths(tmp_path / "nonexistent.md5")
        assert db == {}


@pytest.mark.unit
class TestLookupDuration:
    def test_finds_entry_by_md5(self, tmp_path: Path) -> None:
        sid_file = tmp_path / "test.sid"
        sid_file.write_bytes(b"PSID test data")
        md5 = hashlib.md5(b"PSID test data").hexdigest()  # noqa: S324
        db = {md5: [120.0, 60.0]}

        assert lookup_duration(db, sid_file, subtune=0) == 120.0
        assert lookup_duration(db, sid_file, subtune=1) == 60.0

    def test_returns_none_for_unknown(self, tmp_path: Path) -> None:
        sid_file = tmp_path / "test.sid"
        sid_file.write_bytes(b"unknown data")
        assert lookup_duration({}, sid_file) is None

    def test_returns_first_subtune_for_out_of_range(self, tmp_path: Path) -> None:
        sid_file = tmp_path / "test.sid"
        sid_file.write_bytes(b"data")
        md5 = hashlib.md5(b"data").hexdigest()  # noqa: S324
        db = {md5: [90.0]}

        assert lookup_duration(db, sid_file, subtune=5) == 90.0
