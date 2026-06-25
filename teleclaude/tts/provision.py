"""On-demand provisioning of the TTS-exclusive optional dependencies.

The TTS-exclusive deps live in the ``tts`` optional extra (see ``pyproject.toml``),
excluded from a baseline install. They are installed on demand the first time an
operator enables TTS, gated on a supported platform and pinned to the committed
lockfile. Provisioned state is *probed* (do the extra-backed deps import?), never
stored as a flag.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import platform
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.config import TTSConfig, TTSServiceConfig

logger = get_logger(__name__)

TTS_PROVISION_FAILED_EVENT = "tts_provision_failed"

# The repo root holding pyproject.toml / uv.lock (teleclaude/tts/provision.py -> repo).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The lock-enforced install command for the `tts` extra. `--frozen` forbids any
# runtime dependency resolution or lockfile mutation (supply-chain).
_PROVISION_COMMAND = ("uv", "sync", "--frozen", "--extra", "tts")

# Importable module names provided by the `tts` extra, by backend family.
_ELEVENLABS_MODULE = "elevenlabs"
_MLX_PIPELINE_MODULES = ("misaki", "num2words", "phonemizer")

_MACOS_SERVICE = "macos"


class TTSProvisionError(RuntimeError):
    """Base error for TTS dependency provisioning failures."""


class TTSUnsupportedPlatformError(TTSProvisionError):
    """Raised when no configured-and-enabled TTS service can run on this host."""


class TTSDepsInstallError(TTSProvisionError):
    """Raised when the on-demand `tts` extra install fails or leaves deps absent."""


def _enabled_services(tts_cfg: TTSConfig | None) -> dict[str, TTSServiceConfig]:
    if tts_cfg is None or not tts_cfg.services:
        return {}
    return {name: cfg for name, cfg in tts_cfg.services.items() if cfg.enabled}


def _is_mlx_service(cfg: TTSServiceConfig) -> bool:
    """An mlx local-model service is identified by a set ``model`` field."""
    return bool(cfg.model)


def _service_supported(name: str, cfg: TTSServiceConfig) -> bool:
    is_darwin = sys.platform == "darwin"
    is_arm64 = platform.machine() == "arm64"
    if _is_mlx_service(cfg):
        return is_darwin and is_arm64
    if name == _MACOS_SERVICE:
        return is_darwin
    # elevenlabs / openai / pyttsx3 — cross-platform.
    return True


def supported_services(tts_cfg: TTSConfig | None) -> list[str]:
    """Configured-and-enabled TTS services that can run on this host."""
    return [name for name, cfg in _enabled_services(tts_cfg).items() if _service_supported(name, cfg)]


def _service_requires_extra(name: str, cfg: TTSServiceConfig) -> bool:
    """True when the service's backend deps live in the ``tts`` extra."""
    return _is_mlx_service(cfg) or name == _ELEVENLABS_MODULE


def extra_required_services(tts_cfg: TTSConfig | None) -> list[str]:
    """Supported services whose backend deps are provided only by the ``tts`` extra."""
    enabled = _enabled_services(tts_cfg)
    return [name for name in supported_services(tts_cfg) if _service_requires_extra(name, enabled[name])]


def _service_modules(name: str, cfg: TTSServiceConfig) -> tuple[str, ...]:
    if _is_mlx_service(cfg):
        return _MLX_PIPELINE_MODULES
    if name == _ELEVENLABS_MODULE:
        return (_ELEVENLABS_MODULE,)
    return ()


def tts_deps_present(tts_cfg: TTSConfig | None) -> bool:
    """True iff every extra-requiring service has its extra-backed deps importable.

    Defined over the extra-requiring services only: when none is configured (all
    enabled services are core-backed) there is nothing the extra must provide, so
    this returns True. A core provider being enabled never satisfies the check for
    an unprovisioned extra-requiring service.
    """
    enabled = _enabled_services(tts_cfg)
    for name in extra_required_services(tts_cfg):
        modules = _service_modules(name, enabled[name])
        if not all(importlib.util.find_spec(module) is not None for module in modules):
            return False
    return True


async def provision_tts_deps_async() -> None:
    """Install the ``tts`` extra off the event loop, pinned to the committed lockfile."""

    def _run() -> None:
        result = subprocess.run(
            list(_PROVISION_COMMAND),
            cwd=str(_REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                TTS_PROVISION_FAILED_EVENT,
                reason="install_failed",
                returncode=result.returncode,
                stderr=(result.stderr or "")[-2000:],
            )
            raise TTSDepsInstallError(f"`{' '.join(_PROVISION_COMMAND)}` failed with exit code {result.returncode}.")

    await asyncio.to_thread(_run)


async def ensure_tts_provisioned_async(tts_cfg: TTSConfig | None) -> None:
    """Gate TTS enablement on a supported platform and importable extra deps.

    Fails closed: raises ``TTSUnsupportedPlatformError`` when no enabled service is
    supported, or ``TTSDepsInstallError`` when the install fails or leaves an
    extra-requiring service's deps absent.
    """
    if not supported_services(tts_cfg):
        logger.warning(
            TTS_PROVISION_FAILED_EVENT,
            reason="unsupported_platform",
            platform=sys.platform,
            machine=platform.machine(),
        )
        raise TTSUnsupportedPlatformError("No enabled TTS service is supported on this host; TTS stays off.")

    if tts_deps_present(tts_cfg):
        return

    await provision_tts_deps_async()
    importlib.invalidate_caches()

    if not tts_deps_present(tts_cfg):
        logger.warning(TTS_PROVISION_FAILED_EVENT, reason="deps_absent_after_install")
        raise TTSDepsInstallError("TTS dependency install completed but required modules are still absent.")
