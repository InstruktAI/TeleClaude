"""CLI handlers for ``telec app``: operate the machine's installation from any directory.

The edge only translates: each verb addresses the installation under the XDG data directory, and the
behavior lives in reconciliation (install, rollback, status) and the daemon lifecycle (start, stop,
restart, health). A project checkout the caller stands in is neither run nor changed
(``local/projects/teleclaude/spec/feature/reconciliation/installed-releases``).
"""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import NoReturn

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.cli.telec.handlers._arg_parsing import CliUsageError, parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    APP_ASSESSED,
    APP_INSTALL,
    APP_RESTART,
    APP_ROLLBACK,
    APP_START,
    APP_STATUS,
    APP_STOP,
)
from teleclaude.cli.telec.surface_types import CommandDef, TelecCommand
from teleclaude.config._models import ReleaseChannel
from teleclaude.config.machine import config
from teleclaude.core.reconciliation.channel_target import (
    ChannelTargetError,
    active_release_version,
    channel_target,
    release_tag_of,
    source_full_name,
)
from teleclaude.core.reconciliation.convergence_decision import ConvergenceRecord, read_convergence
from teleclaude.core.reconciliation.install_act import (
    InstallRequest,
    InstallResult,
    InstallStatus,
    install,
    rollback,
)
from teleclaude.core.reconciliation.installation import InstallAct, InstallationLayout, InstallRecord, read_record
from teleclaude.core.reconciliation.installation_assessment import (
    AssessmentRecord,
    NothingOwed,
    OwedInstall,
    read_assessment,
    serving_active_release,
    update_assessment,
)
from teleclaude.core.reconciliation.installation_ports import LiveInstallPorts
from teleclaude.core.reconciliation.installation_release import ReleasePreparationError
from teleclaude.deployment.release_checkout import release_tag
from teleclaude.deployment.self_update import is_superseded
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = get_logger(__name__)

__all__ = ["handle_app"]

_LIFECYCLE_SCRIPT = Path("bin") / "daemon-control.sh"
_LIFECYCLE_EVENT = "telec_app_lifecycle"
_ACT_EVENT = "telec_app_act"
_ASSESSED_EVENT = "telec_app_assessed"
_NO_ACTIVE_RELEASE = "No release is active: the platform is not installed here. Install it with the bootstrap first."
_NO_KEPT_REPOSITORY = (
    "The installation keeps no repository yet, so it has nothing to install from. Run the bootstrap first."
)
_TOO_MANY_OPERANDS = "telec app install takes at most one revision."
_NO_OPERANDS = "telec app {verb} takes no operands."
_FAILED_STOPPED = (
    "The daemon is stopped: neither release is known to serve the partly migrated state. "
    "Repair forward, then run `telec app install` again."
)
_STATUS_ACTIVE = "Active release:   {revision}{tag}"
_STATUS_INSTALLATION = "Installation:     {root}"
_STATUS_LOCATION = "Active location:  {path}"
_STATUS_TAG = " ({tag})"
_STATUS_NO_ACTIVE = "Active release:   none"
_STATUS_PREVIOUS = "Previous release: {revision}"
_STATUS_MIGRATED = "Migrations started since activation: {stores}"
_STATUS_UNKNOWN_MIGRATED = "a start that could not be attributed to a store"
_STATUS_INSTALLING = "Install window:    target {target}, migrations started: {stores}"
_PUBLICATION_OWED = (
    "The release is active, but publishing its documentation, agent artifacts and schemas, or converging "
    "project plumbing, did not complete: "
    "{failure}\nRun `telec app install` again to replay it."
)
_STATUS_PUBLICATION = "Post-install owed: {revision}{failure}"
_STATUS_LAST_ACT = "Last act:          {act} {outcome} {revision} at {at}"
_STATUS_REASON = "  reason: {reason}"
_STATUS_OWED = "Assessment owed:  since {since}"
_STATUS_LAST_ASSESSMENT = "Last assessment:  at {at}"
_STATUS_CHANNEL = "Channel:          {channel}"
_STATUS_SOURCE = "Source:           {source}"
_STATUS_NO_SOURCE = "none (the installation follows no GitHub repository)"
_STATUS_NO_DECISION = "Last decision:    no convergence decision has been made yet"
_STATUS_DECISION = "Last decision:    {outcome} at {at}"
_STATUS_HELD = "Held release:     {tag} of {source}, beyond the active release's compatibility series, held since {at}"
_STATUS_CONVERGENCE_UNREADABLE = "Last decision:    the convergence record could not be read: {error}"
_ASSESSED_OPERAND = "telec app assessed takes the number of one install, as its owed-assessment announcement names it."
_ASSESSED_NOT_SERVING = (
    "The daemon does not serve the active release: {reason}. Restore service with `telec app start`, or repair "
    "forward when `telec app status` reports the daemon left stopped, then assess."
)
_ASSESSED_NOTHING_OWED = "No owed install carries number {number}."
_ASSESSED_OWED_HEADER = "Owed installs:"
_ASSESSED_OWED_ENTRY = "  install {number}, release {revision}"
_ASSESSED_NONE_OWED = "No install is owed an assessment."
_ASSESSED_REPORT = "Assessed install {number}, release {revision}."
_ASSESSED_STILL_OWED = "Still owed: {numbers}"
_LINE_SEPARATOR = "\n"
_NUMBER_SEPARATOR = ", "
_STORE_SEPARATOR = ", "
_NO_STORES = "none"
_ACT_REPORT = "{status}: {revision}"
_ACT_REASON = "  {reason}"
_ACT_STORES = "  reached: {stores}"
_USAGE_EXIT_CODE = 2
_FAILED_EXIT_CODE = 1


