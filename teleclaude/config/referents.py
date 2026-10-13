"""The things a declaration or request names, and the one refusal for a name this computer has not registered.

A referent is a company, a person, a project, or a documentation domain
referred to by slug. Whether it resolves is a fact about one computer: what that
computer has registered. This module is the leaf both the registry owner and the
configuration loader share, so it imports neither: it holds the closed kind
vocabulary, the refusal, and the only wording of each kind's registration surface.
"""

from __future__ import annotations

from enum import StrEnum

from teleclaude.config.machine import config as machine_config


class ReferentKind(StrEnum):
    """What a reference can name."""

    COMPANY = "company"
    PERSON = "person"
    PROJECT = "project"
    DOMAIN = "documentation domain"


_REGISTRATION_SURFACE: dict[ReferentKind, str] = {
    ReferentKind.COMPANY: "run `telec config company init <name> --slug {slug}`",
    ReferentKind.PERSON: "run `telec config person init <name> --email <email> --slug {slug}`",
    ReferentKind.PROJECT: "run `telec config project adopt` in the folder of the project declaring `{slug}`",
    ReferentKind.DOMAIN: (
        "run `telec config project adopt` in the checkout of the project that publishes `{slug}`,"
        " then run `telec sync` there"
    ),
}
_REFUSAL = "No {kind} `{slug}` is registered on computer `{computer}`. To register it there, {surface}."


class UnregisteredReferentError(ValueError):
    """A well-formed reference names a referent the answering computer has not registered.

    The message is the whole answer: it names the kind and slug, the computer that
    answered, and that kind's registration surface there. It never calls the
    reference malformed.
    """

    def __init__(self, kind: ReferentKind, slug: str, computer: str) -> None:
        super().__init__(kind, slug, computer)
        self.kind = kind
        self.slug = slug
        self.computer = computer

    def __str__(self) -> str:
        return _REFUSAL.format(
            kind=self.kind.value,
            slug=self.slug,
            computer=self.computer,
            surface=_REGISTRATION_SURFACE[self.kind].format(slug=self.slug),
        )


def unregistered_referent(kind: ReferentKind, slug: str) -> UnregisteredReferentError:
    """The refusal for ``slug`` as answered by this computer."""
    return UnregisteredReferentError(kind, slug, machine_config.computer.name)
