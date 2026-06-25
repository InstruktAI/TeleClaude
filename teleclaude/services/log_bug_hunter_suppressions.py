"""Per-project known-issue suppression ledger for the log bug hunter.

The log bug hunter scans each project's recent logs and dispatches a bug-hunter
session whenever a candidate error signal appears. A suppression ledger is a
per-project allowlist of signatures that have already been triaged and accepted
as expected or won't-fix, so the scan subtracts them before deciding to
dispatch.

The ledger is a single-writer-per-file document: the ``telec bugs suppress`` /
``unsuppress`` CLI owns all writes, the service only reads. This keeps it clear
of the service's per-run state rewrites, which would otherwise clobber
operator-authored entries.

Matching is pure allowlist — the code only tests a candidate line against the
authored pattern (literal substring or compiled regex) and never grades whether
a line is meaningful. Pattern authoring is intelligence work; the code only
matches what was authored.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TypedDict, cast

from teleclaude import paths

# A predicate testing whether a single candidate error line is suppressed.
Matcher = Callable[[str], bool]


class SuppressionLedgerError(Exception):
    """A persisted ledger exists but is unreadable, non-JSON, or malformed.

    Raised instead of silently substituting an empty ledger: the ledger is
    durable operator-authored memory, so a corrupt existing file must surface
    loudly rather than be discarded and overwritten on the next write.
    """


class MatchMode(StrEnum):
    """How a suppression pattern is tested against a candidate error line."""

    SUBSTRING = "substring"
    REGEX = "regex"


class Disposition(StrEnum):
    """Why a signal is suppressed; record-only, no effect on matching."""

    EXPECTED = "expected"
    WONTFIX = "wontfix"


class SuppressionDict(TypedDict):
    """Serialized form of a single suppression entry."""

    id: str
    pattern: str
    match: str
    disposition: str
    reason: str
    source_bug: str | None
    created_by: str | None
    created_at: str | None
    expires_at: str | None


class SuppressionLedgerDict(TypedDict):
    """Serialized form of the per-project suppression ledger."""

    version: int
    suppressions: list[SuppressionDict]


LEDGER_VERSION = 1


@dataclass
class Suppression:
    """A single triaged known-issue signature the scan treats as already filed."""

    id: str
    pattern: str
    match: MatchMode
    disposition: Disposition
    reason: str
    source_bug: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        # Normalize every timestamp to aware UTC at construction so expiry
        # comparisons never mix naive and aware datetimes. A date-only or naive
        # value entered at the CLI (`--expires 2026-12-31`) is interpreted as UTC
        # rather than raising a TypeError when compared against an aware `now`.
        self.created_at = _as_utc(self.created_at)
        self.expires_at = _as_utc(self.expires_at)

    def to_dict(self) -> SuppressionDict:
        """Serialize for JSON persistence."""
        return {
            "id": self.id,
            "pattern": self.pattern,
            "match": self.match.value,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "source_bug": self.source_bug,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: SuppressionDict) -> Suppression:
        """Deserialize one entry, raising :class:`SuppressionLedgerError` if malformed.

        A malformed entry (missing required field, unknown match/disposition,
        unparseable timestamp) fails loudly rather than being dropped: a silently
        discarded entry would be erased on the next write to the durable ledger.
        """
        try:
            match = MatchMode(data["match"])
            disposition = Disposition(data["disposition"])
            entry_id = data["id"]
            pattern = data["pattern"]
            reason = data["reason"]
        except (KeyError, ValueError) as exc:
            raise SuppressionLedgerError(f"malformed suppression entry: {exc}") from exc

        return cls(
            id=entry_id,
            pattern=pattern,
            match=match,
            disposition=disposition,
            reason=reason,
            source_bug=data.get("source_bug"),
            created_by=data.get("created_by"),
            created_at=_parse_dt(data.get("created_at")),
            expires_at=_parse_dt(data.get("expires_at")),
        )

    def is_active(self, now: datetime) -> bool:
        """Active when no expiry is set or the expiry is still in the future."""
        return self.expires_at is None or self.expires_at > now


@dataclass
class SuppressionLedger:
    """The per-project collection of suppressions."""

    version: int = LEDGER_VERSION
    suppressions: list[Suppression] = field(default_factory=list)

    def to_dict(self) -> SuppressionLedgerDict:
        """Serialize for JSON persistence."""
        return {
            "version": self.version,
            "suppressions": [entry.to_dict() for entry in self.suppressions],
        }

    @classmethod
    def from_dict(cls, data: SuppressionLedgerDict) -> SuppressionLedger:
        """Deserialize the ledger, raising on any malformed entry."""
        raw_entries = data.get("suppressions") or []
        entries = [Suppression.from_dict(raw) for raw in raw_entries]
        return cls(version=data.get("version", LEDGER_VERSION), suppressions=entries)


def _as_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` as an aware UTC datetime, treating a naive value as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse an optional ISO-8601 timestamp; a present-but-unparseable value is malformed."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SuppressionLedgerError(f"unparseable timestamp {raw!r}: {exc}") from exc


def _substring_matcher(pattern: str) -> Matcher:
    def matches(line: str) -> bool:
        return pattern in line

    return matches


def _regex_matcher(compiled: re.Pattern[str]) -> Matcher:
    def matches(line: str) -> bool:
        return compiled.search(line) is not None

    return matches


def suppressions_path_for(project_slug: str) -> Path:
    """Resolve the per-project ledger path — the single deterministic source.

    Both the service (reader) and the ``telec bugs`` CLI (writer) resolve the
    ledger through this one function, so they can never diverge on where a
    project's suppressions live. The derivation is total: there is no path that
    resolves to "suppressions silently disabled".
    """
    return paths.LOG_BUG_HUNTER_STATE_DIR / f"{project_slug}.suppressions.json"


def load(path: Path) -> SuppressionLedger:
    """Load the ledger. A missing file is an empty ledger; a corrupt one fails loudly.

    The ledger is durable operator-authored memory, so an existing file that is
    unreadable, not JSON, or structurally malformed raises
    :class:`SuppressionLedgerError` rather than being silently treated as empty —
    which a later ``append``/``remove`` would persist back, destroying the data.
    """
    if not path.exists():
        return SuppressionLedger()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuppressionLedgerError(f"unreadable suppression ledger at {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SuppressionLedgerError(f"suppression ledger at {path} is not a JSON object")
    return SuppressionLedger.from_dict(cast(SuppressionLedgerDict, raw))


def save(path: Path, ledger: SuppressionLedger) -> None:
    """Persist the ledger as pretty-printed JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger.to_dict(), indent=2), encoding="utf-8")