class AppSubcommand(StrEnum):
    """Closed set of ``telec app`` verbs."""

    STATUS = "status"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    INSTALL = "install"
    ROLLBACK = "rollback"
    ASSESSED = "assessed"


def _refuse(message: str, code: int = _FAILED_EXIT_CODE) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _no_operands(verb: AppSubcommand, node: CommandDef, args: list[str]) -> None:
    if parse_command_args(node, args).positionals:
        raise CliUsageError(_NO_OPERANDS.format(verb=verb.value))


def _lifecycle_script(layout: InstallationLayout) -> Path:
    """The active release's lifecycle script, reached through ``current``."""
    script = layout.current / _LIFECYCLE_SCRIPT
    if not script.is_file():
        _refuse(_NO_ACTIVE_RELEASE)
    return script


def _run_lifecycle(verb: AppSubcommand) -> None:
    """Hand the process to the active release's lifecycle, so its output and exit status are the verb's own."""
    script = _lifecycle_script(InstallationLayout())
    logger.info(_LIFECYCLE_EVENT, verb=verb.value, script=str(script))
    # Python ignores SIGPIPE and an exec'd program inherits that. The lifecycle script streams the daemon's
    # startup log through a `tail | while` pipeline it stops by killing the reader; with SIGPIPE ignored
    # the `tail` never ends and the verb never returns.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    # The service lifecycle is a release's own script; there is no Python API for it, and replacing
    # this process keeps the terminal and exit status exactly the lifecycle's.
    os.execv(script, [str(script), verb.value])


def _release_tag_suffix(layout: InstallationLayout, revision: str) -> str:
    """The published release tag naming the revision, shown beside its full commit; empty for a mainline revision."""
    try:
        tag = release_tag(Repo(str(layout.repository)), revision)
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError):
        return ""
    return _STATUS_TAG.format(tag=tag) if tag else ""


