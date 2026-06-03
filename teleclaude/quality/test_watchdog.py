"""Per-worker in-flight test tracker and master-process hang watchdog.

This module implements rules 14-15 of
``software-development/policy/test-resource-discipline``:

- Every pytest worker writes its currently-running test's nodeid and monotonic
  start time to a tmpfs file in ``pytest_runtest_setup`` and clears it in
  ``pytest_runtest_teardown``.
- The master process (the one spawned by ``telec code test``) polls those files
  every ``DEFAULT_POLL_INTERVAL_S`` seconds. Any worker whose current test has
  exceeded ``2 x tier budget`` is logged with its nodeid and SIGKILLed.

The watchdog sits in the master process — not inside any xdist worker — so it
can name a hang even when the worker is wedged at a syscall the per-test pytest
signal can't reach. That is the load-bearing piece of the "every hang is named"
guarantee.

The conftest-side helpers and the master-side poller share the path format and
parser through this module so the two halves cannot drift.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_FILE_PREFIX = "teleclaude_pytest_worker_"
_FILE_SUFFIX = ".json"

# Tier identity constants — also used by tests in lieu of string literals.
TIER_UNIT = "unit"
TIER_FUNCTIONAL = "functional"
TIER_INTEGRATION = "integration"

# Tier budgets in seconds. Mirrors the per-marker timeouts assigned in
# tests/conftest.py:pytest_collection_modifyitems. Hard-coded here so the
# watchdog has no dependency on pytest at runtime.
TIER_BUDGETS_S: dict[str, float] = {
    TIER_UNIT: 1.0,
    TIER_FUNCTIONAL: 5.0,
    TIER_INTEGRATION: 5.0,
}
_DEFAULT_TIER = TIER_FUNCTIONAL  # fallback if path doesn't match any known tier

# Multiplier applied to the tier budget before the watchdog kills.
# Per-test pytest-timeout fires at 1.0 x budget; the watchdog gives one more
# budget interval of grace for cleanup before SIGKILL.
WATCHDOG_MULTIPLIER = 2.0

DEFAULT_POLL_INTERVAL_S = 0.5


@dataclass(frozen=True)
class InflightRecord:
    """A single worker's currently-running test."""

    worker_pid: int
    nodeid: str
    started_monotonic: float

    @property
    def tier(self) -> str:
        """Tier inferred from the test path prefix in ``nodeid``."""
        return tier_for_nodeid(self.nodeid)

    @property
    def budget_s(self) -> float:
        return TIER_BUDGETS_S.get(self.tier, TIER_BUDGETS_S[_DEFAULT_TIER])

    @property
    def kill_threshold_s(self) -> float:
        return self.budget_s * WATCHDOG_MULTIPLIER


_TIER_PATH_PREFIXES = (
    ("tests/unit/", TIER_UNIT),
    ("tests/functional/", TIER_FUNCTIONAL),
    ("tests/integration/", TIER_INTEGRATION),
)


def tier_for_nodeid(nodeid: str) -> str:
    """Infer the tier from the nodeid path prefix.

    Returns one of ``TIER_UNIT`` / ``TIER_FUNCTIONAL`` / ``TIER_INTEGRATION``,
    falling back to ``_DEFAULT_TIER`` for paths that don't match a known tier.
    """
    norm = nodeid.lstrip("./").replace("\\", "/")
    for prefix, tier in _TIER_PATH_PREFIXES:
        if norm.startswith(prefix):
            return tier
    return _DEFAULT_TIER


def _tmp_dir() -> Path:
    """Resolve the directory where worker files live.

    Honors ``$TMPDIR`` so macOS / Linux behave consistently; falls back to the
    platform default.
    """
    env = os.environ.get("TMPDIR")
    if env:
        return Path(env)
    return Path(tempfile.gettempdir())


def inflight_path(worker_pid: int) -> Path:
    """Path to the worker file for ``worker_pid``. Single source of truth."""
    return _tmp_dir() / f"{_FILE_PREFIX}{worker_pid}{_FILE_SUFFIX}"


def write_inflight(nodeid: str, started_monotonic: float, *, worker_pid: int | None = None) -> None:
    """Atomically record the currently-running test for this worker.

    Called from ``pytest_runtest_setup``. Atomic via write-tmp-then-rename so
    the master watchdog never reads a half-written file.
    """
    pid = worker_pid if worker_pid is not None else os.getpid()
    target = inflight_path(pid)
    tmp = target.with_suffix(_FILE_SUFFIX + ".tmp")
    record = {
        "worker_pid": pid,
        "nodeid": nodeid,
        "started_monotonic": started_monotonic,
    }
    try:
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        # tmpfs unavailable / permission issue — don't fail the test over diagnostics.
        pass


