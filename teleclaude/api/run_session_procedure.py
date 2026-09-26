"""Launch facts for a manually started procedure activation (sibling of run_session_job)."""

from __future__ import annotations

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api_models import RunSessionRequest
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.organization import resolve_organization
from teleclaude.core.procedure_activation_runner import ProcedureActivationLaunch, procedure_activation_launch

_PROCEDURE_ACTIVATION_ARGUMENTS_INVALID_DETAIL = (
    "activate-procedure requires the procedure's snippet ID as its first argument"
)
_PROCEDURE_ACTIVATION_COMPANY_CONFLICT_DETAIL = "the company argument disagrees with the selected --company"
_PROCEDURE_ACTIVATION_COMPANY_REQUIRED_TEMPLATE = (
    "select a company with --company <slug>: eligible companies are {companies}"
)
_PROCEDURE_ACTIVATION_NO_ELIGIBLE_COMPANY_DETAIL = (
    "select a company with --company <slug>; the caller belongs to no company"
)


def normalize_procedure_activation_request(
    request: RunSessionRequest, args: str, identity: CallerIdentity
) -> ProcedureActivationLaunch:
    """Derive the launch facts for a manually started procedure activation.

    The company comes only from an explicit selection (the args' own company
    token, or ``--company``, which must agree when both are given) or the
    calling session's carried-forward company. A sole eligible membership is
    never promoted to a session company here; when none of those supplies
    one, the refusal names the caller's eligible companies rather than
    guessing.
    """
    parts = args.split()
    if not parts:
        raise RunSessionRefusal(
            status_code=400,
            detail=_PROCEDURE_ACTIVATION_ARGUMENTS_INVALID_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    procedure_id = parts[0]
    company_arg = parts[1] if len(parts) > 1 else None
    if company_arg is not None and request.company is not None and company_arg != request.company:
        raise RunSessionRefusal(
            status_code=400,
            detail=_PROCEDURE_ACTIVATION_COMPANY_CONFLICT_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    company = company_arg or request.company or identity.company
    if company is not None:
        return procedure_activation_launch(procedure_id, company)

    person_slug = get_identity_resolver().resolve_by_email(identity.email).person_slug if identity.email else None
    eligible = (
        tuple(membership.company_slug for membership in resolve_organization(person_slug).memberships)
        if person_slug is not None
        else ()
    )
    if not eligible:
        raise RunSessionRefusal(
            status_code=400,
            detail=_PROCEDURE_ACTIVATION_NO_ELIGIBLE_COMPANY_DETAIL,
            reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
        )
    raise RunSessionRefusal(
        status_code=400,
        detail=_PROCEDURE_ACTIVATION_COMPANY_REQUIRED_TEMPLATE.format(companies=", ".join(eligible)),
        reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
    )
