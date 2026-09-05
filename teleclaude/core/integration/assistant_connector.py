"""Construct gated Google connector processes for validated person workspaces."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import (
    DeclaredMailAccountRefusal,
    RefusedDeclaredMailAccount,
    resolve_declared_mail_account,
)
from teleclaude.config.schema import MailConnector
from teleclaude.core.identity import AcceptedPersonContextBinding
from teleclaude.paths import PEOPLE_DIR

_GOOGLE_HOME_FLAG = "--home"
_GOOGLE_ACCOUNT_FLAG = "--account"
_GOOGLE_ENABLED_COMMANDS_FLAG = "--enable-commands"
_GOOGLE_DISABLED_COMMANDS_FLAG = "--disable-commands"
_GOOGLE_SETTINGS_COMMAND = "gmail.settings"
_FLAG_ASSIGNMENT_SUFFIX = "="
_CONNECTOR_DECISION_EVENT = "assistant_connector.decision"
_GOOGLE_CONTROL_FLAGS = frozenset(
    {
        _GOOGLE_HOME_FLAG,
        _GOOGLE_ACCOUNT_FLAG,
        "--acct",
        "-a",
        "--client",
        "--access-token",
        "--quota-project",
        _GOOGLE_ENABLED_COMMANDS_FLAG,
        "--enable-commands-exact",
        _GOOGLE_DISABLED_COMMANDS_FLAG,
        "--gmail-no-send",
        "--readonly",
    }
)
_GOOGLE_PERMITTED_COMMANDS = (
    "gmail.search",
    "gmail.messages",
    "gmail.get",
    "gmail.raw",
    "gmail.attachment",
    "gmail.url",
    "gmail.history",
    "gmail.thread",
    "gmail.labels",
    "gmail.batch",
    "gmail.archive",
    "gmail.mark-read",
    "gmail.unread",
    "gmail.trash",
    "gmail.send",
    "gmail.import",
    "gmail.reply",
    "gmail.reply-all",
    "gmail.forward",
    "gmail.autoreply",
    "gmail.track",
    "gmail.drafts",
    "calendar.calendars",
    "calendar.events",
    "calendar.event",
    "calendar.raw",
    "calendar.create",
    "calendar.update",
    "calendar.move",
    "calendar.delete",
    "calendar.freebusy",
    "calendar.respond",
    "calendar.conflicts",
    "calendar.changed",
    "calendar.search",
    "calendar.users",
)
_GOOGLE_PERMITTED_COMMANDS_VALUE = ",".join(_GOOGLE_PERMITTED_COMMANDS)
_GOOGLE_DISABLED_COMMANDS_VALUE = _GOOGLE_SETTINGS_COMMAND
logger = get_logger(__name__)


class AssistantConnectorOutcome(StrEnum):
    """Terminal outcomes emitted by the connector-launch boundary."""

    ADMITTED = "admitted"
    REFUSED = "refused"


class AssistantConnectorRefusalReason(StrEnum):
    """Closed reasons the connector-launch boundary refuses an invocation."""

    NO_ACCOUNT_NAMED = "no_account_named"
    PERSON_CONTEXT_MISSING = "person_context_missing"
    PERSON_CONTEXT_NOT_PERSON = "person_context_not_person"
    PERSON_CONTEXT_DECLARATION_UNREADABLE = "person_context_declaration_unreadable"
    PERSON_BINDING_REGISTRY_UNAVAILABLE = "person_binding_registry_unavailable"
    PERSON_BINDING_UNKNOWN = "person_binding_unknown"
    PERSON_BINDING_AMBIGUOUS = "person_binding_ambiguous"
    PERSON_BINDING_DISAGREEING = "person_binding_disagreeing"
    MISSING_REGISTERED_SLUG = "missing_registered_slug"
    CANONICAL_DOCUMENT_MISSING = "canonical_document_missing"
    PERSISTED_CLAIM_MISMATCH = "persisted_claim_mismatch"
    ACCOUNT_NOT_DECLARED = "account_not_declared"
    UNSUPPORTED_CONNECTOR = "unsupported_connector"
    CONTROL_FLAG_REJECTED = "control_flag_rejected"
    BINARY_UNAVAILABLE = "binary_unavailable"


class AssistantConnectorAccountSource(StrEnum):
    """The sole source from which the boundary accepts a connector account."""

    DECLARED = "declared"


@dataclass(frozen=True)
class GoogleConnectorProcess:
    """A constructed Google CLI process ready for the entry point to execute."""

    command: tuple[str, ...]
    environment: dict[str, str]


@dataclass(frozen=True)
class GoogleConnectorLaunchContext:
    """Runtime-injected executable and sealed environment for one Google process."""

    binary: Path
    environment: dict[str, str]


@dataclass(frozen=True)
class AssistantConnectorDecision:
    """One non-sensitive terminal decision at the connector-launch boundary."""

    invocation_id: str
    outcome: AssistantConnectorOutcome
    reason: AssistantConnectorRefusalReason | None
    account_source: AssistantConnectorAccountSource | None
    process: GoogleConnectorProcess | None


def prepare_assistant_connector_invocation(
    binding: AcceptedPersonContextBinding,
    account_address: str | None,
    arguments: Sequence[str],
    launch_context: GoogleConnectorLaunchContext,
    *,
    people_dir: Path = PEOPLE_DIR,
) -> AssistantConnectorDecision:
    """Construct an admitted Google process or a closed refusal before execution."""
    invocation_id = uuid4().hex
    if not account_address:
        return _refusal(invocation_id, AssistantConnectorRefusalReason.NO_ACCOUNT_NAMED)
    if _contains_google_control_flag(arguments):
        return _refusal(invocation_id, AssistantConnectorRefusalReason.CONTROL_FLAG_REJECTED)
    resolution = resolve_declared_mail_account(binding.person, account_address, people_dir)
    if isinstance(resolution, RefusedDeclaredMailAccount):
        return _refusal(invocation_id, _resolution_refusal_reason(resolution.reason))
    if resolution.account.connector is not MailConnector.GOOGLE:
        return _refusal(invocation_id, AssistantConnectorRefusalReason.UNSUPPORTED_CONNECTOR)
    process = GoogleConnectorProcess(
        command=(
            str(launch_context.binary),
            _GOOGLE_HOME_FLAG,
            str(resolution.state_root),
            _GOOGLE_ACCOUNT_FLAG,
            resolution.account.address,
            _GOOGLE_ENABLED_COMMANDS_FLAG,
            _GOOGLE_PERMITTED_COMMANDS_VALUE,
            _GOOGLE_DISABLED_COMMANDS_FLAG,
            _GOOGLE_DISABLED_COMMANDS_VALUE,
            *arguments,
        ),
        environment=launch_context.environment,
    )
    return _record_decision(
        AssistantConnectorDecision(
            invocation_id=invocation_id,
            outcome=AssistantConnectorOutcome.ADMITTED,
            reason=None,
            account_source=AssistantConnectorAccountSource.DECLARED,
            process=process,
        )
    )


def refuse_assistant_connector_invocation(reason: AssistantConnectorRefusalReason) -> AssistantConnectorDecision:
    """Record an ingress refusal before account resolution or process construction."""
    return _refusal(uuid4().hex, reason)


def _refusal(invocation_id: str, reason: AssistantConnectorRefusalReason) -> AssistantConnectorDecision:
    """Construct one refusal that never carries connector command content."""
    return _record_decision(
        AssistantConnectorDecision(
            invocation_id=invocation_id,
            outcome=AssistantConnectorOutcome.REFUSED,
            reason=reason,
            account_source=None,
            process=None,
        )
    )


def _record_decision(decision: AssistantConnectorDecision) -> AssistantConnectorDecision:
    """Record a terminal boundary decision without sensitive invocation data."""
    logger.info(
        _CONNECTOR_DECISION_EVENT,
        invocation_id=decision.invocation_id,
        outcome=decision.outcome.value,
        reason=decision.reason.value if decision.reason is not None else None,
        account_source=decision.account_source.value if decision.account_source is not None else None,
    )
    return decision


def _resolution_refusal_reason(reason: DeclaredMailAccountRefusal) -> AssistantConnectorRefusalReason:
    """Translate configuration-owned account resolution outcomes at its boundary."""
    return AssistantConnectorRefusalReason(reason.value)


def _contains_google_control_flag(arguments: Sequence[str]) -> bool:
    """Reject any caller attempt to replace the boundary's control plane."""
    return any(
        argument == control_flag or argument.startswith(f"{control_flag}{_FLAG_ASSIGNMENT_SUFFIX}")
        for argument in arguments
        for control_flag in _GOOGLE_CONTROL_FLAGS
    )
