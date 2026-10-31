"""The daemon's request surface for configuration subject operations.

Every `telec config` operation is published here as one request that performs the same
operation under the same target clearance as the CLI's own process does. The caller's
standing is resolved by this computer from the caller's principal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution, carried_caller
from teleclaude.config.operation_answers import CONFIG_API_PREFIX, CONFIG_OPERATIONS_ROUTE
from teleclaude.config.operation_requests import ConfigOutcome, ConfigRequest
from teleclaude.config.subject_operations import run_config_operation
from teleclaude.core.configuration_clearance import standing_for_caller

router = APIRouter(prefix=CONFIG_API_PREFIX, tags=["config"])


@router.post(CONFIG_OPERATIONS_ROUTE)
async def run_operation(
    request: ConfigRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> ConfigOutcome:
    """Run one configuration operation for the caller this computer resolves from the request."""
    standing = standing_for_caller(caller_for_role_resolution(identity), identity.principal)
    return await run_config_operation(standing, request)
