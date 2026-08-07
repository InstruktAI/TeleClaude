"""Commit identity resolution and footer composition, shared by every sealed commit chokepoint.

Peer to ``teleclaude.todo_scaffold`` — a small module holding logic shared across
a CLI handler and other commit call sites, rather than duplicated per call site.
"""

from __future__ import annotations

from types import MappingProxyType

from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.core.agents import AgentName
from teleclaude.session_identity import get_session_id
from teleclaude.todo_scaffold import get_session_active_agent

# Mandated commit trailer (repo Commits policy). Owned here — the module that
# composes the footer owns the string it composes with.
_COMMIT_TRAILER = "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)"

_LINE_SEP = "\n"
_PARAGRAPH_SEP = _LINE_SEP * 2
_BLANK_LINE = ""
_SESSION_LINE_TEMPLATE = "Session: {session_id}"
_HUMAN_INVOLVED_LINE_TEMPLATE = "Human-Involved: {label}"
_HUMAN_INVOLVED_LABELS: MappingProxyType[bool, str] = MappingProxyType({True: "true", False: "false"})

_ERR_ACTIVE_AGENT_UNRESOLVED = "agent session {session_id!r} exists but its active agent could not be resolved"
_ERR_UNKNOWN_AGENT = "agent session {session_id!r} resolved to unknown agent {active_agent!r}"
_ERR_NO_GIT_IDENTITY = "agent session {session_id!r} resolved to agent {active_agent!r} with no configured git identity"
_ERR_NO_ATTRIBUTABLE_PARTY = "no agent session and no terminal login identity"


class CommitIdentityUnresolvable(RuntimeError):
    """Raised when a commit's authoring identity cannot be honestly resolved.

    Covers a real resolution failure — an agent session that exists but yields
    no usable identity, or a headless/automation context with no attributable
    party at all — distinct from the honest degrade (a human genuinely at the
    keyboard) that ``resolve_commit_identity`` returns rather than raises.
    """


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
        active_agent = get_session_active_agent(session_id)
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
            raise CommitIdentityUnresolvable(
                _ERR_NO_GIT_IDENTITY.format(session_id=session_id, active_agent=active_agent)
            )
        return git_identity, session_id

    if read_current_session_email():
        return None, None

    raise CommitIdentityUnresolvable(_ERR_NO_ATTRIBUTABLE_PARTY)


def compose_commit_footer(message: str, *, session_id: str | None, human_involved: bool) -> str:
    """Append the mandated footer to *message*, never reading a byte of it.

    Appends, in order: the original message exactly as given (subject and body,
    whatever was written — never trimmed or otherwise rewritten), a blank line,
    the branding line, a blank line, ``Session:`` (only when *session_id* is not
    ``None``), and ``Human-Involved:``. No scan, no parse, no rejection, no
    shape inference.
    """
    footer_lines = [_COMMIT_TRAILER, _BLANK_LINE]
    if session_id is not None:
        footer_lines.append(_SESSION_LINE_TEMPLATE.format(session_id=session_id))
    footer_lines.append(_HUMAN_INVOLVED_LINE_TEMPLATE.format(label=_HUMAN_INVOLVED_LABELS[human_involved]))
    return message + _PARAGRAPH_SEP + _LINE_SEP.join(footer_lines) + _LINE_SEP