def clear_inflight(*, worker_pid: int | None = None) -> None:
    """Clear the worker's in-flight record. Called from ``pytest_runtest_teardown``."""
    pid = worker_pid if worker_pid is not None else os.getpid()
    target = inflight_path(pid)
    try:
        target.unlink()
    except (FileNotFoundError, OSError):
        pass


def read_all_inflight(*, since_monotonic: float | None = None) -> list[InflightRecord]:
    """Read every worker file currently on disk.

    ``since_monotonic`` is informational only; the records carry their own
    ``started_monotonic``. Returned list is unsorted.
    """
    out: list[InflightRecord] = []
    for path in _tmp_dir().glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}"):
        if path.suffix == ".tmp":
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            out.append(
                InflightRecord(
                    worker_pid=int(data["worker_pid"]),
                    nodeid=str(data["nodeid"]),
                    started_monotonic=float(data["started_monotonic"]),
                )
            )
        except (OSError, ValueError, KeyError):
            continue
    return out


def cleanup_inflight_files(*, since_monotonic: float | None = None) -> int:
    """Remove every leftover worker file. Called from the master ``finally`` block.

    ``since_monotonic`` is currently unused (kept for symmetry with the read API);
    cleanup is unconditional because each ``telec code test`` invocation owns the
    tmpfs lifecycle.
    """
    removed = 0
    for path in _tmp_dir().glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}*"):
        try:
            path.unlink()
            removed += 1
        except (FileNotFoundError, OSError):
            continue
    return removed


# ---------------------------------------------------------------------------
# Master-process watchdog


@dataclass(frozen=True)
class KillDecision:
    """Outcome of evaluating a single in-flight record against the watchdog threshold."""

    record: InflightRecord
    elapsed_s: float
    should_kill: bool


def evaluate(
    records: Iterable[InflightRecord],
    *,
    now_monotonic: float,
) -> list[KillDecision]:
    """Pure decision function — testable without a real clock or process."""
    out: list[KillDecision] = []
    for rec in records:
        elapsed = now_monotonic - rec.started_monotonic
        out.append(
            KillDecision(
                record=rec,
                elapsed_s=elapsed,
                should_kill=elapsed >= rec.kill_threshold_s,
            )
        )
    return out


class WatchdogPoller:
    """Polls in-flight files and SIGKILLs workers whose current test exceeds 2x tier budget.

    Runs in the master process (the one spawned by ``telec code test``). The
    pytest process is the child; xdist workers are grandchildren. SIGKILL is
    issued directly by PID. The poller does not own the pytest process lifetime
    — the caller starts pytest and uses ``poll_until_exit`` to gate completion.
    """

    def __init__(
        self,
        *,
        pytest_proc_poll: Callable[[], int | None],
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        read_inflight: Callable[[], list[InflightRecord]] = read_all_inflight,
        killer: Callable[[int, int], None] = os.kill,
        log: logging.Logger | None = None,
    ) -> None:
        self._pytest_proc_poll = pytest_proc_poll
        self._poll_interval_s = poll_interval_s
        self._clock = clock
        self._sleep = sleep
        self._read_inflight = read_inflight
        self._killer = killer
        self._log = log or logger
        self._already_killed: set[int] = set()

    def tick(self) -> list[KillDecision]:
        """Single-pass: read inflight files, decide, kill stuck workers. Returns the decisions made."""
        records = self._read_inflight()
        decisions = evaluate(records, now_monotonic=self._clock())
        for decision in decisions:
            if not decision.should_kill:
                continue
            pid = decision.record.worker_pid
            if pid in self._already_killed:
                continue
            self._log.error(
                "WATCHDOG: worker pid=%d stuck on %s for %.1fs (budget=%.1fs, tier=%s) — SIGKILLing",
                pid,
                decision.record.nodeid,
                decision.elapsed_s,
                decision.record.budget_s,
                decision.record.tier,
            )
            try:
                self._killer(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError) as exc:
                self._log.warning("WATCHDOG: kill of pid=%d failed: %s", pid, exc)
            self._already_killed.add(pid)
        return decisions

    def poll_until_exit(self) -> int:
        """Drive ``tick()`` on the interval until the pytest process exits. Returns its exit code."""
        while True:
            exit_code = self._pytest_proc_poll()
            if exit_code is not None:
                return exit_code
            self.tick()
            self._sleep(self._poll_interval_s)
