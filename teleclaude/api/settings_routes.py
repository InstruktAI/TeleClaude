"""Runtime settings read/patch endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, verify_caller
from teleclaude.api_models import SettingsDTO, TTSSettingsDTO
from teleclaude.config.runtime_settings import RuntimeSettings
from teleclaude.tts.provision import TTSProvisionError

logger = get_logger(__name__)

PatchBodyScalar = str | int | float | bool | None
PatchBodyValue = PatchBodyScalar | list[PatchBodyScalar] | dict[str, PatchBodyScalar]

# 503 detail prefix when an enable request cannot provision its deps and stays off.
TTS_PROVISION_503_DETAIL = "TTS could not be provisioned and stays off"

_RUNTIME_SETTINGS: dict[str, RuntimeSettings | None] = {"value": None}

router = APIRouter(prefix="/settings", tags=["settings"])


def configure(runtime_settings: RuntimeSettings | None) -> None:
    """Wire runtime_settings; called from APIServer at construction."""
    _RUNTIME_SETTINGS["value"] = runtime_settings


@router.get("")
async def get_settings() -> SettingsDTO:
    """Return current mutable runtime settings."""
    runtime_settings = _RUNTIME_SETTINGS["value"]
    if not runtime_settings:
        raise HTTPException(503, "Runtime settings not available")
    state = runtime_settings.get_state()
    return SettingsDTO(tts=TTSSettingsDTO(enabled=state.tts.enabled))


@router.patch("")
async def patch_settings(
    body: dict[str, PatchBodyValue] = Body(...),
    _identity: CallerIdentity = Depends(verify_caller),
) -> SettingsDTO:
    """Apply partial updates to mutable runtime settings.

    Enabling TTS can trigger an off-loop dependency install, so the caller is
    verified before the patch is applied.
    """
    runtime_settings = _RUNTIME_SETTINGS["value"]
    if not runtime_settings:
        raise HTTPException(503, "Runtime settings not available")
    try:
        typed_patch = RuntimeSettings.parse_patch(body)
        state = await runtime_settings.apply_patch_async(typed_patch)
        return SettingsDTO(tts=TTSSettingsDTO(enabled=state.tts.enabled))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except TTSProvisionError as exc:
        raise HTTPException(503, f"{TTS_PROVISION_503_DETAIL}: {exc}") from exc
