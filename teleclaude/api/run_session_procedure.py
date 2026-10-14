"""Entry facts for a standing agent started by hand: a subscribed procedure run for a company (sibling of run_session_job)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api_models import RunSessionRequest
from teleclaude.context_selector import entry_procedure_gap, resolve_snippet_meta
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.organization import resolve_organization
from teleclaude.core.procedure_entry import EntryContext, EntryRefusal, manual_activation_entry, normalize_procedure_id
from teleclaude.docs_subscriptions import SubscriptionHomeKind
from teleclaude.types.activation_home import ActivationHome

_PROCEDURE_ACTIVATION_COMPANY_REQUIRED_TEMPLATE = (
    "select a company with --company <slug>: eligible companies are {companies}"
)
_PROCEDURE_ACTIVATION_NO_ELIGIBLE_COMPANY_DETAIL = (
    "select a company with --company <slug>; the caller belongs to no company"
)
_ELIGIBLE_COMPANIES_SEPARATOR = ", "


@dataclass(frozen=True)
class ManualActivation:
    """The entry context and session company of a standing agent started by hand."""

    entry: EntryContext
    company: str


def manual_activation(
    request: RunSessionRequest, procedure_token: str, identity: CallerIdentity
) -> ManualActivation | None:
    """Derive the entry facts for a subscribed procedure started by hand, or ``None`` for any other procedure.

    A hand-started agent must be indistinguishable to the activation runner's ``find`` from a runner-started
    one, so it enters as an activation of a company home: the procedure's ID is the session's instance
    identity and the company is the session's company. The company comes only from an explicit selection
    (``--company``) or the calling session's carried-forward company. A sole eligible membership is never
    promoted to a session company here; when none supplies one, the refusal names the caller's eligible
    companies rather than guessing. A procedure that is not a usable entry procedure is left to the entry's
    own refusal.
    """
    try:
        procedure_id = normalize_procedure_id(procedure_token)
    except EntryRefusal:
        return None
    snippet = resolve_snippet_meta(procedure_id, project_root=Path(request.project))
    if entry_procedure_gap(snippet) is not None or snippet is None or snippet.subscription_delivery is None:
        return None
    company = request.company or identity.company
    if company is None:
        raise _company_refusal(identity)
    return ManualActivation(
        entry=manual_activation_entry(
            procedure_id=procedure_id,
            home=ActivationHome(SubscriptionHomeKind.COMPANY, company).to_token(),
        ),
        company=company,
    )


def _company_refusal(identity: CallerIdentity) -> RunSessionRefusal:
    """The refusal naming the caller's eligible companies when a manual activation selected none."""
    person_slug = get_identity_resolver().resolve_by_email(identity.email).person_slug if identity.email else None
    eligible = (
        tuple(membership.company_slug for membership in resolve_organization(person_slug).memberships)
        if person_slug is not None
        else ()
    )
    if not eligible:
        return RunSessionRefusal(
            status_code=400,
            detail=_PROCEDURE_ACTIVATION_NO_ELIGIBLE_COMPANY_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    return RunSessionRefusal(
        status_code=400,
        detail=_PROCEDURE_ACTIVATION_COMPANY_REQUIRED_TEMPLATE.format(
            companies=_ELIGIBLE_COMPANIES_SEPARATOR.join(eligible)
        ),
        reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
    )
