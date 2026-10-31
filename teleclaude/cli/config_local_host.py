"""Execute configuration in the CLI's or the terminal interface's own process while no daemon serves.

The configuration owner's dispatcher (``config.subject_operations.run_config_operation``) is the one
that performs every operation; the daemon's route and this host differ only in where it runs. While no
daemon serves this computer — before the platform's first start — the edges choose this host and receive
the same typed ``ConfigOutcome``, resolved for the same standing the route would resolve from the same
terminal caller (``local/projects/teleclaude/spec/domain/config``).
"""

from __future__ import annotations

import asyncio

from teleclaude.api.auth import caller_for_role_resolution, caller_identity_of, principal_for_carried_caller
from teleclaude.api_models_identity import WhoAmIDTO
from teleclaude.caller_identity import CarriedIdentity
from teleclaude.cli.api_client_request import JsonBody
from teleclaude.cli.clearance import ClearanceScope, clearance_scope_refusal, refresh_cli_identity_role
from teleclaude.cli.session_auth import ResolvedCliIdentity, resolve_cli_identity
from teleclaude.cli.tool_client import api_socket_path
from teleclaude.config.operation_requests import ConfigFailure, ConfigFailureKind, ConfigOutcome, ConfigRequest
from teleclaude.config.subject_operations import run_config_operation
from teleclaude.core.configuration_clearance import ConfigurationStanding, standing_for_caller
from teleclaude.runtime.daemon_shutdown_control import ControlRefusal, NothingListening, read_health


def daemon_serves_this_computer() -> bool:
    """Whether a daemon serves this computer: anything listening on its local API socket counts."""
    try:
        read_health(api_socket_path())
    except NothingListening:
        return False
    except ControlRefusal:
        return True
    return True


async def run_locally(request: ConfigRequest, identity: ResolvedCliIdentity | None = None) -> ConfigOutcome:
    """Run one configuration operation here, for the standing the terminal caller resolves to."""
    return await run_config_operation(_standing_of(identity or resolve_cli_identity()), request)


def run_locally_blocking(request: ConfigRequest) -> ConfigOutcome:
    """Run one configuration operation here from a synchronous caller."""
    return asyncio.run(run_locally(request))


def _standing_of(identity: ResolvedCliIdentity) -> ConfigurationStanding:
    carried = caller_identity_of(CarriedIdentity.from_cli_identity(identity))
    return standing_for_caller(caller_for_role_resolution(carried), carried.principal)


class LocalConfigHost:
    """The terminal interface's host for configuration requests while no daemon serves.

    It answers as the daemon's client does: the request is cleared as the ``telec config`` verb that
    performs it, and the answer is the operation's outcome as JSON.
    """

    async def run_config_operation(self, request_body: JsonBody, command_path: str) -> str:
        """Run one operation here, cleared as ``command_path``; a refusal is an outcome, as the daemon answers it."""
        identity = refresh_cli_identity_role(resolve_cli_identity())
        refusal = clearance_scope_refusal(ClearanceScope.verb(command_path), identity)
        if refusal is not None:
            outcome = ConfigOutcome(failure=ConfigFailure(kind=ConfigFailureKind.REFUSED, message=refusal))
        else:
            outcome = await run_locally(ConfigRequest.model_validate(request_body), identity)
        return outcome.model_dump_json()

    async def whoami(self) -> WhoAmIDTO:
        """The registered person operating this terminal, resolved as the daemon's identity route resolves them."""
        identity = resolve_cli_identity()
        carried = caller_identity_of(CarriedIdentity.from_cli_identity(identity))
        return WhoAmIDTO(
            principal=principal_for_carried_caller(carried),
            email=carried.email,
            person_slug=_standing_of(identity).person_slug,
        )
