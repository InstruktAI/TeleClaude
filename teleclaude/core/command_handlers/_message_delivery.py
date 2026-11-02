"""Composer-aware dispatch for accepted inbound messages."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.inbound_errors import InboundPlacementUncertainError
from teleclaude.core.injected_text import InjectedInputAuthority
from teleclaude.core.models import Session
from teleclaude.core.runtime_readiness import RuntimeReadiness
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_utils import resolve_working_dir


async def inject_inbound_text(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    authority: InjectedInputAuthority,
    readiness: RuntimeReadiness,
) -> bool | tmux_io.UserTurnDeliveryResult:
    """Preserve inbound composer protection without changing operator paths."""
    working_dir = resolve_working_dir(session.project_path, session.subdir)
    if active_agent and session.lifecycle_status != SessionLifecycleStatus.HEADLESS:
        return await tmux_io.inject_user_turn(
            session,
            text,
            active_agent=active_agent,
            authority=authority,
            readiness=readiness,
        )
    return await tmux_io.route_text(
        session,
        text,
        working_dir=working_dir,
        active_agent=active_agent,
        authority=authority,
        readiness=readiness,
    )


@dataclass
class PlacementProbe:
    """Whether the begun-effect hook has fired for one delivery attempt.

    Replaying a queue-backed interface delivery after its paste began appends a second copy
    beside whatever the first attempt left in the composer, so such a failure is final.
    """

    begun: bool = False

    async def mark(self) -> None:
        self.begun = True

    def raise_if_begun(
        self, session_id: str, stage: tmux_io.UserTurnDeliveryStage, cause: BaseException | None = None
    ) -> None:
        """Raise the final placement-uncertain failure when placement began, chaining `cause`."""
        if self.begun:
            raise InboundPlacementUncertainError(session_id=session_id, stage=stage) from cause


async def inject_inbound_text_tracking_placement(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    authority: InjectedInputAuthority,
    readiness: RuntimeReadiness,
    on_placement_begun: Callable[[], Awaitable[None]],
) -> bool | tmux_io.UserTurnDeliveryResult:
    """Inject inbound text, reporting through `on_placement_begun` the moment placement begins.

    Only an interface-authority delivery to an active agent reports: conversation-authority
    replays hold on an occupied composer instead of appending, so they cannot duplicate.
    """
    inject = inject_inbound_text(session, text, active_agent=active_agent, authority=authority, readiness=readiness)
    is_active_agent_delivery = bool(active_agent) and session.lifecycle_status != SessionLifecycleStatus.HEADLESS
    if not (is_active_agent_delivery and authority is InjectedInputAuthority.INTERFACE):
        return await inject
    # The begun-effect hook fires only for the task that installs the scope, and gather runs
    # this coroutine as a new task, so the scope is entered here and not around the gather.
    with tmux_bridge.input_effect_scope(session.tmux_session_name, on_placement_begun):
        return await inject
