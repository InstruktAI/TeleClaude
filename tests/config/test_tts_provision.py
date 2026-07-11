"""TTS lazy-provisioning behavior: packaging boundary, lazy import, and the provision module."""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import subprocess
from collections.abc import Callable
from importlib.machinery import ModuleSpec
from types import SimpleNamespace

import pytest

from teleclaude.config import TTSConfig, TTSServiceConfig
from teleclaude.tts import provision as provision_mod
from teleclaude.tts.backends.elevenlabs import ElevenLabsBackend
from teleclaude.tts.provision import (
    TTSDepsInstallError,
    TTSDepsRemoveError,
    TTSUnsupportedPlatformError,
    deprovision_tts_deps_async,
    ensure_tts_provisioned_async,
    provision_tts_deps_async,
    tts_deps_present,
)

pytestmark = pytest.mark.functional

_ELEVENLABS = "elevenlabs"


def _import_blocking(blocked: str) -> Callable[..., object]:
    """Return an __import__ replacement that raises ImportError for one package."""
    real_import = builtins.__import__

    def _fake(name: str, *args: object, **kwargs: object) -> object:
        if name == blocked or name.startswith(f"{blocked}."):
            raise ImportError(f"{blocked} is not installed")
        return real_import(name, *args, **kwargs)

    return _fake


def test_elevenlabs_backend_module_imports_without_dep() -> None:
    """The ElevenLabs backend module loads even when elevenlabs is absent (lazy import)."""
    el_mod = importlib.import_module("teleclaude.tts.backends.elevenlabs")
    real_import = builtins.__import__
    try:
        builtins.__import__ = _import_blocking(_ELEVENLABS)
        reloaded = importlib.reload(el_mod)
        assert reloaded.ElevenLabsBackend() is not None
    finally:
        builtins.__import__ = real_import
        importlib.reload(el_mod)


def test_elevenlabs_speak_returns_false_when_dep_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """speak() degrades to False (not raises) when the elevenlabs import fails."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(builtins, "__import__", _import_blocking(_ELEVENLABS))
    assert ElevenLabsBackend().speak("hello", "voice-id") is False


def _svc(*, enabled: bool = True, model: str | None = None) -> TTSServiceConfig:
    return TTSServiceConfig(enabled=enabled, model=model)


def _tts_config(services: dict[str, TTSServiceConfig]) -> TTSConfig:
    return TTSConfig(enabled=True, service_priority=None, events={}, services=services)


def _find_spec_blocking(absent: set[str], provisioned: set[str] | None = None) -> Callable[..., object]:
    """Return a find_spec replacement that reports the named modules as absent."""
    real_find_spec = importlib.util.find_spec
    provisioned = set() if provisioned is None else provisioned

    def _fake(name: str, *args: object, **kwargs: object) -> object:
        if name in absent:
            return None
        if name in provisioned:
            return ModuleSpec(name, loader=None)
        return real_find_spec(name, *args, **kwargs)

    return _fake


@pytest.mark.asyncio
async def test_extra_service_unprovisioned_triggers_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """A core provider being enabled must not skip the install for an unprovisioned extra service."""
    cfg = _tts_config({"openai": _svc(), "elevenlabs": _svc()})
    absent = {_ELEVENLABS}
    monkeypatch.setattr(importlib.util, "find_spec", _find_spec_blocking(absent, {_ELEVENLABS}))

    assert tts_deps_present(cfg) is False

    calls = {"n": 0}

    async def _fake_provision() -> None:
        calls["n"] += 1
        absent.clear()  # the install "succeeds": deps now import

    monkeypatch.setattr(provision_mod, "provision_tts_deps_async", _fake_provision)
    await ensure_tts_provisioned_async(cfg)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_core_only_config_needs_no_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """When only core-backed providers are enabled, nothing in the extra is required."""
    cfg = _tts_config({"openai": _svc()})
    assert tts_deps_present(cfg) is True

    calls = {"n": 0}

    async def _fake_provision() -> None:
        calls["n"] += 1

    monkeypatch.setattr(provision_mod, "provision_tts_deps_async", _fake_provision)
    await ensure_tts_provisioned_async(cfg)
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_provision_runs_lock_enforced_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """The install is pinned to the committed lockfile and run from the repo root."""
    calls: list[tuple[list[str], object]] = []

    def _fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs.get("cwd")))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    await provision_tts_deps_async()
    argv, cwd = calls[0]
    assert argv == list(provision_mod._PROVISION_COMMAND)
    assert cwd == str(provision_mod._REPO_ROOT)


@pytest.mark.asyncio
async def test_unsupported_platform_fails_closed() -> None:
    """No enabled-and-supported service on this host fails closed."""
    cfg = _tts_config({})
    with pytest.raises(TTSUnsupportedPlatformError):
        await ensure_tts_provisioned_async(cfg)


@pytest.mark.asyncio
async def test_failed_install_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero install exit raises TTSDepsInstallError."""

    def _fail_run(_argv: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", _fail_run)
    with pytest.raises(TTSDepsInstallError):
        await provision_tts_deps_async()


@pytest.mark.asyncio
@pytest.mark.spec("project/spec/feature/config/runtime-tts-toggle", "UC-CFG-RUNTIME-32")
async def test_deprovision_runs_lock_enforced_removal_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deprovision runs the resolver-inverse command from the repo root."""
    calls: list[tuple[list[str], object]] = []

    def _fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv, kwargs.get("cwd")))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    await deprovision_tts_deps_async()
    argv, cwd = calls[0]
    assert argv == list(provision_mod._DEPROVISION_COMMAND)
    assert cwd == str(provision_mod._REPO_ROOT)


@pytest.mark.asyncio
@pytest.mark.spec("project/spec/feature/config/runtime-tts-toggle", "UC-CFG-RUNTIME-33")
async def test_deprovision_failed_removal_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero removal exit raises TTSDepsRemoveError."""

    def _fail_run(_argv: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", _fail_run)
    with pytest.raises(TTSDepsRemoveError):
        await deprovision_tts_deps_async()
