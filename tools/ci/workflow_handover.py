"""Amendment A4 of the workflow acceptance: the owner\'s manual close of a holding driver, and the explicit release.

The assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/b2-b3-b4-close-hold-handover-amendment-rev2-draft.md`, approved at exact SHA-256
6871ce0dae59a98e6c24f3de945b3f2e2cb51c74daf847a2ee96820f8f522b21), which amends B2 step 12, B3 step 10 and B4 step 9
and cites every base: B2 95c7a8e7698bfc45737bb107508bc009e1f2c62520b78f5716b2061f29d6a9b4, B3
dd390a30129379b499339eb972d8f805ef30cd4893904b9b84498be5fdc953c4, B4
468714c024b576157001c2a1563b9cb32a1abb74dd0dc1969c8bb435ac2bde89, B4G
781033c73aab429302e5716df959c089b8e34ccbcb871212f93097ac1af02d2b and R3
8055cc9cf4741c32e655e52dea679087e7ded6fbe9c40f715debbf1c382c9ceb. B1 is unchanged.

Ending the session of the item\'s holding driver from the owner terminal makes the platform hold the item (the
manual-close hold of the session-lifecycle contract). The case reads a fresh public snapshot immediately before each
ending, confirms the end, the claim release and the unchanged phase, body, log and worktree, classifies the hold as the
expected one by all four audit fields before releasing any item, releases it through the public `telec todo update
--release`, and verifies the item is unheld with an empty audit, changed only where a release may change it. An
unrelated hold is never released: it is a binding failure, and the case retains its controls. No production change,
private observer or fixture capability is used.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_items as items
from tools.ci.workflow_creation import Observer, SessionView

TELEC: Final = "bin/telec"
TODO: Final = "todo"
UPDATE: Final = "update"
RELEASE_FLAG: Final = "--release"
SESSIONS: Final = "sessions"
SHOW: Final = "show"

STATE_HOLD: Final = "state.hold"
STATE_AUDIT: Final = "state.hold_audit"
PHASE_PATH: Final = "state.lifecycle_phase"
STANDING_PHASE_PATH: Final = "standing.phase"
INPUT_PATH: Final = "artifact_content.input"
HEADER_PREFIX: Final = "### "
SOURCE_CLOSE: Final = "session_close"
REASON_CLOSE: Final = "manual session close"
EMPTY_AUDIT: Final = {"source": "", "set_at": "", "set_by_session_id": "", "reason": ""}
RELEASE_ALLOWED: Final = (STATE_HOLD, STATE_AUDIT, items.ROADMAP_UPDATED_AT)
ABSENCE_SECONDS: Final = 30.0
POLL_SECONDS: Final = 2.0
SETTLE_SECONDS: Final = items.SETTLE_SECONDS

DETAIL_NOT_CLOSED: Final = "A4-1: the ended holder {session} of {item} is not closed: {record!r}"
DETAIL_STILL_HELD: Final = "A4-1: {item} still shows a holder or a held_by after the end: {found!r}"
DETAIL_NO_HOLD: Final = "A4-3: {item} is not held after its holder {session} was closed by the owner: {audit!r}"
DETAIL_UNRELATED: Final = "A4-3: {item} carries a hold that is not the close hold of {session}: {audit!r}"
DETAIL_INVARIANT: Final = "A4-2: {item} {what} is {found!r}, not {expected!r}"
DETAIL_WORKTREE: Final = "A4-2: the worktree {path} is no longer listed on {branch}: {listing!r}"
DETAIL_RELEASE: Final = (
    "A4-4: `telec todo update {item} --release` answered {output!r}, not an ok release with no warnings"
)
DETAIL_AFTER: Final = "A4-5: {item} {what} is {found!r}, not {expected!r}"
DETAIL_SESSION: Final = "A4-6: a session appeared after the release: {found!r}"
DETAIL_SESSION_LOG: Final = "A4-2: the log headers of {item} changed: {before!r} became {after!r}"

type Json = Mapping[str, object]


def log_headers(shown: Json) -> list[str]:
    """The section header lines of the item\'s log, in order."""
    _, log = creation.dig(shown, "artifact_content.log")
    return [line for line in str(log).replace("\r\n", "\n").split("\n") if line.startswith(HEADER_PREFIX)]


