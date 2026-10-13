"""Company resolution for session creation, and its observability record.

Split out of the create-session door purely to keep that module under its
size guardrail; the decision itself is identity's, per
`resolve_company_selection`.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.core.organization import CompanySelectionOutcome, CompanySelectionRefused, resolve_company_selection

logger = get_logger(__name__)

_SESSION_COMPANY_RESOLVED_EVENT = "session_company_resolved"
_SESSION_COMPANY_REFUSED_EVENT = "session_company_refused"


def resolve_session_creation_company(
    request_id: str | None, company: str | None, human_email: str | None, parent_company: str | None
) -> tuple[str | None, str]:
    """Validate an explicit company selection, or inherit the parent's.

    Returns ``(company, source)`` where source is ``selected``, ``inherited``,
    or ``none``. Having logged the refusal, raises config's
    ``UnregisteredReferentError`` when an explicit selection names a company
    this computer has not registered, and ``CompanySelectionRefused`` when it
    fails membership validation.
    """
    if company:
        selection = resolve_company_selection(company, human_email)
        if selection.outcome is not CompanySelectionOutcome.ACCEPTED:
            logger.info(_SESSION_COMPANY_REFUSED_EVENT, request_id=request_id, reason=selection.outcome.value)
            if selection.outcome is CompanySelectionOutcome.UNKNOWN_COMPANY:
                raise unregistered_referent(ReferentKind.COMPANY, company)
            raise CompanySelectionRefused(selection.outcome, company, selection.eligible)
        return company, "selected"
    if parent_company:
        return parent_company, "inherited"
    return None, "none"


def record_session_company_resolved(
    request_id: str | None, session_id: str, company: str | None, source: str, initiator_session_id: str | None
) -> None:
    """Record the company resolution outcome for a newly created session."""
    logger.info(
        _SESSION_COMPANY_RESOLVED_EVENT,
        request_id=request_id,
        session_id=session_id,
        company=company,
        source=source,
        initiator_session_id=initiator_session_id,
    )
