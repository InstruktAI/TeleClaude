"""The Creation Record: how a todo came into existence.

Four fields, stamped once at creation and immutable thereafter:
``lineage``, ``entry_point``, ``human_involved``, ``context``. See
``project/spec/domain/workflow`` for the full contract.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NamedTuple

_LINEAGE_SEPARATOR = ">"
_LINEAGE_SESSION_PREFIX = "session:"
_HUMAN_ROOT_PREFIX = "human:"
_SYSTEM_ROOT_PREFIX = "system:"


class EntryPoint(StrEnum):
    """The creation door — stamped by the door itself, never declared by the caller."""

    TUI = "tui"
    CLI = "cli"
    WEB = "web"
    AGENT = "agent"
    SPLIT = "split"


class Lineage(NamedTuple):
    """The creation chain: a chain-root authority plus an optional acting agent session.

    Encodes to ``<root>`` or ``<root>>session:<session_id>``. ``root`` is
    ``human:<email>`` for every human-rooted chain, or ``system:<session_id>``
    for a job-runner filing — the sole legitimate no-human root.
    """

    root: str
    acting_session: str | None = None

    def encode(self) -> str:
        """Render the chain to its single-value TEXT encoding."""
        if self.acting_session:
            return f"{self.root}{_LINEAGE_SEPARATOR}{_LINEAGE_SESSION_PREFIX}{self.acting_session}"
        return self.root

    @classmethod
    def parse(cls, value: str) -> Lineage:
        """Parse the TEXT encoding back into its root and optional acting session.

        A read path, tolerant of stored data — including empty or malformed
        legacy rows predating this column's introduction, whose backfill is a
        separate, deliberately deferred task. Never raises; use ``create`` to
        validate a chain being newly constructed instead of read back.
        """
        root, _, remainder = value.partition(_LINEAGE_SEPARATOR)
        acting_session = remainder.removeprefix(_LINEAGE_SESSION_PREFIX) if remainder else None
        return cls(root=root, acting_session=acting_session or None)

    @classmethod
    def root_of(cls, value: str | None) -> str | None:
        """Return the chain-root authority of a raw lineage value, or None."""
        if not value:
            return None
        return cls.parse(value).root

    @classmethod
    def create(cls, *, root: str, acting_session: str | None = None) -> Lineage:
        """Construct a new lineage, validating the root's shape.

        The write path for a chain being newly established at a creation door
        (never for reading a stored value back — see ``parse``). Rejects an
        empty root or one missing the ``human:``/``system:`` prefix, so a
        malformed chain can never be freshly persisted.
        """
        if not root or not (root.startswith(_HUMAN_ROOT_PREFIX) or root.startswith(_SYSTEM_ROOT_PREFIX)):
            raise ValueError(f"lineage root must be 'human:<email>' or 'system:<id>', got {root!r}")
        return cls(root=root, acting_session=acting_session or None)
