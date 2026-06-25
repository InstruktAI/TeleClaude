"""Functional bindings for the `telec bugs suppress` operator surface.

Drives the real CLI handlers, then proves the effect at the service boundary —
a registered suppression is honored by a fresh ``LogBugHunterService`` (a daemon
restart), and removing it makes the signal eligible again. Dispatch decisions and
typed/persisted fields are asserted; emitted prose is only ever snapshot-covered.

Covers @prd#sc-3 (register → persists → honored, default and non-default
match/disposition), @prd#sc-4 (active-only list; remove → eligible again),
@prd#sc-6 (a date-only `--expires` is honored, not crashed), the regex-validation
guard at write, and the durable-ledger fail-loud contract.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.handlers import bugs
from teleclaude.services import log_bug_hunter_suppressions as supp
from teleclaude.services.log_bug_hunter_service import LogBugHunterService
from teleclaude.types.commands import CreateSessionCommand

pytestmark = pytest.mark.functional

ServiceFactory = Callable[[str, str, list[CreateSessionCommand]], LogBugHunterService]

_SLUG = "cliproj"
_PATTERN = "reason=loop_lag"
_REASON = "deliberately tolerated"
_REGEX_PATTERN = r"loop_lag_\d+ms"
_LOOP_LAG_LINE = f"2026-06-25T10:00:00 ERROR HANG_DUMP {_PATTERN} took 1234ms"
_REGEX_ONLY_LINE = "2026-06-25T10:00:00 ERROR HANG_DUMP loop_lag_390ms over budget"


@pytest.fixture
def cli_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the CLI's cwd resolution at a tmp project so it resolves a real slug."""
    project_root = tmp_path / "cli-project"
    project_root.mkdir()
    (project_root / "teleclaude.yml").write_text(
        f"project_slug: {_SLUG}\nbusiness:\n  domains:\n    software-development: docs\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bugs, "resolve_invocation_cwd", lambda: project_root)
    return _SLUG


def _only_entry() -> supp.Suppression:
    ledger = supp.load(supp.suppressions_path_for(_SLUG))
    assert len(ledger.suppressions) == 1
    return ledger.suppressions[0]


async def test_register_persists_and_is_honored_after_restart(
    ledger_dir: Path, cli_project: str, make_service: ServiceFactory
) -> None:
    """@prd#sc-3 — a default substring/wontfix suppression is honored by a fresh service."""
    bugs._handle_bugs(["suppress", _PATTERN, "--reason", _REASON])

    created: list[CreateSessionCommand] = []
    service = make_service(_SLUG, _LOOP_LAG_LINE, created)
    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is False
    assert created == []


async def test_register_regex_expected_disposition_round_trips(
    ledger_dir: Path, cli_project: str, make_service: ServiceFactory
) -> None:
    """@prd#sc-3 — non-default --match regex --disposition expected persist and are honored.

    The pattern only matches under regex semantics (substring of `loop_lag_\\d+ms`
    is absent from the line), so a no-dispatch outcome proves the match mode was
    persisted as regex rather than silently downgraded to substring.
    """
    bugs._handle_bugs(
        ["suppress", _REGEX_PATTERN, "--reason", _REASON, "--match", "regex", "--disposition", "expected"]
    )

    entry = _only_entry()
    assert entry.match is supp.MatchMode.REGEX
    assert entry.disposition is supp.Disposition.EXPECTED

    created: list[CreateSessionCommand] = []
    service = make_service(_SLUG, _REGEX_ONLY_LINE, created)
    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is False
    assert created == []


async def test_unsuppress_makes_signal_eligible_again(
    ledger_dir: Path, cli_project: str, make_service: ServiceFactory
) -> None:
    """@prd#sc-4 — after removal the signal dispatches again."""
    bugs._handle_bugs(["suppress", _PATTERN, "--reason", _REASON])
    entry_id = _only_entry().id

    bugs._handle_bugs(["unsuppress", entry_id])

    created: list[CreateSessionCommand] = []
    service = make_service(_SLUG, _LOOP_LAG_LINE, created)
    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is True
    assert len(created) == 1


def test_suppressions_lists_only_active_entries(
    ledger_dir: Path, cli_project: str, capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    """@prd#sc-4 — the operator list shows active entries and omits expired ones.

    A regression that printed the raw ledger would surface the expired entry's id
    and pattern in the snapshot.
    """
    active_entry = supp.Suppression(
        id="aaaaaaaaaaaa",
        pattern=_PATTERN,
        match=supp.MatchMode.SUBSTRING,
        disposition=supp.Disposition.WONTFIX,
        reason=_REASON,
        expires_at=None,
    )
    expired_entry = supp.Suppression(
        id="bbbbbbbbbbbb",
        pattern="reason=expired_signal",
        match=supp.MatchMode.SUBSTRING,
        disposition=supp.Disposition.WONTFIX,
        reason="lapsed tolerance",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    supp.save(supp.suppressions_path_for(_SLUG), supp.SuppressionLedger(suppressions=[active_entry, expired_entry]))

    bugs._handle_bugs(["suppressions"])

    assert capsys.readouterr().out == snapshot


async def test_date_only_expires_is_honored_without_crashing(
    ledger_dir: Path, cli_project: str, make_service: ServiceFactory
) -> None:
    """@prd#sc-6 — a date-only --expires is normalized to aware UTC and applied, not crashed.

    Before normalization the naive expiry raised TypeError against an aware `now`.
    """
    future = (datetime.now(UTC) + timedelta(days=365)).date().isoformat()
    bugs._handle_bugs(["suppress", _PATTERN, "--reason", _REASON, "--expires", future])

    created: list[CreateSessionCommand] = []
    service = make_service(_SLUG, _LOOP_LAG_LINE, created)
    dispatched = await service.maybe_dispatch(now=datetime.now(UTC))

    assert dispatched is False
    assert created == []


def test_invalid_regex_pattern_is_rejected_and_persists_nothing(ledger_dir: Path, cli_project: str) -> None:
    """A --match regex pattern that does not compile exits non-zero, writing no ledger."""
    with pytest.raises(SystemExit) as excinfo:
        bugs._handle_bugs(["suppress", "(unterminated", "--reason", "x", "--match", "regex"])

    assert excinfo.value.code == 1
    assert supp.load(supp.suppressions_path_for(_SLUG)).suppressions == []


def test_unsuppress_unknown_id_exits_nonzero(ledger_dir: Path, cli_project: str) -> None:
    """Removing an id that does not exist is a non-zero error, not a silent no-op."""
    with pytest.raises(SystemExit) as excinfo:
        bugs._handle_bugs(["unsuppress", "deadbeef"])

    assert excinfo.value.code == 1


def test_corrupt_ledger_fails_loud_and_is_not_overwritten(ledger_dir: Path, cli_project: str) -> None:
    """A corrupt existing ledger fails loudly; a subsequent write does not destroy it."""
    path = supp.suppressions_path_for(_SLUG)
    path.parent.mkdir(parents=True, exist_ok=True)
    corrupt = "{ not valid json"
    path.write_text(corrupt, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        bugs._handle_bugs(["suppress", _PATTERN, "--reason", _REASON])

    assert excinfo.value.code == 1
    assert path.read_text(encoding="utf-8") == corrupt
