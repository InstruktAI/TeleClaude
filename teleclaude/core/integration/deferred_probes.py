"""Owed-probes for the on-demand maintenance actions that reload a running process.

A probe answers one question for an action an on-demand run never performs: is a
running process older than the converged tip in a way that owes the action? It prints
one line per process that owes it, prints nothing when none does, and exits non-zero
(naming the reason on stderr) when it cannot tell for at least one process.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import load_committed_checkpoint_model, triggered_action_ids
from teleclaude.cli.tui.processes import live_tui_start_commits
from teleclaude.git import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = get_logger(__name__)

_GIT_NAME_ONLY_ARGUMENT = "--name-only"
_PROBE_ARGUMENT = "probe"
_TIP_FLAG = "--tip"
_PROBE_FINISHED_EVENT = "deferred_probe_finished"
_TUI_LABEL = "the telec TUI (pid {pid})"
_OWED_LINE = "{process} started from {start}, and the changes up to {tip} owe {action}"
_PROBE_UNREACHABLE = "its probe could not run: {error}"
_START_UNKNOWN = "{process} recorded no start commit."
_START_UNRELATED = "{process} started from {start}, which is neither behind nor ahead of {tip}."
_START_UNREADABLE = "{process} started from {start}, which git cannot read: {error}"
_SHORT_COMMIT_LENGTH = 12
_OWED_EXIT_CODE = 0
_UNDECIDABLE_EXIT_CODE = 1
_GIT_FAILURES = (GitCommandError, BadName, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)


class DeferredProbe(StrEnum):
    """The deferred maintenance actions this module answers for, by action id."""

    TUI_RELOAD = "tui-reload"


class StartRelation(StrEnum):
    """How a process's start commit stands to the converged tip."""

    CONTAINS_TIP = "contains_tip"
    BEHIND_TIP = "behind_tip"
    UNRELATED = "unrelated"


@dataclass(frozen=True)
class RunningProcess:
    """A running process and the commit it started from, when that is known."""

    label: str
    start_commit: str | None


@dataclass(frozen=True)
class ProbeReport:
    """What a probe found: the processes that owe the action, and why it could not tell for others."""

    owed: tuple[str, ...]
    undecidable: tuple[str, ...]


def read_tui_processes() -> tuple[RunningProcess, ...]:
    """Read each live TUI's recorded start commit."""
    return tuple(
        RunningProcess(label=_TUI_LABEL.format(pid=pid), start_commit=commit)
        for pid, commit in live_tui_start_commits()
    )


def relate_start_to_tip(repository: Repo, start_commit: str, tip: str) -> StartRelation:
    """Classify a start commit against the tip by ancestry."""
    if repository.is_ancestor(repository.commit(tip), repository.commit(start_commit)):
        return StartRelation.CONTAINS_TIP
    if repository.is_ancestor(repository.commit(start_commit), repository.commit(tip)):
        return StartRelation.BEHIND_TIP
    return StartRelation.UNRELATED


def judge_processes(root: Path, probe: DeferredProbe, processes: Sequence[RunningProcess], tip: str) -> ProbeReport:
    """Report which processes owe ``probe``'s action at ``tip``, and for which none can be told."""
    repository = Repo(str(root))
    model = load_committed_checkpoint_model(root, tip)
    owed: list[str] = []
    undecidable: list[str] = []
    for process in processes:
        if process.start_commit is None:
            undecidable.append(_START_UNKNOWN.format(process=process.label))
            continue
        try:
            relation = relate_start_to_tip(repository, process.start_commit, tip)
            if relation is StartRelation.CONTAINS_TIP:
                continue
            if relation is StartRelation.UNRELATED:
                undecidable.append(
                    _START_UNRELATED.format(
                        process=process.label,
                        start=process.start_commit[:_SHORT_COMMIT_LENGTH],
                        tip=tip[:_SHORT_COMMIT_LENGTH],
                    )
                )
                continue
            changed = repository.git.diff(_GIT_NAME_ONLY_ARGUMENT, process.start_commit, tip).splitlines()
        except _GIT_FAILURES as exc:
            undecidable.append(
                _START_UNREADABLE.format(
                    process=process.label, start=process.start_commit[:_SHORT_COMMIT_LENGTH], error=exc
                )
            )
            continue
        # The probed action alone decides: another action's binding matching the same paths owes nothing here.
        if probe.value in triggered_action_ids(changed, model):
            owed.append(
                _OWED_LINE.format(
                    process=process.label,
                    start=process.start_commit[:_SHORT_COMMIT_LENGTH],
                    tip=tip[:_SHORT_COMMIT_LENGTH],
                    action=probe.value,
                )
            )
    return ProbeReport(owed=tuple(owed), undecidable=tuple(undecidable))


def run_probe(root: Path, probe: DeferredProbe, tip: str) -> int:
    """Print the probe's findings and return its exit status."""
    try:
        processes = read_tui_processes()
    except OSError as exc:
        report = ProbeReport(owed=(), undecidable=(_PROBE_UNREACHABLE.format(error=exc),))
    else:
        report = judge_processes(root, probe, processes, tip)
    for line in report.owed:
        print(line)
    for line in report.undecidable:
        print(line, file=sys.stderr)
    exit_code = _UNDECIDABLE_EXIT_CODE if report.undecidable else _OWED_EXIT_CODE
    logger.info(
        _PROBE_FINISHED_EVENT,
        probe=probe.value,
        tip=tip,
        owed_count=len(report.owed),
        undecidable_count=len(report.undecidable),
    )
    return exit_code


def main() -> int:
    """Run one probe for the command line's working root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_PROBE_ARGUMENT, type=DeferredProbe)
    parser.add_argument(_TIP_FLAG, required=True)
    args = parser.parse_args()
    return run_probe(Path.cwd().resolve(), args.probe, args.tip)


if __name__ == "__main__":
    raise SystemExit(main())
