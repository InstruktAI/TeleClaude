"""Scoped command clearance for clients that perform API work outside dispatch."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from teleclaude.caller_identity import NoIdentityCliCaller, PersonCliCaller, person_entry_for_email
from teleclaude.cli.session_auth import (
    ResolvedCliIdentity,
    cli_clearance,
    no_identity_refusal,
    resolve_cli_identity,
)
from teleclaude.cli.telec.auth import _resolve_command_auth


class ClearanceKind(StrEnum):
    """Kinds of authorization a client request may carry."""

    VERB = "verb"
    IDENTIFIED_ONLY = "identified-only"
    UNGOVERNED = "ungoverned"


@dataclass(frozen=True)
class ClearanceScope:
    """Authorization scope for a request initiated outside CLI dispatch."""

    kind: ClearanceKind
    command_path: str | None = None
    target_session_id: str | None = None
    additional_command_paths: tuple[str, ...] = ()

    @classmethod
    def verb(cls, command_path: str, *, target_session_id: str | None = None) -> ClearanceScope:
        """Clear a request as one declared CLI verb."""
        return cls(ClearanceKind.VERB, command_path, target_session_id)

    @classmethod
    def verbs(cls, command_paths: list[str]) -> ClearanceScope:
        """Clear one request against every verb it performs."""
        if not command_paths:
            return cls.ungoverned()
        return cls(ClearanceKind.VERB, command_paths[0], additional_command_paths=tuple(command_paths[1:]))

    @classmethod
    def identified_only(cls) -> ClearanceScope:
        """Require a resolved person or system identity, with no verb band."""
        return cls(ClearanceKind.IDENTIFIED_ONLY)

    @classmethod
    def ungoverned(cls) -> ClearanceScope:
        """Mark a request that has no CLI command to clear."""
        return cls(ClearanceKind.UNGOVERNED)


def refresh_cli_identity_role(identity: ResolvedCliIdentity) -> ResolvedCliIdentity:
    """Refresh a launched person's registry role without changing who launched the client."""
    caller = identity.caller
    if not isinstance(caller, PersonCliCaller) or not caller.email:
        return identity
    person = person_entry_for_email(caller.email)
    if person is None:
        return replace(identity, caller=NoIdentityCliCaller(), principal=None)
    return replace(
        identity,
        caller=PersonCliCaller(
            email=person.email,
            person_slug=person.slug,
            human_role=person.role,
        ),
    )


def clearance_scope_refusal(scope: ClearanceScope, identity: ResolvedCliIdentity | None) -> str | None:
    """Return a scope's refusal without printing, exiting, or contacting the daemon."""
    if scope.kind is ClearanceKind.UNGOVERNED:
        return None
    resolved = refresh_cli_identity_role(identity or resolve_cli_identity())
    if scope.kind is ClearanceKind.IDENTIFIED_ONLY:
        if isinstance(resolved.caller, NoIdentityCliCaller):
            return no_identity_refusal(resolved)
        return None
    command_paths = ([scope.command_path] if scope.command_path is not None else []) + list(
        scope.additional_command_paths
    )
    for command_path in command_paths:
        refusal = cli_clearance(
            command_path,
            resolved,
            scope.target_session_id,
            _resolve_command_auth(command_path),
        ).refusal
        if refusal is not None:
            return refusal
    return None
