"""The running daemon's reaction to its source: a green main revision or a published release of the followed repository.

The installation reacts for itself: it does not depend on a project checkout being registered on the
machine, so the consumer establishes the signal's repository itself. Every signal is normalized at this boundary
to one shape — the repository's canonical ``owner/name``, what kind of signal, and the revision or release tag it
names — and its complete match domain is that repository equal to the installation's source: the owner and name
of the kept repository's remote, so a fork's installation follows its fork. Only then does the channel's own rule
decide the target (``deployment.self_update.decide_signals``). Every other repository's signals are outside the
domain, whether or not a project for them is registered. A pushed revision is no signal on any channel.

Relayed events are the fast path; the interval read of the source (``InstallationSourceReader``) feeds the same
decision, so an installation that receives no relay, or was not running when one was sent, still converges.

The install stops the daemon that decided it, so the reaction launches the act as a process of its own,
detached from the daemon's process group; the service definitions let such a process outlive the stop
(``local/projects/teleclaude/design/architecture/deployment-pipeline``).
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.config._models import ReleaseChannel
from teleclaude.config.machine import config
from teleclaude.core.integration.newest_green import NewestGreenStatus, newest_green_main_revision
from teleclaude.core.reconciliation.channel_target import (
    ChannelTargetError,
    active_release_version,
    required_checks_at,
    source_full_name,
)
from teleclaude.core.reconciliation.convergence_decision import (
    DecisionOutcome,
    HeldRelease,
    mark_hold_announced,
    record_decision,
)
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.core.reconciliation.installation_ports import LiveInstallPorts
from teleclaude.core.reconciliation.installation_release import ReleasePreparationError, release_process_environment
from teleclaude.deployment.self_update import (
    ChannelDecision,
    ChannelSignal,
    SignalKind,
    SkipReason,
    decide_signals,
    record_admitted_target,
)
from teleclaude.events import EventLevel, EventProducer, EventVisibility
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import EventHomeMarker, ReceivedEvent, occurrence_id
from teleclaude.events.references import ReleaseRef
from teleclaude.events.schemas.ci import CiRevisionPassed, CiRevisionPassedData
from teleclaude.events.schemas.installation import InstallationReleaseHeld, InstallationReleaseHeldData
from teleclaude.events.type_pattern import TypePattern
from teleclaude.events.wire import LegacyFacts
from teleclaude.git import Repo
from teleclaude.github.actions import GitHubActionsReader, GitHubActionsRefused, PublicRepository

logger = get_logger(__name__)

INSTALLATION_REACTION_CONSUMER = "installation-reaction"

_CHANNEL_SIGNAL: dict[ReleaseChannel, SignalKind] = {
    ReleaseChannel.EDGE: SignalKind.GREEN_REVISION,
    ReleaseChannel.STABLE: SignalKind.RELEASE_PUBLISHED,
}
_REVISION_PASSED_TYPE = CiRevisionPassed.type_name()
_RELEASE_EVENT_TYPE = "github.release"
_PUBLISHED_ACTION = "published"
_ACTION_FIELD = "action"
_RELEASE_FIELD = "release"
_TAG_FIELD = "tag_name"
_REPOSITORY_FIELD = "repository"
_FULL_NAME_FIELD = "full_name"
_RELEASE_PYTHON = Path(".venv") / "bin" / "python"
_REACTION_MODULE = "teleclaude.deployment.self_update"
_MODULE_OPTION = "-m"
_TARGET_OPTION = "--target"
_ADMITTED_OPTION = "--admitted"
_DECISION_EVENT = "installation_reaction_decision"
_LAUNCHED_OUTCOME = "launched"
_OUTSIDE_DOMAIN_OUTCOME = "outside_domain"
_LAUNCH_FAILED = "the installation reaction for {target} could not be launched: {error}"
_READ_INTERVAL_SECONDS = 3600.0
_READ_FAILED_EVENT = "installation_source_read_failed"
_READ_DECISION_EVENT = "installation_source_read_decision"
_RELEASE_IDENTITY = "{source}@{version}"
_HELD_PRODUCER = "daemon"
_HELD_DOMAIN = "installation"
_HELD_DESCRIPTION = "Release {tag} of {source} is beyond the active release {active} and is held for the inspector"
_HELD_EMITTED_EVENT = "installation_release_held_emitted"
_VERSION_TEXT = "{major}.{minor}.{patch}"
_NO_RELEASE_READ_REASON = "the source's published releases could not be read: {detail}"
_NO_RELEASES_REASON = "the source has published no release"
_FETCH_FAILED_REASON = "the source could not be fetched, so no required check could be read: {detail}"


class ReactionLaunchError(RuntimeError):
    """The reaction was decided but its process did not start, so the event must not be acknowledged as handled."""


@dataclass(frozen=True)
class _Reaction:
    """A decision with the version of the active release it was decided against."""

    decision: ChannelDecision
    active: tuple[int, int, int]


def event_full_name(event: ReceivedEvent) -> str | None:
    """The ``owner/name`` the event's payload names as its repository, or ``None`` when it names none."""
    repository = event.data.get(_REPOSITORY_FIELD)
    if not isinstance(repository, dict):
        return None
    full_name = repository.get(_FULL_NAME_FIELD)
    return full_name if isinstance(full_name, str) else None