@dataclass
class Pending:
    """What was read immediately before one holder was ended."""

    item: str
    ended: str
    phase: str
    snapshot: Json
    headers: list[str]
    input_text: object
    worktree: str | None


@dataclass
class Handover:
    """The A4 procedure of one case: capture before each end, then classify, release and verify the point."""

    observer: Observer
    host: foundation.FoundationHost
    worktree: Callable[[], str | None] | None = None
    pending: dict[str, Pending] = field(default_factory=dict)
    unrelated: str = ""

    def before(self, item: str, ended: str, phase: str) -> None:
        """A fresh strict public snapshot of the item, immediately before its holder is ended."""
        snapshot = driver.fresh_snapshot(self.observer, item)
        found, input_text = creation.dig(snapshot, INPUT_PATH)
        self.pending[item] = Pending(
            item=item,
            ended=ended,
            phase=phase,
            snapshot=snapshot,
            headers=log_headers(snapshot),
            input_text=input_text if found else None,
            worktree=self.worktree() if self.worktree is not None else None,
        )

    def _closed(self, pending: Pending) -> None:
        outcome = self.observer.run((TELEC, SESSIONS, SHOW, pending.ended, foundation.FULL_FLAG), retain=False)
        record = foundation.json_object(outcome.output) if outcome.exit_status == 0 else None
        if (
            record is None
            or record.get(foundation.FIELD_CLOSED_AT) is None
            or record.get(foundation.FIELD_LIFECYCLE) != foundation.CLOSED
        ):
            raise creation.binding_failure(
                DETAIL_NOT_CLOSED.format(item=pending.item, session=pending.ended, record=record)
            )

    def _invariant(self, pending: Pending, shown: Json) -> None:
        item = pending.item
        for path, expected in ((PHASE_PATH, pending.phase), (STANDING_PHASE_PATH, pending.phase)):
            found, value = creation.dig(shown, path)
            if not found or value != expected:
                raise creation.platform_failure(
                    DETAIL_INVARIANT.format(item=item, what=path, found=value, expected=expected)
                )
        _, input_text = creation.dig(shown, INPUT_PATH)
        if input_text != pending.input_text:
            raise creation.platform_failure(
                DETAIL_INVARIANT.format(item=item, what=INPUT_PATH, found=input_text, expected=pending.input_text)
            )
        headers = log_headers(shown)
        if headers != pending.headers:
            raise creation.platform_failure(DETAIL_SESSION_LOG.format(item=item, before=pending.headers, after=headers))
        if self.worktree is not None:
            listing = self.worktree()
            if listing != pending.worktree:
                raise creation.platform_failure(
                    DETAIL_WORKTREE.format(path=pending.worktree, branch=item, listing=listing)
                )

    @staticmethod
    def _expected_hold(pending: Pending, shown: Json) -> str | None:
        """None when the hold is exactly the expected close hold; otherwise a word for what it is."""
        _, hold = creation.dig(shown, STATE_HOLD)
        _, audit = creation.dig(shown, STATE_AUDIT)
        if hold is not True:
            return "absent"
        if not isinstance(audit, Mapping):
            return "unrelated"
        set_at = audit.get("set_at")
        parsed = False
        if isinstance(set_at, str) and set_at:
            try:
                datetime.fromisoformat(set_at)
            except ValueError:
                parsed = False
            else:
                parsed = True
        expected = (
            audit.get("source") == SOURCE_CLOSE
            and audit.get("set_by_session_id") == pending.ended
            and audit.get("reason") == REASON_CLOSE
            and parsed
        )
        return None if expected else "unrelated"

    def after(self, items_ended: list[str]) -> None:
        """Run A4-1 to A4-6 for the items whose holders were just ended; classify all before releasing any."""
        creation.require_manual_runner(self.observer)
        views: dict[str, Json] = {}
        classes: dict[str, str | None] = {}
        for item in items_ended:
            pending = self.pending[item]
            self._closed(pending)
            shown = driver.fresh_snapshot(self.observer, item)
            found, runner = creation.dig(shown, "state.active_runner")
            _, standing = creation.dig(shown, "standing")
            if (
                not found
                or runner not in (None, creation.EMPTY)
                or (isinstance(standing, Mapping) and "held_by" in standing)
            ):
                raise creation.binding_failure(DETAIL_STILL_HELD.format(item=item, found=runner))
            self._invariant(pending, shown)
            views[item] = shown
            classes[item] = self._expected_hold(pending, shown)
        for item, kind in classes.items():
            _, audit = creation.dig(views[item], STATE_AUDIT)
            if kind == "absent":
                raise creation.platform_failure(
                    DETAIL_NO_HOLD.format(item=item, session=self.pending[item].ended, audit=audit)
                )
        unrelated = [item for item, kind in classes.items() if kind == "unrelated"]
        if unrelated:
            detail = "; ".join(
                DETAIL_UNRELATED.format(
                    item=item, session=self.pending[item].ended, audit=creation.dig(views[item], STATE_AUDIT)[1]
                )
                for item in unrelated
            )
            self.unrelated = detail
            raise creation.binding_failure(detail)
        for item in items_ended:
            self._release(self.pending[item], views[item])

    def _release(self, pending: Pending, held: Json) -> None:
        item = pending.item
        sessions_before = self.observer.sessions(retain=False)
        outcome = self.observer.run((TELEC, TODO, UPDATE, item, RELEASE_FLAG))
        answer = foundation.json_object(outcome.output)
        if (
            outcome.exit_status != 0
            or answer is None
            or answer.get("status") != "ok"
            or answer.get(items.FIELD_SLUG) != item
            or answer.get("hold") is not False
            or answer.get("warnings") != []
        ):
            raise creation.platform_failure(DETAIL_RELEASE.format(item=item, output=outcome.output[-300:]))
        shown = driver.shown_with_content(self.observer, item)
        creation.require_value(item, shown, STATE_HOLD, False)
        found, audit = creation.dig(shown, STATE_AUDIT)
        if not found or not isinstance(audit, Mapping) or dict(audit) != EMPTY_AUDIT:
            raise creation.platform_failure(
                DETAIL_AFTER.format(item=item, what=STATE_AUDIT, found=audit, expected=EMPTY_AUDIT)
            )
        items.require_only_changes("A4 release", held, shown, RELEASE_ALLOWED)
        self._invariant(pending, shown)
        time.sleep(SETTLE_SECONDS)
        later = driver.shown_with_content(self.observer, item)
        changed = creation.differences(shown, later)
        if changed:
            raise creation.platform_failure(
                items.DETAIL_WRITE.format(case="A4 release", when="five seconds later", paths=changed)
            )
        self._absence(sessions_before)

    def _absence(self, expected: SessionView) -> None:
        deadline = time.monotonic() + ABSENCE_SECONDS
        while time.monotonic() < deadline:
            now = self.observer.sessions(retain=False)
            if now.ids != expected.ids:
                raise creation.platform_failure(DETAIL_SESSION.format(found=sorted(now.ids - expected.ids)))
            time.sleep(POLL_SECONDS)

    def assert_start_unheld(self, item: str, what: str) -> None:
        """B4\'s restored start check: the previous case released, and nothing else holds the item."""
        shown = driver.shown_with_content(self.observer, item)
        _, hold = creation.dig(shown, STATE_HOLD)
        _, audit = creation.dig(shown, STATE_AUDIT)
        if hold is not False or not isinstance(audit, Mapping) or dict(audit) != EMPTY_AUDIT:
            raise creation.binding_failure(
                DETAIL_AFTER.format(
                    item=item, what=f"{what} (hold, audit)", found=(hold, audit), expected=(False, EMPTY_AUDIT)
                )
            )
