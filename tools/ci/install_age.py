"""Install and verify the pinned age command-line tools for release setup."""

from __future__ import annotations

import argparse
import subprocess
from enum import StrEnum
from pathlib import Path

from tools.ci.gha import append_path, required_env

_DESCRIPTION = "Install and verify the release age tools."
_AGE_VERSION = "AGE_VERSION"
_GO_BINARY = "go"
_GO_PATH = "GOPATH"
_PACKAGE_TEMPLATE = "filippo.io/age/cmd/...@{version}"
_BIN_DIRECTORY = "bin"
_VERSION_OPTION = "--version"


class AgeExecutable(StrEnum):
    """The native age commands required by release authentication."""

    AGE = "age"
    KEYGEN = "age-keygen"


class GoCommand(StrEnum):
    """Go operations used to install and locate the age commands."""

    INSTALL = "install"
    ENV = "env"


def main(argv: list[str] | None = None) -> int:
    """Install both tools, verify they execute, then publish their directory to subsequent steps."""
    argparse.ArgumentParser(description=_DESCRIPTION).parse_args(argv)
    version = required_env(_AGE_VERSION)
    # Native Go package installation and tool version commands have no Python API.
    subprocess.run([_GO_BINARY, GoCommand.INSTALL, _PACKAGE_TEMPLATE.format(version=version)], check=True)
    # Go owns discovery of its configured installation directory.
    go_path = subprocess.run([_GO_BINARY, GoCommand.ENV, _GO_PATH], check=True, capture_output=True, text=True)
    bin_directory = Path(go_path.stdout.strip()) / _BIN_DIRECTORY
    for executable in AgeExecutable:
        # Each native CLI's version entrypoint verifies the installed executable.
        subprocess.run([str(bin_directory / executable), _VERSION_OPTION], check=True)
    append_path(str(bin_directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
