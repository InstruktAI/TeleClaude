"""Characterization tests for teleclaude.chiptunes.sid_parser."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

import teleclaude.chiptunes.sid_parser as sid_parser


def _pad(text: str) -> bytes:
    return text.encode("latin-1").ljust(32, b"\x00")


def _sid_bytes(
    *,
    magic: bytes = b"PSID",
    version: int = 1,
    data_offset: int | None = None,
    load_address: int = 0x1000,
    init_address: int = 0x1003,
    play_address: int = 0x1006,
    songs: int = 1,
    start_song: int = 1,
    speed: int = 0,
    flags: int = 0,
    payload: bytes = b"\xea\xea",
) -> bytes:
    if data_offset is None:
        data_offset = (
            sid_parser._HEADER_V1_SIZE if version < 2 else sid_parser._HEADER_V1_SIZE + sid_parser._HEADER_V2_EXTRA_SIZE
        )
    header = struct.pack(
        sid_parser._HEADER_V1_FMT,
        magic,
        version,
        data_offset,
        load_address,
        init_address,
        play_address,
        songs,
        start_song,
        speed,
        _pad("Song"),
        _pad("Author"),
        _pad("1988"),
    )
    if version >= 2:
        header += struct.pack(sid_parser._HEADER_V2_EXTRA_FMT, flags, 0, 0, 0, 0)
    return header + payload


@pytest.mark.unit
class TestParseSIDFile:
    def test_parse_psid_v1_with_embedded_load_address(self, tmp_path: Path) -> None:
        path = tmp_path / "embedded.sid"
        path.write_bytes(_sid_bytes(load_address=0, payload=struct.pack("<H", 0x2000) + b"\x01\x02\x03"))

        header = sid_parser.parse_sid_file(path)

        assert header.magic == b"PSID"
        assert header.version == 1
        assert header.load_address == 0x2000
        assert header.payload == b"\x01\x02\x03"
        assert header.name == "Song"
        assert header.author == "Author"

    def test_parse_psid_v2_reads_flags_and_helper_functions(self, tmp_path: Path) -> None:
        path = tmp_path / "v2.sid"
        path.write_bytes(_sid_bytes(version=2, flags=0b1000, speed=0b10))

        header = sid_parser.parse_sid_file(path)

        assert header.flags == 0b1000
        assert sid_parser.is_pal(header) is False
        assert sid_parser.speed_for_subtune(header, 0) == "VBI"
        assert sid_parser.speed_for_subtune(header, 1) == "CIA"
        assert sid_parser.speed_for_subtune(header, 40) == "CIA"

    def test_parse_rejects_short_files(self, tmp_path: Path) -> None:
        path = tmp_path / "short.sid"
        path.write_bytes(b"too short")

        with pytest.raises(ValueError, match="File too short"):
            sid_parser.parse_sid_file(path)

    def test_parse_rejects_invalid_magic(self, tmp_path: Path) -> None:
        path = tmp_path / "not-sid.sid"
        path.write_bytes(_sid_bytes(magic=b"NOPE"))

        with pytest.raises(ValueError, match="Not a PSID/RSID file"):
            sid_parser.parse_sid_file(path)

    def test_parse_rejects_interrupt_driven_rsid_files(self, tmp_path: Path) -> None:
        path = tmp_path / "rsid.sid"
        path.write_bytes(_sid_bytes(magic=b"RSID", play_address=0))

        with pytest.raises(ValueError, match="unsupported"):
            sid_parser.parse_sid_file(path)
