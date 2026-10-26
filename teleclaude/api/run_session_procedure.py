"""Entry facts for a standing agent started by hand: a subscribed procedure run for its home (sibling of run_session_job)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api_models import RunSessionRequest
from teleclaude.config.subject_resolution import resolve_config_subject
from teleclaude.context_selector import entry_procedure_gap, resolve_snippet_meta
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.procedure_activation_runner import home_folder
from teleclaude.core.procedure_entry import EntryContext, EntryRefusal, manual_activation_entry, normalize_procedure_id
from teleclaude.core.procedure_event_delivery import ProcedureActivationTerminalError
from teleclaude.docs_subscriptions import (
    SubscriptionEntry,
    SubscriptionHomeKind,
    SubscriptionIdentity,
    published_procedure_subscriptions,
)
from teleclaude.types.activation_home import ActivationHome

_SUBSCRIPTION_UNPUBLISHED_TEMPLATE = (
    "{procedure_id} declares subscriptions that are not published on this computer; publish them first"
)
_SUBSCRIPTIONS_UNREADABLE_TEMPLATE = "the published procedure subscriptions cannot be read: {error}"
_SUBJECT_IDENTITY_TEMPLATE = (
    "{procedure_id} answers each event subject with its own agent; those agents start from their events"
)
_COMPANY_FOR_OTHER_KIND_TEMPLATE = (
    "{procedure_id} answers {kind} homes; --company names a company home and does not apply"
)
_COMPANY_INVALID_TEMPLATE = "--company {company!r} does not name a company: {error}"
_FOLDER_NOT_IN_KIND_TEMPLATE = "{procedure_id} answers {kind} homes, and {folder} is not in one"
_FOLDER_NOT_IN_COMPANY_TEMPLATE = (
    "{procedure_id} answers company homes, and {folder} is not in one; name the company with --company <slug>"
)
_FOLDER_UNRESOLVABLE_TEMPLATE = "the home of {folder} cannot be resolved: {error}"
_OUTSIDE_TIER_TEMPLATE = "{procedure_id} answers only {tier_home}, not {home}"


@dataclass(frozen=True)
class ManualActivation:
    """The entry context of a standing agent started by hand, the home it serves and the folder it works in."""

    entry: EntryContext
    home: ActivationHome
    folder: Path


def manual_activation(request: RunSessionRequest, procedure_token: str) -> ManualActivation | None:
    """Derive the home and entry facts for a subscribed procedure started by hand, or ``None`` for any other procedure.

    A hand-started agent is the procedure's agent for its home, exactly as an activation would start it: the
    procedure's published subscription names the kind of home it answers, and its publishing tier the home
    itself when the tier limits it. ``--company`` names that home only for a procedure answering company homes;
    otherwise the home is the one of that kind the invoking folder belongs to, and the platform for a platform
    procedure. The agent works in the home's folder. A procedure that is not a usable entry procedure is left
    to the entry's own refusal.
    """
    try:
        procedure_id = normalize_procedure_id(procedure_token)
    except EntryRefusal:
        return None
    snippet = resolve_snippet_meta(procedure_id, project_root=Path(request.project))
    if entry_procedure_gap(snippet) is not None or snippet is None or snippet.subscription_delivery is None:
        return None
    subscription = _published_subscription(procedure_id)
    if subscription.identity is SubscriptionIdentity.SUBJECT:
        raise _refusal(_SUBJECT_IDENTITY_TEMPLATE.format(procedure_id=procedure_id))
    home = _requested_home(request, subscription)
    if not subscription.reaches(home.kind, home.slug):
        tier_home = ActivationHome(subscription.home_kind, subscription.home_slug or home.slug).to_token()
        raise _refusal(
            _OUTSIDE_TIER_TEMPLATE.format(procedure_id=procedure_id, tier_home=tier_home, home=home.to_token())
        )
    try:
        folder = home_folder(home)
    except ProcedureActivationTerminalError as exc:
        raise _refusal(exc.detail, status_code=404) from exc
    return ManualActivation(
        entry=manual_activation_entry(procedure_id=procedure_id, home=home.to_token()),
        home=home,
        folder=folder,
    )


def _published_subscription(procedure_id: str) -> SubscriptionEntry:
    """The procedure's published subscription, the one the event consumer matches against."""
    try:
        entries = published_procedure_subscriptions().entries
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise _refusal(_SUBSCRIPTIONS_UNREADABLE_TEMPLATE.format(error=exc), status_code=503) from exc
    subscription = next((entry for entry in entries if entry.procedure_id == procedure_id), None)
    if subscription is None:
        raise _refusal(_SUBSCRIPTION_UNPUBLISHED_TEMPLATE.format(procedure_id=procedure_id))
    return subscription


def _requested_home(request: RunSessionRequest, subscription: SubscriptionEntry) -> ActivationHome:
    """The home the hand start names: by ``--company``, by the publishing tier, or by the invoking folder."""
    kind = subscription.home_kind
    procedure_id = subscription.procedure_id
    if request.company is not None:
        if kind is not SubscriptionHomeKind.COMPANY:
            raise _refusal(_COMPANY_FOR_OTHER_KIND_TEMPLATE.format(procedure_id=procedure_id, kind=kind.value))
        try:
            return ActivationHome(kind, request.company)
        except ValueError as exc:
            raise _refusal(_COMPANY_INVALID_TEMPLATE.format(company=request.company, error=exc)) from exc
    if kind is SubscriptionHomeKind.PLATFORM:
        return ActivationHome.platform()
    if subscription.home_slug is not None:
        return ActivationHome(kind, subscription.home_slug)
    folder = Path(request.project)
    try:
        subject = resolve_config_subject(folder)
    except ValueError as exc:
        raise _refusal(_FOLDER_UNRESOLVABLE_TEMPLATE.format(folder=folder, error=exc)) from exc
    if subject is None or subject.instance is None or subject.kind.value != kind.value:
        template = (
            _FOLDER_NOT_IN_COMPANY_TEMPLATE if kind is SubscriptionHomeKind.COMPANY else _FOLDER_NOT_IN_KIND_TEMPLATE
        )
        raise _refusal(template.format(procedure_id=procedure_id, kind=kind.value, folder=folder))
    return ActivationHome(kind, subject.instance)


def _refusal(detail: str, *, status_code: int = 400) -> RunSessionRefusal:
    return RunSessionRefusal(status_code=status_code, detail=detail, reason=AgentDispatchReason.RUN_REQUEST_REJECTED)
