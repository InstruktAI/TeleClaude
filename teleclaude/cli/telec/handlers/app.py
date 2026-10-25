"""CLI handlers for ``telec app``: operate the machine's installation from any directory.

The edge only translates: each verb addresses the installation under the XDG data directory, and the
behavior lives in reconciliation (install, rollback, status) and the daemon lifecycle (start, stop,
restart, health). A project checkout the caller stands in is neither run nor changed
(``local/projects/teleclaude/spec/feature/reconciliation/installed-releases``).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.handlers._arg_parsing import CliUsageError, parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    APP_INSTALL,
    APP_RESTART,
    APP_ROLLBACK,
    APP_START,
    APP_STATUS,
    APP_STOP,
)
from teleclaude.cli.telec.surface_types import CommandDef, TelecCommand
from teleclaude.config.machine import config
from teleclaude.core.reconciliation.channel_target import ChannelTargetError, channel_target, release_tag_of
from teleclaude.core.reconciliation.install_act import (
    InstallRequest,
    InstallResult,
    InstallStatus,
    install,
    rollback,
)
from teleclaude.core.reconciliation.installation import InstallAct, InstallationLayout, InstallRecord, read_record
from teleclaude.core.reconciliation.installation_ports import LiveInstallPorts
from teleclaude.core.reconciliation.installation_release import ReleasePreparationError
from teleclaude.deployment.release_checkout import release_tag
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = get_logger(__name__)

__all__ = ["handle_app"]

_LIFECYCLE_SCRIPT = Path("bin") / "daemon-control.sh"
_LIFECYCLE_EVENT = "telec_app_lifecycle"
_ACT_EVENT = "telec_app_act"
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
    "The release is active, but publishing its documentation, agent artifacts and schemas did not complete: "
    "{failure}\nRun `telec app install` again to replay it."
)
_STATUS_PUBLICATION = "Publication owed:  {revision}{failure}"
_STATUS_LAST_ACT = "Last act:          {act} {outcome} {revision} at {at}"
_STATUS_REASON = "  reason: {reason}"
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


def _status(args: list[str]) -> None:
    _no_operands(AppSubcommand.STATUS, APP_STATUS, args)
    layout = InstallationLayout()
    for line in _record_lines(read_record(layout), layout):
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
    """The install request: the named revision, or the target the installation's channel resolves."""
    if revision is not None:
        return InstallRequest(target=revision, release_tag=release_tag_of(revision))
    if not layout.repository.is_dir():
        _refuse(_NO_KEPT_REPOSITORY)
    try:
        ports.fetch(None)
        target = channel_target(layout, config.deployment.channel, config.deployment.series)
    except (ReleasePreparationError, ChannelTargetError) as error:
        _refuse(str(error))
    return InstallRequest(target=target.reference, release_tag=target.release_tag)


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


_HANDLERS: dict[AppSubcommand, Callable[[list[str]], None]] = {
    AppSubcommand.STATUS: _status,
    AppSubcommand.START: _start,
    AppSubcommand.STOP: _stop,
    AppSubcommand.RESTART: _restart,
    AppSubcommand.INSTALL: _install,
    AppSubcommand.ROLLBACK: _rollback,
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
