"""Route published procedure subscriptions to derived contracts, and submit activations.

Publication is registration: a procedure's declared subscriptions become live
contracts with no second registration act. Contracts are derived, never
persisted, and re-derived whenever the published index's digest changes —
never at startup only, so an edit takes effect at the next event.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Mapping
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import find_company_config_path
from teleclaude.core.command_dispatch import run_local_command
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import ErrorEventContext, TeleClaudeEvents
from teleclaude.docs_subscriptions import SubscriptionPublication, published_procedure_subscriptions
from teleclaude.events.envelope import EventVisibility
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.handlers import HandlerRegistry
from teleclaude.hooks.registry import ContractRegistry
from teleclaude.hooks.webhook_models import Contract, HookEvent, PropertyCriterion, Target
from teleclaude.types.commands import ActivateProcedureCommand

logger = get_logger(__name__)

_OWNER = "procedure_subscriptions"
_HANDLER_KEY = "procedure_activation"
_CONTRACT_ID_PREFIX = "procedure-subscription:"
_SUBSCRIPTIONS_DERIVED_EVENT = "procedure_subscriptions_derived"
_ACTIVATION_DECISION_EVENT = "procedure_activation_decision"

_last_digest: str | None = None


class _EventIdentity(TypedDict):
    """The event fields the observation map correlates a decision back to its ingress record by."""

    source: str
    type: str
    event_ts: str


def _contract_id(procedure_id: str, company: str | None) -> str:
    if company is None:
        return f"{_CONTRACT_ID_PREFIX}{procedure_id}"
    return f"{_CONTRACT_ID_PREFIX}{company}:{procedure_id}"


def _parse_contract_id(contract_id: str) -> str:
    """Parse a derived contract id back into its procedure id.

    The single owner of this format: ``derive`` writes it, ``handle`` reads it.
    """
    rest = contract_id.removeprefix(_CONTRACT_ID_PREFIX)
    _company, _sep, procedure_id = rest.rpartition(":")
    return procedure_id if _sep else rest


def _emit_platform_error(message: str, *, source: str, details: Mapping[str, object] | None = None) -> None:
    try:
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=None, message=message, source=source, details=details),
            visibility=EventVisibility.CLUSTER,
        )
    except Exception as exc:
        logger.error("procedure_activation_error_event_emission_failed", source=source, error=str(exc))


def derive(registry: ContractRegistry, publication: SubscriptionPublication | None = None) -> None:
    """(Re)derive every procedure-subscription contract from the published index.

    A global entry's contract carries no company criterion, so the handler
    sees company-less events too and can emit the affirmative skip record.
    """
    global _last_digest
    publication = publication or published_procedure_subscriptions()
    contracts = [
        Contract(
            id=_contract_id(entry.procedure_id, entry.company),
            target=Target(handler=_HANDLER_KEY),
            type_criterion=PropertyCriterion(match=list(entry.event_types)),
            properties=({"company": PropertyCriterion(match=entry.company)} if entry.company is not None else {}),
            source="derived",
        )
        for entry in publication.entries
    ]
    registry.replace_derived(_OWNER, contracts)
    _last_digest = publication.digest
    logger.info(_SUBSCRIPTIONS_DERIVED_EVENT, digest=publication.digest, contract_count=len(contracts))


async def refresh(registry: ContractRegistry) -> None:
    """Pre-match hook: re-derive when the published index's digest has changed.

    A failure here clears this owner's derived contracts rather than keeping
    stale ones: a stale contract could activate a removed procedure, and a
    missed activation is recovered by the procedure's own reconciliation
    (design invariant "Attention, not effect"), which a wrongly-live contract
    is not.
    """
    global _last_digest
    try:
        publication = published_procedure_subscriptions()
        if publication.digest == _last_digest:
            return
        derive(registry, publication)
    except Exception as exc:
        # Covers both reading the publication and building contracts from it —
        # a malformed entry raising mid-derive must clear contracts exactly
        # like an unreadable index does. Letting it escape uncaught here would
        # reach the dispatcher's generic pre-match handler instead, which logs
        # and emits but leaves whatever is already cached live, violating the
        # "never keep stale contracts on a failed refresh" invariant below.
        logger.error("procedure_subscriptions_refresh_failed", error=str(exc), exc_info=True)
        registry.replace_derived(_OWNER, [])
        _last_digest = None
        _emit_platform_error(str(exc), source="procedure_subscriptions_refresh")


async def handle(event: HookEvent, contract: Contract) -> None:
    """Submit an activation for the matched contract's procedure, or record why not."""
    procedure_id = _parse_contract_id(contract.id)
    # source/type/event_ts correlate this decision back to the ingress's own
    # inbound_webhook_event_accepted record — the observation map's join key.
    identity_fields: _EventIdentity = {
        "source": event.source,
        "type": event.type,
        "event_ts": event.timestamp,
    }
    raw_company = event.properties.get("company")
    company = raw_company if isinstance(raw_company, str) and raw_company else None
    if company is None:
        logger.info(
            _ACTIVATION_DECISION_EVENT,
            procedure_id=procedure_id,
            outcome="skipped",
            reason="no_company",
            **identity_fields,
        )
        return
    if find_company_config_path(company) is None:
        logger.info(
            _ACTIVATION_DECISION_EVENT,
            procedure_id=procedure_id,
            company=company,
            outcome="skipped",
            reason="company_not_hosted",
            **identity_fields,
        )
        return

    activate_cmd = ActivateProcedureCommand(
        procedure_id=procedure_id,
        company=company,
        event_json=event.to_json(),
        request_id=str(uuid.uuid4()),
    )
    try:
        receipt = await run_local_command(activate_cmd)
    except Exception as exc:
        logger.error(
            "procedure_activation_submission_failed",
            procedure_id=procedure_id,
            company=company,
            error=str(exc),
            exc_info=True,
            **identity_fields,
        )
        _emit_platform_error(
            str(exc),
            source="procedure_activation_submit",
            details={"procedure_id": procedure_id, "company": company, **identity_fields},
        )
        return
    operation_id = receipt.get("operation_id") if isinstance(receipt, dict) else None
    logger.info(
        _ACTIVATION_DECISION_EVENT,
        procedure_id=procedure_id,
        company=company,
        outcome="submitted",
        operation_id=str(operation_id or ""),
        **identity_fields,
    )


def install(registry: ContractRegistry, handlers: HandlerRegistry, dispatcher: HookDispatcher) -> None:
    """Register the handler, derive contracts, then register the refresh pre-match hook.

    Order matters: no contract is derived before its handler is registered.
    """
    handlers.register(_HANDLER_KEY, handle)
    derive(registry)
    dispatcher.register_pre_match(functools.partial(refresh, registry))
