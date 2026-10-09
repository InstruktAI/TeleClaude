"""Mask the values this computer's environment files hold before text leaves the process that read it.

Output a command printed is reported elsewhere only after every value from the machine, global-home
and project environment files is replaced. A secret a command reads from anywhere else is not known
here and is not masked.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final

from teleclaude.config._environment import read_environment_file
from teleclaude.paths import PROJECT_ENV_PATH, TELECLAUDE_HOME, ConfigFileName

_MASK: Final = "***"
# Shorter values are flags and words ("1", "true"), whose masking would hide output without protecting anything.
_MIN_MASKED_LENGTH: Final = 6


def environment_files(project_root: Path) -> tuple[Path, ...]:
    """The environment files whose values a command run in ``project_root`` can reach."""
    return (PROJECT_ENV_PATH, TELECLAUDE_HOME / ConfigFileName.ENV, project_root / ConfigFileName.ENV)


def mask_environment_values(text: str, files: Iterable[Path]) -> str:
    """Replace every sufficiently long value held in ``files`` with a mask, longest first."""
    values = {
        value for path in files for value in read_environment_file(path).values() if len(value) >= _MIN_MASKED_LENGTH
    }
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, _MASK)
    return text