def normalize_event(event: ReceivedEvent) -> ChannelSignal | SkipReason:
    """The one shape the decision reads, built from a relayed green announcement or a relayed release publication.

    A green announcement is typed and names its repository and revision; a release event names its repository
    and tag in the provider's payload. Anything else, and a release event of an action other than publication,
    is no signal.
    """
    if event.type == _REVISION_PASSED_TYPE:
        try:
            passed = CiRevisionPassedData.model_validate(event.data)
        except ValidationError:
            return SkipReason.NOT_A_SIGNAL
        return ChannelSignal(repository=passed.repository, kind=SignalKind.GREEN_REVISION, reference=passed.revision)
    if event.type != _RELEASE_EVENT_TYPE:
        return SkipReason.NOT_A_SIGNAL
    if event.data.get(_ACTION_FIELD) != _PUBLISHED_ACTION:
        return SkipReason.NOT_PUBLISHED_RELEASE
    repository = event_full_name(event)
    release = event.data.get(_RELEASE_FIELD)
    tag = release.get(_TAG_FIELD) if isinstance(release, dict) else None
    if repository is None or not isinstance(tag, str):
        return SkipReason.NOT_A_SIGNAL
    return ChannelSignal(repository=repository, kind=SignalKind.RELEASE_PUBLISHED, reference=tag)


def follows_source(signal: ChannelSignal, layout: InstallationLayout) -> bool:
    """Whether the signal is about the repository this installation follows: the one comparison every signal passes."""
    followed = source_full_name(layout)
    return followed is not None and followed.casefold() == signal.repository.casefold()


def react_to_signals(signals: Sequence[ChannelSignal], layout: InstallationLayout) -> _Reaction | None:
    """The channel's decision for the signals about the followed source; ``None`` when none concerns this installation.

    A signal concerns it when it is about the followed repository and of the kind its channel follows: a green
    revision on edge, a published release on stable. The other kind is no signal for this channel and leaves
    the recorded decision as it was, so a stable installation's last decision is not overwritten by every green
    main revision of its source.
    """
    channel = config.deployment.channel
    followed = tuple(
        signal for signal in signals if signal.kind is _CHANNEL_SIGNAL[channel] and follows_source(signal, layout)
    )
    if not followed:
        return None
    active = active_release_version(layout)
    if active is None:
        return None
    return _Reaction(decide_signals(followed, channel, active), active)


async def apply_reaction(reaction: _Reaction, layout: InstallationLayout, producer: EventProducer) -> None:
    """Record the decision, announce the release the record holds, and launch the admitted target.

    The record decides which release is held: an older or reordered signal never replaces a newer hold, and
    concurrent decisions agree because the record's own lock orders them. The held-release event is emitted for
    the recorded hold, once, and marked announced afterwards, so a hold whose announcement failed is announced
    again by the next signal or read, and an older release is never announced over a newer one.
    """
    decision = reaction.decision
    record = await asyncio.to_thread(record_decision, decision.outcome, decision.reason, decision.held, reaction.active)
    held = record.holding(reaction.active)
    if held is not None and not held.announced:
        await emit_held_release(producer, held, reaction.active)
        await asyncio.to_thread(mark_hold_announced, held)
    if decision.target is None:
        logger.info(_DECISION_EVENT, outcome=decision.outcome, reason=decision.reason)
        return
    await asyncio.to_thread(launch_reaction, decision.target.ref, layout)
    logger.info(_DECISION_EVENT, outcome=decision.outcome, reason=decision.reason, target=decision.target.ref)


async def emit_held_release(producer: EventProducer, held: HeldRelease, active: tuple[int, int, int]) -> None:
    """Announce the release held for the installation inspector, once per release: its identity names the event."""
    major, minor, patch = active
    active_text = _VERSION_TEXT.format(major=major, minor=minor, patch=patch)
    await producer.emit(
        InstallationReleaseHeld(
            id=occurrence_id(InstallationReleaseHeld.type_name(), held.source, held.version),
            subject=ReleaseRef(_RELEASE_IDENTITY.format(source=held.source, version=held.version)),
            home=EventHomeMarker.NONE,
            data=InstallationReleaseHeldData(
                source=held.source, version=held.version, tag=held.tag, active_version=active_text
            ),
        ),
        LegacyFacts(
            producer=_HELD_PRODUCER,
            level=EventLevel.INFRASTRUCTURE,
            domain=_HELD_DOMAIN,
            visibility=EventVisibility.CLUSTER,
            description=_HELD_DESCRIPTION.format(tag=held.tag, source=held.source, active=active_text),
        ),
    )
    logger.info(_HELD_EMITTED_EVENT, source=held.source, tag=held.tag)


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


