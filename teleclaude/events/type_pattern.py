"""Type patterns: the one matcher that selects platform event types.

A pattern is an exact type name, whole name segments followed by the segment
wildcard (every type below that prefix), or the bare wildcard (every type). A
`TypePattern` can only exist parsed, so a malformed pattern is refused where it
is declared and every context that selects events by type matches the same way.
"""

from __future__ import annotations

from dataclasses import dataclass

_SEGMENT_SEPARATOR = "."
_WILDCARD = "*"
_PREFIX_SUFFIX = _SEGMENT_SEPARATOR + _WILDCARD
_MALFORMED_PATTERN_ERROR = (
    "malformed event type pattern {pattern!r}: use an exact type name, whole name segments followed by '.*', or '*'"
)


class TypePatternError(ValueError):
    """A string declared as a type pattern is not an exact name, a segment prefix with `.*`, or `*`."""


def _is_name(text: str) -> bool:
    """Whether the text is dot-separated, non-empty segments with no wildcard."""
    return all(segment and _WILDCARD not in segment for segment in text.split(_SEGMENT_SEPARATOR))


@dataclass(frozen=True)
class TypePattern:
    """A parsed type pattern; construction refuses any malformed text."""

    text: str

    def __post_init__(self) -> None:
        if self.text == _WILDCARD:
            return
        name = self.text.removesuffix(_PREFIX_SUFFIX)
        if not _is_name(name):
            raise TypePatternError(_MALFORMED_PATTERN_ERROR.format(pattern=self.text))

    @classmethod
    def below(cls, prefix: str) -> TypePattern:
        """The pattern selecting every type below a name prefix, such as every state of a lifecycle family."""
        return cls(prefix + _PREFIX_SUFFIX)

    def matches(self, event_type: str) -> bool:
        """Whether an event type name is selected by this pattern, at whole-segment boundaries."""
        if self.text == _WILDCARD:
            return True
        if self.text.endswith(_PREFIX_SUFFIX):
            prefix = self.text.removesuffix(_WILDCARD)
            return event_type.startswith(prefix) and len(event_type) > len(prefix)
        return event_type == self.text

    def __str__(self) -> str:
        return self.text


#: The pattern that selects every event type.
ANY_TYPE = TypePattern(_WILDCARD)