def append(path: Path, entry: Suppression) -> None:
    """Read-modify-write a new suppression into the ledger."""
    ledger = load(path)
    ledger.suppressions.append(entry)
    save(path, ledger)


def remove(path: Path, suppression_id: str) -> bool:
    """Remove the suppression with ``suppression_id``; return whether it existed."""
    ledger = load(path)
    remaining = [entry for entry in ledger.suppressions if entry.id != suppression_id]
    if len(remaining) == len(ledger.suppressions):
        return False
    ledger.suppressions = remaining
    save(path, ledger)
    return True


def active(ledger: SuppressionLedger, now: datetime) -> list[Suppression]:
    """Return the entries whose expiry is unset or still in the future."""
    return [entry for entry in ledger.suppressions if entry.is_active(now)]


def unsuppressed_lines(lines: Iterable[str], ledger: SuppressionLedger, now: datetime) -> list[str]:
    """Return the lines not matched by any active suppression.

    Each active entry is applied per its :class:`MatchMode`: a literal substring
    test or a compiled regex search. A regex entry that fails to compile is
    skipped — it suppresses nothing rather than crashing the scan.
    """
    matchers = _active_matchers(ledger, now)
    return [line for line in lines if not any(matches(line) for matches in matchers)]


def _active_matchers(ledger: SuppressionLedger, now: datetime) -> list[Matcher]:
    matchers: list[Matcher] = []
    for entry in active(ledger, now):
        if entry.match is MatchMode.SUBSTRING:
            matchers.append(_substring_matcher(entry.pattern))
            continue
        try:
            compiled = re.compile(entry.pattern)
        except re.error:
            continue
        matchers.append(_regex_matcher(compiled))
    return matchers