def build_installation_reaction_consumer(producer: EventProducer) -> Consumer:
    """The consumer through which this computer's installation installs the revision its channel admits."""
    layout = InstallationLayout()

    def decide(event: ReceivedEvent) -> _Reaction | SkipReason | None:
        if layout.active_revision() is None:
            return None
        signal = normalize_event(event)
        if isinstance(signal, SkipReason):
            return signal
        try:
            return react_to_signals((signal,), layout)
        except ChannelTargetError:
            logger.error(_DECISION_EVENT, event_id=event.id, event_type=event.type, exc_info=True)
            return None

    async def handle(event: ReceivedEvent) -> None:
        reaction = await asyncio.to_thread(decide, event)
        if not isinstance(reaction, _Reaction):
            logger.info(
                _DECISION_EVENT,
                event_id=event.id,
                event_type=event.type,
                outcome=reaction if reaction is not None else _OUTSIDE_DOMAIN_OUTCOME,
            )
            return
        await apply_reaction(reaction, layout, producer)
        logger.info(
            _DECISION_EVENT,
            event_id=event.id,
            event_type=event.type,
            outcome=_LAUNCHED_OUTCOME if reaction.decision.target is not None else reaction.decision.outcome,
        )

    return Consumer(
        name=INSTALLATION_REACTION_CONSUMER,
        interest=Interest(
            types=(TypePattern(_REVISION_PASSED_TYPE), TypePattern(_RELEASE_EVENT_TYPE)),
            own_computer_only=False,
        ),
        handler=handle,
    )


class InstallationSourceReader:
    """Read the followed source at start and at a fixed interval, and feed the same decision the relayed signals feed.

    On stable it reads the source's published releases; on edge, the newest main revision integration establishes
    as green. A tick that admits nothing still records its decision, so status has a reason from the first tick;
    a failed read is logged and retried at the next interval and never changes the active release.
    """

    def __init__(self, producer: EventProducer, layout: InstallationLayout) -> None:
        self._producer = producer
        self._layout = layout

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Read now, then every interval until shutdown; a failed read never stops the loop."""
        while not shutdown_event.is_set():
            await self._read()
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=_READ_INTERVAL_SECONDS)
                break
            except TimeoutError:
                pass

    async def _read(self) -> None:
        try:
            await self._read_source()
        except Exception:  # supervision boundary: a failed read is retried at the next interval
            logger.error(_READ_FAILED_EVENT, exc_info=True)

    async def _read_source(self) -> None:
        active = await asyncio.to_thread(active_release_version, self._layout)
        if active is None:
            return
        source = await asyncio.to_thread(source_full_name, self._layout)
        if source is None:
            return
        channel = config.deployment.channel
        signals = await (
            self._green_signals(source, active)
            if channel is ReleaseChannel.EDGE
            else self._release_signals(source, active)
        )
        if not signals:
            return
        reaction = await asyncio.to_thread(react_to_signals, signals, self._layout)
        if reaction is not None:
            await apply_reaction(reaction, self._layout, self._producer)

    async def _green_signals(self, source: str, active: tuple[int, int, int]) -> tuple[ChannelSignal, ...]:
        """The newest green main revision as a signal, or nothing after recording why there is none."""
        try:
            await asyncio.to_thread(LiveInstallPorts(self._layout).fetch, None)
        except ReleasePreparationError as error:
            await self._record_unadmitted(
                DecisionOutcome.UNDETERMINED, _FETCH_FAILED_REASON.format(detail=error), active
            )
            return ()
        repository = Repo(str(self._layout.repository))

        def checks_at(revision: str) -> tuple[str, ...]:
            return required_checks_at(repository, revision)

        answer = await newest_green_main_revision(source, checks_at, self._layout.active_revision())
        if answer.status is NewestGreenStatus.GREEN and answer.revision is not None:
            return (ChannelSignal(repository=source, kind=SignalKind.GREEN_REVISION, reference=answer.revision),)
        outcome = (
            DecisionOutcome.NOTHING_NEWER
            if answer.status is NewestGreenStatus.NONE_GREEN
            else DecisionOutcome.UNDETERMINED
        )
        await self._record_unadmitted(outcome, answer.detail, active)
        return ()

    async def _release_signals(self, source: str, active: tuple[int, int, int]) -> tuple[ChannelSignal, ...]:
        """Every published release of the source as a signal, so the decision sees the compatible and the breaking alike."""
        try:
            releases = await GitHubActionsReader(PublicRepository(source)).published_releases()
        except GitHubActionsRefused as refusal:
            await self._record_unadmitted(
                DecisionOutcome.UNDETERMINED, _NO_RELEASE_READ_REASON.format(detail=refusal), active
            )
            return ()
        if not releases:
            await self._record_unadmitted(DecisionOutcome.NOTHING_NEWER, _NO_RELEASES_REASON, active)
        return tuple(
            ChannelSignal(repository=source, kind=SignalKind.RELEASE_PUBLISHED, reference=release.tag)
            for release in releases
        )

    async def _record_unadmitted(self, outcome: DecisionOutcome, reason: str, active: tuple[int, int, int]) -> None:
        await asyncio.to_thread(record_decision, outcome, reason, None, active)
        logger.info(_READ_DECISION_EVENT, outcome=outcome, reason=reason)
