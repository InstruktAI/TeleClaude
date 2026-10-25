"""The running daemon's reaction to its source: a push or release of the repository the installation follows.

The installation reacts for itself: it does not depend on a project checkout being registered on the
machine, so the consumer establishes the event's repository itself. Its complete match domain is the
event's repository identity (``repository.full_name`` in the payload) equal to the installation's source —
the owner and name of the kept repository's remote, so a fork's installation follows its fork — and only
then the channel's own rules decide the target (``deployment.self_update.target_for_event``). Every other
repository's events are outside the domain, whether or not a project for them is registered.

The install stops the daemon that decided it, so the reaction launches the act as a process of its own,
detached from the daemon's process group; the service definitions let such a process outlive the stop
(``local/projects/teleclaude/design/architecture/deployment-pipeline``).
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.core.reconciliation.installation_release import release_process_environment
from teleclaude.deployment.self_update import (
    ConvergenceTarget,
    SelfUpdateError,
    SkipReason,
    record_admitted_target,
    target_for_event,
)
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.type_pattern import TypePattern
from teleclaude.git import GitCommandError, Repo

logger = get_logger(__name__)

INSTALLATION_REACTION_CONSUMER = "installation-reaction"

_PUSH_EVENT_TYPE = "github.push"
_RELEASE_EVENT_TYPE = "github.release"
_REPOSITORY_FIELD = "repository"
_FULL_NAME_FIELD = "full_name"
_REMOTE_NAME = "origin"
_REMOTE_PATTERN = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$")
_FULL_NAME_TEMPLATE = "{owner}/{name}"
_RELEASE_PYTHON = Path(".venv") / "bin" / "python"
_REACTION_MODULE = "teleclaude.deployment.self_update"
_MODULE_OPTION = "-m"
_TARGET_OPTION = "--target"
_ADMITTED_OPTION = "--admitted"
_DECISION_EVENT = "installation_reaction_decision"
_LAUNCHED_OUTCOME = "launched"
_OUTSIDE_DOMAIN_OUTCOME = "outside_domain"
_NOT_INSTALLED_OUTCOME = "no_installation"
_LAUNCH_FAILED = "the installation reaction for {target} could not be launched: {error}"


class ReactionLaunchError(RuntimeError):
    """The reaction was decided but its process did not start, so the event must not be acknowledged as handled."""


def source_full_name(layout: InstallationLayout) -> str | None:
    """The ``owner/name`` of the repository the installation follows, or ``None`` when it keeps none or follows no GitHub remote."""
    if not layout.repository.is_dir():
        return None
    try:
        url = str(Repo(str(layout.repository)).remote(_REMOTE_NAME).url)
    except (GitCommandError, ValueError, OSError):
        return None
    matched = _REMOTE_PATTERN.search(url)
    if matched is None:
        return None
    return _FULL_NAME_TEMPLATE.format(owner=matched.group("owner"), name=matched.group("name"))


def event_full_name(event: ReceivedEvent) -> str | None:
    """The ``owner/name`` the event's payload names as its repository, or ``None`` when it names none."""
    repository = event.data.get(_REPOSITORY_FIELD)
    if not isinstance(repository, dict):
        return None
    full_name = repository.get(_FULL_NAME_FIELD)
    return full_name if isinstance(full_name, str) else None


def reaction_target(event: ReceivedEvent, layout: InstallationLayout) -> ConvergenceTarget | SkipReason | None:
    """The target the installation converges to for this event; ``None`` when the event is outside its domain."""
    followed = source_full_name(layout)
    named = event_full_name(event)
    if followed is None or named is None or followed.casefold() != named.casefold():
        return None
    return target_for_event(event, config.deployment.channel, config.deployment.series)


def launch_reaction(target: str, layout: InstallationLayout) -> None:
    """Start the act for ``target`` as a process detached from the daemon's, from the active release's interpreter."""
    record_admitted_target(target, layout)
    python = layout.current / _RELEASE_PYTHON
    # The act stops this daemon, so it cannot run inside it: a detached process of the active release is the
    # only way for the decision to outlive the stop that carries it out.
    try:
        subprocess.Popen(
            [str(python), _MODULE_OPTION, _REACTION_MODULE, _TARGET_OPTION, target, _ADMITTED_OPTION],
            cwd=layout.current,
            env=release_process_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise ReactionLaunchError(_LAUNCH_FAILED.format(target=target, error=error)) from error


def build_installation_reaction_consumer() -> Consumer:
    """The consumer through which this computer's installation installs the revision its channel admits."""
    layout = InstallationLayout()

    def decide(event: ReceivedEvent) -> ConvergenceTarget | SkipReason | None:
        if layout.active_revision() is None:
            return None
        try:
            return reaction_target(event, layout)
        except SelfUpdateError:
            logger.error(_DECISION_EVENT, event_id=event.id, event_type=event.type, exc_info=True)
            return None

    async def handle(event: ReceivedEvent) -> None:
        target = await asyncio.to_thread(decide, event)
        if not isinstance(target, ConvergenceTarget):
            logger.info(
                _DECISION_EVENT,
                event_id=event.id,
                event_type=event.type,
                outcome=target if target is not None else _OUTSIDE_DOMAIN_OUTCOME,
            )
            return
        await asyncio.to_thread(launch_reaction, target.ref, layout)
        logger.info(
            _DECISION_EVENT, event_id=event.id, event_type=event.type, target=target.ref, outcome=_LAUNCHED_OUTCOME
        )

    return Consumer(
        name=INSTALLATION_REACTION_CONSUMER,
        interest=Interest(
            types=(TypePattern(_PUSH_EVENT_TYPE), TypePattern(_RELEASE_EVENT_TYPE)),
            own_computer_only=False,
        ),
        handler=handle,
    )
