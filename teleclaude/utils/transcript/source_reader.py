"""Format-aware native transcript reads; byte progress is never delivery progress."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, cast

import zstandard

from teleclaude.core.models._types import JsonDict, JsonValue

_BINARY_READ: Literal["rb"] = "rb"
_UTF8 = "utf-8"
_JSON_SUFFIX = ".json"
_NEWLINE = b"\n"
_EMPTY_BYTES = b""
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_READ_BYTES = 1_048_576
_ANCHOR_BYTES = 128


class SourceChange(StrEnum):
    """How a source read relates to its preceding successful read."""

    UNCHANGED = "unchanged"
    APPENDED = "appended"
    REPLACED = "replaced"


class SourceFormat(StrEnum):
    """Native file encodings supported by the shared reader."""

    JSONL = "jsonl"
    JSON = "json"
    ZSTD_JSONL = "zstd_jsonl"


@dataclass(frozen=True)
class SourceVersion:
    """Identity and observed revision of an opened file."""

    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, stat: os.stat_result) -> SourceVersion:
        """Capture native file identity without a separate pathname lookup."""
        return cls(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@dataclass(frozen=True)
class TranscriptSourceRead:
    """Raw append or replacement, ready for the existing provider normalizer."""

    change: SourceChange
    format: SourceFormat
    records: tuple[JsonDict, ...] = ()
    document: JsonValue = None
    decode_error: json.JSONDecodeError | None = None


class _StreamingDecoder(Protocol):
    @property
    def eof(self) -> bool: ...

    @property
    def unused_data(self) -> bytes: ...

    def decompress(self, data: bytes) -> bytes: ...


class TranscriptSourceReader:
    """Own one source cursor, incomplete record and optional decompression state.

    JSONL append optimization relies on the native writer's append-only prefix.
    Identity, shrinkage and observed boundary rewrites invalidate that state.
    """

    def __init__(self) -> None:
        self._version: SourceVersion | None = None
        self._format = SourceFormat.JSONL
        self._partial = _EMPTY_BYTES
        self._anchor = _EMPTY_BYTES
        self._provisional = False
        self._decoder: _StreamingDecoder | None = None
        self._decode_error: json.JSONDecodeError | None = None
        self.decoded_bytes = 0

    def reset(self) -> None:
        """Discard derived progress after invalidation or a failed read."""
        self._version = None
        self._format = SourceFormat.JSONL
        self._partial = _EMPTY_BYTES
        self._anchor = _EMPTY_BYTES
        self._provisional = False
        self._decoder = None
        self._decode_error = None
        self.decoded_bytes = 0

    def read(self, path: Path) -> TranscriptSourceRead:
        """Read one fixed EOF; unchanged versions require no parsing."""
        try:
            with path.open(_BINARY_READ) as source:
                version = SourceVersion.from_stat(os.fstat(source.fileno()))
                if version == self._version:
                    return TranscriptSourceRead(SourceChange.UNCHANGED, self._format)
                appended = self._can_append(source, version)
                offset = self._version.size if appended and self._version is not None else 0
                if not appended:
                    self.reset()
                    self._format = self._detect_format(source, path)
                self._decode_error = None
                source.seek(offset)
                if self._format is SourceFormat.JSON:
                    document = cast(JsonValue, json.loads(source.read(version.size).decode(_UTF8)))
                    result = TranscriptSourceRead(SourceChange.REPLACED, self._format, document=document)
                    self.decoded_bytes = version.size
                else:
                    records = self._read_records(source, version.size - offset)
                    result = TranscriptSourceRead(
                        SourceChange.APPENDED if appended else SourceChange.REPLACED,
                        self._format,
                        tuple(records),
                        decode_error=self._decode_error,
                    )
                source.seek(max(0, version.size - _ANCHOR_BYTES))
                self._anchor = source.read(min(version.size, _ANCHOR_BYTES))
                self._version = version
                return result
        except Exception:
            self.reset()
            raise

    def _can_append(self, source: BinaryIO, version: SourceVersion) -> bool:
        previous = self._version
        if (
            previous is None
            or self._format is SourceFormat.JSON
            or self._provisional
            or previous.size < len(_ZSTD_MAGIC)
            or (previous.device, previous.inode) != (version.device, version.inode)
            or version.size <= previous.size
        ):
            return False
        source.seek(max(0, previous.size - _ANCHOR_BYTES))
        return source.read(min(previous.size, _ANCHOR_BYTES)) == self._anchor

    @staticmethod
    def _detect_format(source: BinaryIO, path: Path) -> SourceFormat:
        source.seek(0)
        if source.read(len(_ZSTD_MAGIC)) == _ZSTD_MAGIC:
            return SourceFormat.ZSTD_JSONL
        return SourceFormat.JSON if path.suffix == _JSON_SUFFIX else SourceFormat.JSONL

    def _read_records(self, source: BinaryIO, remaining: int) -> list[JsonDict]:
        records: list[JsonDict] = []
        while remaining:
            data = source.read(min(remaining, _READ_BYTES))
            if not data:
                break
            remaining -= len(data)
            if self._format is SourceFormat.ZSTD_JSONL:
                data = self._inflate(data)
            self.decoded_bytes += len(data)
            lines = (self._partial + data).split(_NEWLINE)
            self._partial = lines.pop()
            for line in lines:
                self._append_record(records, line)
        # Historical/final files can end with a valid object but no newline.
        # Expose it provisionally; a later append replaces the view from source.
        if self._partial:
            try:
                value: object = json.loads(self._partial.decode(_UTF8))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                self._provisional = True
                if isinstance(value, dict):
                    records.append(cast(JsonDict, value))
        return records

    def _append_record(self, records: list[JsonDict], line: bytes) -> None:
        if not line.strip():
            return
        try:
            value: object = json.loads(line.decode(_UTF8))
        except json.JSONDecodeError as exc:
            if self._decode_error is None:
                self._decode_error = exc
            return
        if isinstance(value, dict):
            records.append(cast(JsonDict, value))

    def _inflate(self, data: bytes) -> bytes:
        chunks: list[bytes] = []
        while data:
            if self._decoder is None or self._decoder.eof:
                self._decoder = cast(_StreamingDecoder, zstandard.ZstdDecompressor().decompressobj())
            chunks.append(self._decoder.decompress(data))
            data = self._decoder.unused_data if self._decoder.eof else _EMPTY_BYTES
        return _EMPTY_BYTES.join(chunks)
