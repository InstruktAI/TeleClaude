"""Commit identity resolution and footer composition, shared by every sealed commit chokepoint.

Peer to ``teleclaude.todo_scaffold`` — a small module holding logic shared across
a CLI handler and other commit call sites, rather than duplicated per call site.
"""

from __future__ import annotations

from types import MappingProxyType

from teleclaude.cli.session_auth import ResolvedCliIdentity, read_current_session_email
from teleclaude.constants import SYSTEM_OPERATOR_PRINCIPAL
from teleclaude.core.agents import AgentName
from teleclaude.core.identity import NoIdentityCliCaller, PersonCliCaller, human_principal_for_email
from teleclaude.core.session_identity_facts import read_session_active_agent
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.session_identity import get_session_id

# Mandated commit trailer (repo Commits policy). Owned here — the module that
# composes the footer owns the string it composes with.
_COMMIT_TRAILER = "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)"

_LINE_SEP = "\n"
_PARAGRAPH_SEP = _LINE_SEP * 2
_BLANK_LINE = ""
SESSION_TRAILER_KEY = "Session"
TODO_TRAILER_KEY = "Todo"
PLANNED_TODO_TRAILER_KEY = "Planned-Todo"
_HUMAN_INVOLVED_TRAILER_KEY = "Human-Involved"
_TRAILER_SEPARATOR = ":"
_SESSION_LINE_TEMPLATE = SESSION_TRAILER_KEY + ": {session_id}"
_HUMAN_INVOLVED_LINE_TEMPLATE = _HUMAN_INVOLVED_TRAILER_KEY + ": {label}"
_TODO_ASSOCIATION_LINE_TEMPLATE = "{key}: {slug}"
_HUMAN_INVOLVED_LABELS: MappingProxyType[bool, str] = MappingProxyType({True: "true", False: "false"})
_GENERATED_TRAILER_KEYS = frozenset(
    key.casefold()
    for key in (SESSION_TRAILER_KEY, _HUMAN_INVOLVED_TRAILER_KEY, TODO_TRAILER_KEY, PLANNED_TODO_TRAILER_KEY)
)
_GENERATED_BRANDING = _COMMIT_TRAILER.casefold()
_ERR_AUTHORED_METADATA = (
    "Commit message contains platform-owned metadata. Supply only the subject and explanation; "
    "use --todo for association and --human-involved for the involvement declaration."
)

_ERR_ACTIVE_AGENT_UNRESOLVED = "agent session {session_id!r} exists but its active agent could not be resolved"
_ERR_UNKNOWN_AGENT = "agent session {session_id!r} resolved to unknown agent {active_agent!r}"
_ERR_NO_GIT_IDENTITY = "agent session {session_id!r} resolved to agent {active_agent!r} with no configured git identity"
_ERR_NO_ATTRIBUTABLE_PARTY = "no agent session and no terminal login identity"
_ERR_NO_CALLER_PRINCIPAL = "no verified caller principal"


class CommitIdentityUnresolvable(RuntimeError):
    """Raised when a commit's authoring identity cannot be honestly resolved.

    Covers a real resolution failure — an agent session that exists but yields
    no usable identity, or a headless/automation context with no attributable
    party at all — distinct from the honest degrade (a human genuinely at the
    keyboard) that ``resolve_commit_identity`` returns rather than raises.
    """


class CommitMessageMetadataReserved(ValueError):
    """Caller-authored text occupies the commit owner's metadata namespace."""


def validate_authored_commit_message(message: str) -> None:
    """Reject generated metadata lines anywhere in the caller's message."""
    for line in message.splitlines():
        normalized = line.strip()
        key, separator, _ = normalized.partition(_TRAILER_SEPARATOR)
        if normalized.casefold() == _GENERATED_BRANDING or (
            separator and key.strip().casefold() in _GENERATED_TRAILER_KEYS
        ):
            raise CommitMessageMetadataReserved(_ERR_AUTHORED_METADATA)


def resolve_commit_identity() -> tuple[str | None, str | None]:
    """Resolve the git ``--author`` identity and session id for the current commit.

    Returns ``(git_identity, session_id)``:

    - An agent session exists: resolves its active agent to a configured bot
      identity. Any failure along that path — no active-agent answer, an
      unmapped agent name, or an agent with no identity entry — raises
      ``CommitIdentityUnresolvable``: an agent session that exists but resolves
      to no identity is a bug, not an honest gap.
    - No agent session, but a human is logged in at this terminal: returns
      ``(None, None)``, the honest degrade — git's own ambient identity is a
      real human's.
    - Neither an agent session nor a terminal login resolves: raises
      ``CommitIdentityUnresolvable`` — a headless or automation context with no
      attributable party at all.
    """
    session_id = get_session_id()
    if session_id:
        return _resolve_agent_session_commit_identity(session_id)

    if read_current_session_email():
        return None, None

    raise CommitIdentityUnresolvable(_ERR_NO_ATTRIBUTABLE_PARTY)


def _resolve_agent_session_commit_identity(session_id: str) -> tuple[str, str]:
    """Resolve an agent session to its bot author identity."""
    active_agent = read_session_active_agent(str(MAIN_DB_PATH), session_id)
    if active_agent is None:
        raise CommitIdentityUnresolvable(_ERR_ACTIVE_AGENT_UNRESOLVED.format(session_id=session_id))
    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError as exc:
        raise CommitIdentityUnresolvable(
            _ERR_UNKNOWN_AGENT.format(session_id=session_id, active_agent=active_agent)
        ) from exc
    git_identity = agent_name.git_identity
    if git_identity is None:
        raise CommitIdentityUnresolvable(_ERR_NO_GIT_IDENTITY.format(session_id=session_id, active_agent=active_agent))
    return git_identity, session_id


def resolve_commit_identity_from_caller(identity: ResolvedCliIdentity) -> tuple[str | None, str | None]:
    """Map the resolved local caller to the sealed commit author.

    An agent session commits as its agent's bot identity. A person resolved at a
    terminal, and the computer's operator outside any session, commit under git's
    own ambient identity: the repository's configured author.
    """
    if isinstance(identity.caller, NoIdentityCliCaller) or identity.principal is None:
        raise CommitIdentityUnresolvable(_ERR_NO_CALLER_PRINCIPAL)
    if identity.session_id:
        return _resolve_agent_session_commit_identity(identity.session_id)
    if identity.principal == SYSTEM_OPERATOR_PRINCIPAL:
        return None, None
    if (
        isinstance(identity.caller, PersonCliCaller)
        and identity.caller.email is not None
        and identity.principal == human_principal_for_email(identity.caller.email)
    ):
        return None, None
    raise CommitIdentityUnresolvable(_ERR_NO_CALLER_PRINCIPAL)


def compose_commit_footer(
    message: str,
    *,
    session_id: str | None,
    human_involved: bool,
    todo_association: tuple[str, str] | None = None,
) -> str:
    """Preserve valid authored text and append the platform-owned metadata."""
    validate_authored_commit_message(message)
    footer_lines = [_COMMIT_TRAILER, _BLANK_LINE]
    if session_id is not None:
        footer_lines.append(_SESSION_LINE_TEMPLATE.format(session_id=session_id))
    footer_lines.append(_HUMAN_INVOLVED_LINE_TEMPLATE.format(label=_HUMAN_INVOLVED_LABELS[human_involved]))
    if todo_association is not None:
        key, slug = todo_association
        footer_lines.append(_TODO_ASSOCIATION_LINE_TEMPLATE.format(key=key, slug=slug))
    return message + _PARAGRAPH_SEP + _LINE_SEP.join(footer_lines) + _LINE_SEP