def _record_lines(record: InstallRecord, layout: InstallationLayout) -> list[str]:
    active = (
        _STATUS_ACTIVE.format(revision=record.active, tag=_release_tag_suffix(layout, record.active))
        if record.active
        else _STATUS_NO_ACTIVE
    )
    lines = [_STATUS_INSTALLATION.format(root=layout.root), active]
    location = layout.active_release()
    if location is not None:
        lines.append(_STATUS_LOCATION.format(path=location))
    if record.previous:
        lines.append(_STATUS_PREVIOUS.format(revision=record.previous))
    if record.migrated.started:
        stores = _STORE_SEPARATOR.join(record.migrated.stores) or _STATUS_UNKNOWN_MIGRATED
        lines.append(_STATUS_MIGRATED.format(stores=stores))
    if record.installing is not None:
        window = record.installing.migrated
        reached = _STORE_SEPARATOR.join(window.stores) or (_STATUS_UNKNOWN_MIGRATED if window.started else _NO_STORES)
        lines.append(_STATUS_INSTALLING.format(target=record.installing.target, stores=reached))
    if record.publication is not None:
        failure = _STATUS_REASON.format(reason=record.publication.failure) if record.publication.failure else ""
        lines.append(_STATUS_PUBLICATION.format(revision=record.publication.revision, failure=failure.lstrip()))
    if record.last_act is not None:
        act = record.last_act
        lines.append(
            _STATUS_LAST_ACT.format(act=act.act.value, outcome=act.outcome.value, revision=act.revision, at=act.at)
        )
        if act.reason:
            lines.append(_STATUS_REASON.format(reason=act.reason))
    return lines


def _assessment_lines(assessment: AssessmentRecord) -> list[str]:
    # Whether work is owed, not which install: the inspector takes the install from its activation event.
    newest = assessment.newest_owed
    lines = [] if newest is None else [_STATUS_OWED.format(since=newest.owed_since)]
    if assessment.last is not None:
        lines.append(_STATUS_LAST_ASSESSMENT.format(at=assessment.last.at))
    return lines


def _convergence_lines(layout: InstallationLayout) -> list[str]:
    """The channel, the followed source, the last convergence decision with its reason, and any held release."""
    lines = [
        _STATUS_CHANNEL.format(channel=config.deployment.channel.value),
        _STATUS_SOURCE.format(source=source_full_name(layout) or _STATUS_NO_SOURCE),
    ]
    try:
        record = read_convergence()
    except (OSError, ValidationError) as error:
        return [*lines, _STATUS_CONVERGENCE_UNREADABLE.format(error=error)]
    return [*lines, *_decision_lines(record, layout)]


def _decision_lines(record: ConvergenceRecord, layout: InstallationLayout) -> list[str]:
    try:
        active = active_release_version(layout)
    except ChannelTargetError:
        active = None
    lines = [_STATUS_NO_DECISION]
    if record.last is not None:
        lines = [
            _STATUS_DECISION.format(outcome=record.last.outcome.value, at=record.last.at),
            _STATUS_REASON.format(reason=record.last.reason),
        ]
    held = record.holding(active)
    if held is not None:
        lines.append(_STATUS_HELD.format(tag=held.tag, source=held.source, at=held.held_at))
    return lines


def _status(args: list[str]) -> None:
    _no_operands(AppSubcommand.STATUS, APP_STATUS, args)
    layout = InstallationLayout()
    for line in [
        *_record_lines(read_record(layout), layout),
        *_convergence_lines(layout),
        *_assessment_lines(read_assessment(layout)),
    ]:
        print(line)
    sys.stdout.flush()
    _run_lifecycle(AppSubcommand.STATUS)


def _start(args: list[str]) -> None:
    _no_operands(AppSubcommand.START, APP_START, args)
    _run_lifecycle(AppSubcommand.START)


def _stop(args: list[str]) -> None:
    _no_operands(AppSubcommand.STOP, APP_STOP, args)
    _run_lifecycle(AppSubcommand.STOP)


def _restart(args: list[str]) -> None:
    _no_operands(AppSubcommand.RESTART, APP_RESTART, args)
    _run_lifecycle(AppSubcommand.RESTART)


def _report(result: InstallResult) -> None:
    """Print what an act ended with and exit non-zero unless it completed or changed nothing."""
    print(_ACT_REPORT.format(status=result.status.value, revision=result.revision or ""))
    if result.reason:
        print(_ACT_REASON.format(reason=result.reason), file=sys.stderr)
    if result.reached_stores:
        print(_ACT_STORES.format(stores=_STORE_SEPARATOR.join(result.reached_stores)), file=sys.stderr)
    if result.left_stopped:
        print(_FAILED_STOPPED, file=sys.stderr)
    if result.publication_failure:
        print(_PUBLICATION_OWED.format(failure=result.publication_failure), file=sys.stderr)
    if result.status in (InstallStatus.REFUSED, InstallStatus.FAILED) or result.publication_failure:
        raise SystemExit(_FAILED_EXIT_CODE)


