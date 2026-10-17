"""Stdlib-only identity observations from the actual isolated tool interpreter."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Final, TypedDict

IMAGE_REFERENCE: Final = Path("/proc/self/exe")
SCHEMA_VERSION: Final = 1
SUCCESS: Final = 0
FAILURE: Final = 1
READ_BINARY: Final = "rb"
SHA256: Final = "sha256"
EMPTY: Final = ""


class MetadataError(StrEnum):
    """Failures that keep interpreter identity unavailable to its observer."""

    NOT_ISOLATED = "not_isolated_without_site"
    UNEXPECTED_ARGUMENTS = "unexpected_arguments"
    FILE_CHANGED = "identity_file_changed"
    OBSERVATION_FAILED = "identity_observation_failed"


class FileIdentity(TypedDict):
    """Byte identity and native file facts at this observation point."""

    sha256: str
    size_bytes: int
    device: int
    inode: int


class Isolation(TypedDict):
    """Native interpreter flags, without importing site or an application package."""

    isolated: int
    no_site: int
    ignore_environment: int
    no_user_site: int


class InterpreterMetadata(TypedDict):
    """The actual running image, requested entry and interpreter's own metadata."""

    schema_version: int
    requested_executable: str
    native_image_path: str
    native_image: FileIdentity
    helper_file: FileIdentity
    implementation: str
    version: str
    version_info: list[int]
    prefix: str
    base_prefix: str
    isolation: Isolation


class FailureMetadata(TypedDict):
    """A missing observation remains an explicit failure, with no replacement identity."""

    schema_version: int
    error: MetadataError
    error_class: str
    detail: str


def _file_identity(path: Path) -> FileIdentity:
    with path.open(mode=READ_BINARY) as handle:
        before = os.fstat(handle.fileno())
        digest = hashlib.file_digest(handle, SHA256).hexdigest()
        after = os.fstat(handle.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise RuntimeError(MetadataError.FILE_CHANGED)
    return FileIdentity(sha256=digest, size_bytes=after.st_size, device=after.st_dev, inode=after.st_ino)


def observe() -> InterpreterMetadata:
    """Read the current process image through the kernel reference and its own stdlib metadata."""
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment and sys.flags.no_user_site):
        raise RuntimeError(MetadataError.NOT_ISOLATED)
    return InterpreterMetadata(
        schema_version=SCHEMA_VERSION,
        requested_executable=sys.executable,
        native_image_path=os.readlink(IMAGE_REFERENCE),
        native_image=_file_identity(IMAGE_REFERENCE),
        helper_file=_file_identity(Path(__file__)),
        implementation=sys.implementation.name,
        version=sys.version,
        version_info=list(sys.version_info[:3]),
        prefix=sys.prefix,
        base_prefix=sys.base_prefix,
        isolation=Isolation(
            isolated=sys.flags.isolated,
            no_site=sys.flags.no_site,
            ignore_environment=sys.flags.ignore_environment,
            no_user_site=sys.flags.no_user_site,
        ),
    )


def main() -> int:
    """Emit a single structured identity observation for the declared no-argument invocation."""
    if len(sys.argv) != 1:
        print(
            json.dumps(
                FailureMetadata(
                    schema_version=SCHEMA_VERSION,
                    error=MetadataError.UNEXPECTED_ARGUMENTS,
                    error_class=EMPTY,
                    detail=EMPTY,
                )
            ),
            file=sys.stderr,
        )
        return FAILURE
    try:
        metadata = observe()
    except (OSError, RuntimeError) as error:
        print(
            json.dumps(
                FailureMetadata(
                    schema_version=SCHEMA_VERSION,
                    error=MetadataError.OBSERVATION_FAILED,
                    error_class=type(error).__name__,
                    detail=str(error),
                )
            ),
            file=sys.stderr,
        )
        return FAILURE
    print(json.dumps(metadata, sort_keys=True))
    return SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
