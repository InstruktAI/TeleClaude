"""Install the native libraries the release candidate's modules load at import."""

from __future__ import annotations

import argparse
import subprocess
from enum import StrEnum

_DESCRIPTION = "Install the native libraries the release candidate's modules load."
_SUDO_BINARY = "sudo"
_NON_INTERACTIVE = "-n"
_APT_BINARY = "apt-get"
_ASSUME_YES = "-y"
_QUIET = "-qq"
# PortAudio shared library that sounddevice discovers on Linux when the chiptunes modules import.
# Pinned to the build published for Ubuntu 26.04, whose release pocket is immutable.
_PORTAUDIO_PACKAGE = "libportaudio2=19.7.0+git20260206.e1b70d33-0ubuntu1"


class AptCommand(StrEnum):
    """The apt-get operations used to establish the native prerequisites."""

    UPDATE = "update"
    INSTALL = "install"


def _apt(*arguments: str) -> None:
    # Native package installation has no Python API.
    subprocess.run([_SUDO_BINARY, _NON_INTERACTIVE, _APT_BINARY, *arguments], check=True)


def main(argv: list[str] | None = None) -> int:
    """Refresh the package index, then install the pinned native library."""
    argparse.ArgumentParser(description=_DESCRIPTION).parse_args(argv)
    _apt(AptCommand.UPDATE, _QUIET)
    _apt(AptCommand.INSTALL, _ASSUME_YES, _QUIET, _PORTAUDIO_PACKAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
