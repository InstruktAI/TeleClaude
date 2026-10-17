"""Typed failures returned by mirror identity resolution."""

_AMBIGUOUS_HISTORY_IDENTIFIER = "Ambiguous history identifier: multiple reachable conversations match."


class MirrorIdentityAmbiguityError(ValueError):
    """A source identifier addresses more than one conversation within the caller's reach."""

    def __init__(self) -> None:
        super().__init__(_AMBIGUOUS_HISTORY_IDENTIFIER)