def _request(revision: str | None, layout: InstallationLayout, ports: LiveInstallPorts) -> InstallRequest:
    """The install request: the named revision, or the target the installation's channel resolves.

    A named revision is a deliberate selection and asks no confirmation. An edge target is the newest green
    revision, and the act confirms before it stops the daemon that no newer green revision overtook it.
    """
    if revision is not None:
        return InstallRequest(target=revision, release_tag=release_tag_of(revision))
    if not layout.repository.is_dir():
        _refuse(_NO_KEPT_REPOSITORY)
    channel = config.deployment.channel
    try:
        ports.fetch(None)
        target = channel_target(layout, channel)
    except (ReleasePreparationError, ChannelTargetError) as error:
        _refuse(str(error))
    return InstallRequest(
        target=target.reference,
        release_tag=target.release_tag,
        is_superseded=partial(is_superseded, layout) if channel is ReleaseChannel.EDGE else None,
    )


def _install(args: list[str]) -> None:
    parsed = parse_command_args(APP_INSTALL, args)
    if len(parsed.positionals) > 1:
        raise CliUsageError(_TOO_MANY_OPERANDS)
    layout = InstallationLayout()
    ports = LiveInstallPorts(layout)
    request = _request(parsed.positionals[0] if parsed.positionals else None, layout, ports)
    logger.info(_ACT_EVENT, act=InstallAct.INSTALL.value, target=request.target)
    _report(install(request, ports, layout))


def _rollback(args: list[str]) -> None:
    _no_operands(AppSubcommand.ROLLBACK, APP_ROLLBACK, args)
    layout = InstallationLayout()
    logger.info(_ACT_EVENT, act=InstallAct.ROLLBACK.value)
    _report(rollback(LiveInstallPorts(layout), layout))


def _owed_listing(owed: tuple[OwedInstall, ...]) -> list[str]:
    if not owed:
        return [_ASSESSED_NONE_OWED]
    return [
        _ASSESSED_OWED_HEADER,
        *(_ASSESSED_OWED_ENTRY.format(number=install.number, revision=install.revision) for install in owed),
    ]


def _assessed(args: list[str]) -> None:
    operands = parse_command_args(APP_ASSESSED, args).positionals
    if len(operands) != 1 or not operands[0].isdecimal():
        raise CliUsageError(_ASSESSED_OPERAND)
    number = int(operands[0])
    layout = InstallationLayout()
    not_serving = serving_active_release(layout)
    if not_serving is not None:
        _refuse(_ASSESSED_NOT_SERVING.format(reason=not_serving))
    try:
        after = update_assessment(lambda record: record.assessed(number, datetime.now(UTC)), layout)
    except NothingOwed as error:
        _refuse(_LINE_SEPARATOR.join([_ASSESSED_NOTHING_OWED.format(number=number), *_owed_listing(error.owed)]))
    if after.last is not None:
        logger.info(
            _ASSESSED_EVENT,
            number=after.last.number,
            revision=after.last.revision,
            still_owed=[install.number for install in after.owed],
        )
        print(_ASSESSED_REPORT.format(number=after.last.number, revision=after.last.revision))
    if after.owed:
        print(
            _ASSESSED_STILL_OWED.format(numbers=_NUMBER_SEPARATOR.join(str(install.number) for install in after.owed))
        )


_HANDLERS: dict[AppSubcommand, Callable[[list[str]], None]] = {
    AppSubcommand.STATUS: _status,
    AppSubcommand.START: _start,
    AppSubcommand.STOP: _stop,
    AppSubcommand.RESTART: _restart,
    AppSubcommand.INSTALL: _install,
    AppSubcommand.ROLLBACK: _rollback,
    AppSubcommand.ASSESSED: _assessed,
}


def handle_app(args: list[str]) -> None:
    """Route ``telec app <verb>`` to its handler."""
    if not args:
        print(_usage(TelecCommand.APP))
        return
    try:
        verb = AppSubcommand(args[0])
    except ValueError:
        print(_usage(TelecCommand.APP))
        raise SystemExit(_USAGE_EXIT_CODE) from None
    _HANDLERS[verb](args[1:])
