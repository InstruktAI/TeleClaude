"""SID file header parser — PSID v1–v4 and RSID format support."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import cast


@dataclass
class SIDHeader:  # pylint: disable=too-many-instance-attributes
    """Parsed PSID/RSID file header."""

    magic: bytes  # b'PSID' or b'RSID'
    version: int  # 1–4
    data_offset: int  # offset to C64 payload in file
    load_address: int  # 0 means first 2 payload bytes are the real address (LE)
    init_address: int  # address of init routine
    play_address: int  # address of play routine (0 = interrupt-driven RSID)
    songs: int  # number of subtunes
    start_song: int  # default start subtune (1-based)
    speed: int  # speed flags (bit per subtune: 0=VBI, 1=CIA)
    name: str  # song title
    author: str  # composer name
    released: str  # release info
    flags: int  # v2+ extended flags
    payload: bytes  # raw C64 binary payload (starting after header)


_PSID_MAGIC = b"PSID"
_RSID_MAGIC = b"RSID"

# Fixed-size fields common to v1+:  magic(4) version(2) data_offset(2) load(2) init(2) play(2)
# songs(2) start_song(2) speed(4) name(32) author(32) released(32)
_HEADER_V1_FMT = ">4sHHHHHHHI32s32s32s"
_HEADER_V1_SIZE = struct.calcsize(_HEADER_V1_FMT)  # 118 bytes

# v2+ adds: flags(2) start_page(1) page_length(1) second_sid_address(1) third_sid_address(1)
_HEADER_V2_EXTRA_FMT = ">H4B"
_HEADER_V2_EXTRA_SIZE = struct.calcsize(_HEADER_V2_EXTRA_FMT)  # 6 bytes


def parse_sid_file(path: Path) -> SIDHeader:  # pylint: disable=too-many-locals
    """Parse a PSID or RSID file and return its header.

    Raises:
        ValueError: if the file is not a valid PSID/RSID, or is an unsupported RSID.
        OSError: if the file cannot be read.
    """
    data = path.read_bytes()

    if len(data) < _HEADER_V1_SIZE:
        raise ValueError(f"File too short to be a valid SID: {path}")

    header_values = cast(
        tuple[bytes, int, int, int, int, int, int, int, int, bytes, bytes, bytes],
        struct.unpack_from(_HEADER_V1_FMT, data, 0),
    )
    (
        magic,
        version,
        data_offset,
        load_address,
        init_address,
        play_address,
        songs,
        start_song,
        speed,
        name_raw,
        author_raw,
        released_raw,
    ) = header_values

    if magic not in (_PSID_MAGIC, _RSID_MAGIC):
        raise ValueError(f"Not a PSID/RSID file (magic={magic!r}): {path}")

    if magic == _RSID_MAGIC and play_address == 0:
        raise ValueError(f"RSID file with play_address=0 (interrupt-driven) is unsupported: {path}")

    flags = 0
    if version >= 2 and data_offset >= _HEADER_V1_SIZE + _HEADER_V2_EXTRA_SIZE:
        extra_values = cast(tuple[int, int, int, int, int], struct.unpack_from(_HEADER_V2_EXTRA_FMT, data, _HEADER_V1_SIZE))
        flags = extra_values[0]

    payload = data[data_offset:]

    # Handle embedded load address (load_address == 0)
    if load_address == 0:
        if len(payload) < 2:
            raise ValueError(f"Payload too short for embedded load address: {path}")
        load_address = cast(int, struct.unpack_from("<H", payload, 0)[0])
        payload = payload[2:]

    return SIDHeader(
        magic=magic,
        version=version,
        data_offset=data_offset,
        load_address=load_address,
        init_address=init_address,
        play_address=play_address,
        songs=songs,
        start_song=start_song,
        speed=speed,
        name=_decode_sid_string(name_raw),
        author=_decode_sid_string(author_raw),
        released=_decode_sid_string(released_raw),
        flags=flags,
        payload=payload,
    )


def is_pal(header: SIDHeader) -> bool:
    """Return True if the tune is PAL (or unknown — default to PAL).

    v2+ flags bits 2–3: 0=unknown, 1=PAL, 2=NTSC, 3=both.
    v1 files have no clock flag; assume PAL.
    """
    if header.version < 2:
        return True
    clock_bits = (header.flags >> 2) & 0x3
    return clock_bits != 2  # anything other than explicit NTSC is treated as PAL


def speed_for_subtune(header: SIDHeader, subtune: int) -> str:
    """Return speed type for a subtune (0-based index).

    Returns 'VBI' for vertical blank interrupt (50/60 Hz) or 'CIA' for CIA timer.
    Subtunes beyond bit 31 default to CIA.
    """
    if subtune < 32:
        return "CIA" if (header.speed >> subtune) & 1 else "VBI"
    return "CIA"


def _decode_sid_string(raw: bytes) -> str:
    """Decode a null-terminated Latin-1 string from a fixed-width SID field."""
    null_pos = raw.find(b"\x00")
    if null_pos >= 0:
        raw = raw[:null_pos]
    return raw.decode("latin-1", errors="replace")
