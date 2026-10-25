"""The compatibility series a stable installation follows: a minor line before 1.0, a major line from 1.0 onward."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

_SEPARATOR: Final = "."
_MAJOR_ONLY_PARTS: Final = 1
_MAJOR_AND_MINOR_PARTS: Final = 2
_PRE_RELEASE_MAJOR: Final = 0
_INVALID_SERIES_ERROR: Final = (
    "deployment.compatibility_series {value!r} is not a compatibility series; "
    "write the minor line as a quoted `0.<minor>` before 1.0, or the major line as `<major>` from 1.0 onward"
)
_FLOAT_SERIES_ERROR: Final = (
    "deployment.compatibility_series {value!r} is ambiguous as an unquoted number; quote the series, for example '0.10'"
)
_INVARIANT_ERROR: Final = "a compatibility series carries a minor exactly when its major is zero"


@dataclass(frozen=True)
class CompatibilitySeries:
    """A selected update boundary: ``0.<minor>`` while the major is zero, ``<major>`` once it is positive."""

    major: int
    minor: int | None = None

    def __post_init__(self) -> None:
        if (self.major == _PRE_RELEASE_MAJOR) != (self.minor is not None):
            raise ValueError(_INVARIANT_ERROR)

    @classmethod
    def parse(cls, value: object) -> CompatibilitySeries:
        """Read a series from its operator spelling, naming the value when it is not one.

        A positive major written with a minor, as a minor pin is written, names that major's line.
        """
        if isinstance(value, float):
            raise ValueError(_FLOAT_SERIES_ERROR.format(value=value))
        text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
        numbers = _numbers(text) if isinstance(text, str) else None
        if numbers is None:
            raise ValueError(_INVALID_SERIES_ERROR.format(value=value))
        major = numbers[0]
        return cls(major=major, minor=numbers[1] if major == _PRE_RELEASE_MAJOR else None)

    @classmethod
    def of_version(cls, version: tuple[int, int, int]) -> CompatibilitySeries:
        """The series a release version belongs to: its minor line while the major is zero, its major line from 1.0."""
        major, minor, _patch = version
        return cls(major=major, minor=minor if major == _PRE_RELEASE_MAJOR else None)

    def admits(self, version: tuple[int, int, int]) -> bool:
        """Whether a release version lies inside this series."""
        return version[0] == self.major and (self.minor is None or version[1] == self.minor)

    def __str__(self) -> str:
        return str(self.major) if self.minor is None else _SEPARATOR.join((str(self.major), str(self.minor)))


def _numbers(text: str) -> tuple[int, ...] | None:
    """The canonical decimal parts of a series spelling, or None when the text is not one.

    A pre-1.0 spelling must name its minor; a positive major may be written alone or with a minor.
    """
    parts = text.split(_SEPARATOR)
    if len(parts) not in (_MAJOR_ONLY_PARTS, _MAJOR_AND_MINOR_PARTS):
        return None
    if not all(part.isascii() and part.isdigit() and part == str(int(part)) for part in parts):
        return None
    numbers = tuple(int(part) for part in parts)
    if numbers[0] == _PRE_RELEASE_MAJOR and len(numbers) != _MAJOR_AND_MINOR_PARTS:
        return None
    return numbers
