"""Publish complete documentation generations without exposing an incomplete root."""

from __future__ import annotations

import ctypes
import errno
import os
import platform
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

_LINUX_AT_FDCWD = -100
_DARWIN_AT_FDCWD = -2
_RENAME_EXCHANGE = 0x2
_RENAME_SWAP = 0x2
_Exchange = Callable[[Path, Path], None]


class _NativeExchange(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, from_fd: int, source: bytes, to_fd: int, target: bytes, flags: int) -> int: ...


class DocsPublicationError(RuntimeError):
    """A documentation generation cannot become the deployed generation."""


class DocsPublicationUnsupportedError(DocsPublicationError):
    """The host cannot atomically exchange two documentation roots."""


class DocsPublicationExchangeError(DocsPublicationError):
    """The operating system rejected an attempted documentation-root exchange."""


def publish_generation(staging_root: Path, deployed_root: Path) -> Path | None:
    """Publish a staged directory and return the displaced generation when present."""
    _validate_generation_paths(staging_root, deployed_root)
    if not os.path.lexists(deployed_root):
        try:
            os.replace(staging_root, deployed_root)
        except OSError as exc:
            raise DocsPublicationExchangeError(
                f"cannot create deployed documentation root {deployed_root}: {exc}"
            ) from exc
        return None
    exchange = _exchange_function()
    exchange(staging_root, deployed_root)
    return staging_root


def _validate_generation_paths(staging_root: Path, deployed_root: Path) -> None:
    if not staging_root.is_dir():
        raise DocsPublicationError(f"staging documentation root is not a directory: {staging_root}")
    try:
        staging_device = staging_root.stat().st_dev
        deployed_device = deployed_root.parent.stat().st_dev
    except OSError as exc:
        raise DocsPublicationError(f"cannot inspect documentation publication paths: {exc}") from exc
    if staging_device != deployed_device:
        raise DocsPublicationUnsupportedError("staging and deployed documentation roots must share one filesystem")


def _exchange_function() -> _Exchange:
    system = platform.system()
    library = ctypes.CDLL(None, use_errno=True)
    if system == "Linux":
        native = getattr(library, "renameat2", None)
        if native is None:
            raise DocsPublicationUnsupportedError("libc does not expose renameat2")
        function = cast(_NativeExchange, native)
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int

        def exchange(staging_root: Path, deployed_root: Path) -> None:
            _call_exchange(function, staging_root, deployed_root, _RENAME_EXCHANGE, _LINUX_AT_FDCWD)

        return exchange
    if system == "Darwin":
        native = getattr(library, "renameatx_np", None)
        if native is None:
            raise DocsPublicationUnsupportedError("libc does not expose renameatx_np")
        function = cast(_NativeExchange, native)
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int

        def exchange(staging_root: Path, deployed_root: Path) -> None:
            _call_exchange(function, staging_root, deployed_root, _RENAME_SWAP, _DARWIN_AT_FDCWD)

        return exchange
    raise DocsPublicationUnsupportedError(f"atomic documentation exchange is unsupported on {system}")


def _call_exchange(
    function: _NativeExchange, staging_root: Path, deployed_root: Path, flag: int, directory_fd: int
) -> None:
    result = function(
        directory_fd,
        os.fsencode(staging_root),
        directory_fd,
        os.fsencode(deployed_root),
        flag,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    error = OSError(error_number, os.strerror(error_number), str(deployed_root))
    if error_number in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
        raise DocsPublicationUnsupportedError(f"atomic documentation exchange is unavailable: {error}") from error
    raise DocsPublicationExchangeError(f"cannot exchange documentation roots: {error}") from error
