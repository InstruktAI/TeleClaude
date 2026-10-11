"""Privileged, descriptor-relative creation inside an inspector controller root."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

_DESCRIPTION = "Create isolated inspector directories or install staged files."
_ROOT_ARGUMENT = "root"
_TARGET_ARGUMENT = "target"
_UID_ARGUMENT = "uid"
_GID_ARGUMENT = "gid"
_OPERATION_ARGUMENT = "operation"
_SOURCE_OPTION = "--source"
_MODE_OPTION = "--mode"
_PRIVATE_MODE = 0o600
_READ_ONLY_MODE = 0o444
_DIRECTORY_MODE = 0o700
_MAX_FILE_BYTES = 4 * 1024 * 1024
_OCTAL_BASE = 8
_PARENT_COMPONENT = ".."
_INVALID_PATH = "Inspector filesystem boundary refused the path."
_INVALID_SOURCE = "Inspector filesystem boundary refused the staged file."
_BINARY_READ_MODE = "rb"
_BINARY_WRITE_MODE = "wb"
_OCTAL_FORMAT = "o"
_STAGING_DIRECTORY = "inspector-controller-staging"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_SOURCE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
_TARGET_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


class FilesystemOperation(StrEnum):
    """The only mutations supported by the privileged setup helper."""

    CREATE_DIRECTORY = "create_directory"
    INSTALL_FILE = "install_file"


class FilesystemArguments(argparse.Namespace):
    """Typed arguments at the privileged helper's command-line boundary."""

    operation: str
    root: Path
    target: Path
    uid: int
    gid: int
    source: Path | None
    mode: str


class FilesystemFailure(TypedDict):
    """The complete diagnostic payload; no exception message or path is retained."""

    exception_type: str
    errno: int | None


@contextmanager
def _destination_parent(root: Path, target: Path) -> Iterator[int]:
    """Resolve with privilege, then anchor traversal and mutation to non-symlink descriptors."""
    if root.is_symlink():
        raise ValueError(_INVALID_PATH)
    root_path = root.resolve(strict=True)
    relative = target.absolute().relative_to(root.absolute())
    resolved_target = target.resolve()
    if (
        not relative.parts
        or _PARENT_COMPONENT in relative.parts
        or not resolved_target.is_relative_to(root_path)
        or resolved_target == root_path
    ):
        raise ValueError(_INVALID_PATH)
    descriptor = os.open(root_path, _DIRECTORY_FLAGS)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def create_directory(root: Path, target: Path, uid: int, gid: int) -> None:
    """Exclusively create a private directory without following any provider-controlled link."""
    with _destination_parent(root, target) as parent:
        os.mkdir(target.name, mode=_DIRECTORY_MODE, dir_fd=parent)
        descriptor = os.open(target.name, _DIRECTORY_FLAGS, dir_fd=parent)
        try:
            os.fchown(descriptor, uid, gid)
            os.fchmod(descriptor, _DIRECTORY_MODE)
        finally:
            os.close(descriptor)


def install_file(root: Path, target: Path, uid: int, gid: int, source: Path, mode: int) -> None:
    """Copy bounded controller staging bytes into a new provider-owned file."""
    if mode not in {_PRIVATE_MODE, _READ_ONLY_MODE}:
        raise ValueError(_INVALID_SOURCE)
    staging = root / _STAGING_DIRECTORY
    if source.parent != staging or staging.is_symlink():
        raise ValueError(_INVALID_SOURCE)
    controller_uid = root.stat().st_uid
    staging_metadata = staging.stat()
    if staging_metadata.st_uid != controller_uid or stat.S_IMODE(staging_metadata.st_mode) != _DIRECTORY_MODE:
        raise ValueError(_INVALID_SOURCE)
    source_descriptor = os.open(source, _SOURCE_FLAGS)
    with os.fdopen(source_descriptor, mode=_BINARY_READ_MODE) as staged:
        metadata = os.fstat(staged.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_MODE
            or metadata.st_uid != controller_uid
        ):
            raise ValueError(_INVALID_SOURCE)
        content = staged.read(_MAX_FILE_BYTES + 1)
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError(_INVALID_SOURCE)
    with _destination_parent(root, target) as parent:
        descriptor = os.open(target.name, _TARGET_FLAGS, _PRIVATE_MODE, dir_fd=parent)
        with os.fdopen(descriptor, mode=_BINARY_WRITE_MODE) as destination:
            destination.write(content)
            destination.flush()
            os.fchown(destination.fileno(), uid, gid)
            os.fchmod(destination.fileno(), mode)


def main(argv: list[str] | None = None) -> int:
    """Expose only secret-free setup arguments and bounded failure metadata to the controller."""
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(_OPERATION_ARGUMENT, choices=list(FilesystemOperation))
    parser.add_argument(_ROOT_ARGUMENT, type=Path)
    parser.add_argument(_TARGET_ARGUMENT, type=Path)
    parser.add_argument(_UID_ARGUMENT, type=int)
    parser.add_argument(_GID_ARGUMENT, type=int)
    parser.add_argument(_SOURCE_OPTION, type=Path)
    parser.add_argument(_MODE_OPTION, default=format(_PRIVATE_MODE, _OCTAL_FORMAT))
    arguments = FilesystemArguments()
    parser.parse_args(argv, namespace=arguments)
    try:
        operation = FilesystemOperation(arguments.operation)
        if operation is FilesystemOperation.CREATE_DIRECTORY:
            create_directory(arguments.root, arguments.target, arguments.uid, arguments.gid)
        else:
            if arguments.source is None:
                raise ValueError(_INVALID_SOURCE)
            install_file(
                arguments.root,
                arguments.target,
                arguments.uid,
                arguments.gid,
                arguments.source,
                int(arguments.mode, _OCTAL_BASE),
            )
    except (OSError, RuntimeError, ValueError) as error:
        failure = FilesystemFailure(
            exception_type=type(error).__name__, errno=error.errno if isinstance(error, OSError) else None
        )
        print(json.dumps(failure))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
