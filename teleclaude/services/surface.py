"""Command surface — single manifest that generates both CLI and API transports.

Architecture:
    Domain commands are defined once in the SURFACE dict. Each command
    specifies its handler, parameters, auth requirements, response mode,
    and which transports expose it. CLI and API are generated from this
    manifest — no hand-written routes or CLI handlers for domain commands.

    CommandDef (authored)
           │
           ├──▶ Generated CLI entry point
           ├──▶ Generated API route
           └──▶ Both call the SAME handler via service layer
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from types import NoneType
from typing import Any


class Transport(StrEnum):
    """Where a command is exposed."""

    CLI = "cli"
    API = "api"


class ResponseMode(StrEnum):
    """How the transport should handle the response."""

    IMMEDIATE = "immediate"
    FIRE_AND_FORGET = "fire_and_forget"
    RECEIPT = "receipt"


class Role(StrEnum):
    """Minimum role required to execute the command."""

    ADMIN = "admin"
    MEMBER = "member"
    CONTRIBUTOR = "contributor"
    NEWCOMER = "newcomer"
    SYSTEM = "system"


@dataclass(frozen=True)
class Param:
    """Parameter definition for a command."""

    type: type
    required: bool = True
    positional: bool = False
    default: Any = None
    description: str = ""


@dataclass(frozen=True)
class CommandDef:
    """Single command definition — the atom of the surface manifest.

    Contains everything needed to generate both CLI and API transports:
    - handler: the service function to call
    - params: typed parameter definitions
    - returns: return type for serialization
    - auth: minimum role
    - mode: response mode (immediate, fire-and-forget, receipt)
    - expose: which transports serve this command
    """

    handler: Callable[..., Any]
    params: dict[str, Param] = field(default_factory=dict)
    returns: type = NoneType
    auth: Role = Role.MEMBER
    mode: ResponseMode = ResponseMode.IMMEDIATE
    expose: frozenset[Transport] = frozenset({Transport.CLI, Transport.API})
    description: str = ""


# ---------------------------------------------------------------------------
# SURFACE — the canonical command manifest
#
# Domain commands are grouped by schema pillar. Adding a command here
# automatically makes it available on all transports listed in `expose`.
#
# Handlers are wired during service initialization — they reference
# service layer functions, not raw database operations.
#
# This dict is intentionally empty until services are implemented.
# Each service module will register its commands here.
# ---------------------------------------------------------------------------

SURFACE: dict[str, CommandDef] = {
    # -- work domain ----------------------------------------------------------
    # "work.list-todos":      CommandDef(handler=..., ...),
    # "work.get-todo":        CommandDef(handler=..., ...),
    # "work.update-phase":    CommandDef(handler=..., ...),
    # "work.read-artifact":   CommandDef(handler=..., ...),
    # "work.write-artifact":  CommandDef(handler=..., ...),
    # "work.list-roadmap":    CommandDef(handler=..., ...),
    #
    # -- runtime domain -------------------------------------------------------
    # "runtime.list-sessions":   CommandDef(handler=..., ...),
    # "runtime.create-session":  CommandDef(handler=..., ...),
    # "runtime.end-session":     CommandDef(handler=..., ...),
    # "runtime.send-message":    CommandDef(handler=..., ...),
    #
    # -- ledger domain --------------------------------------------------------
    # "ledger.search-history":   CommandDef(handler=..., ...),
    # "ledger.get-session":      CommandDef(handler=..., ...),
    #
    # -- identity domain ------------------------------------------------------
    # "identity.list-people":    CommandDef(handler=..., ...),
    # "identity.add-person":     CommandDef(handler=..., ...),
    #
    # -- context domain -------------------------------------------------------
    # "context.index-snippets":  CommandDef(handler=..., ...),
    # "context.get-snippets":    CommandDef(handler=..., ...),
    # "context.save-memory":     CommandDef(handler=..., ...),
    # "context.search-memory":   CommandDef(handler=..., ...),
}
