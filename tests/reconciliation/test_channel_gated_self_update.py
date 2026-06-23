"""Functional bindings for channel-gated self-update.

Binds the CHANNEL-POLICY and convergence-FAILURE scenarios to the current live
convergence implementation: the v1 deployment handler/executor
(``teleclaude/deployment/handler.py`` + ``executor.py``). Per the spec's
"version-agnostic by construction" caveat, these scenarios re-bind unchanged when
the v2 reconciliation control loop (ADR-0024) ships.

Bound: UC-CSU-1 (alpha → mainline push), UC-CSU-2 (beta → published release only),
UC-CSU-3 (stable → within pinned minor only), UC-CSU-4 (exactly-once — a release for
the already-running version performs no second update), UC-CSU-5 (failure half —
convergence halts with a recorded reason).

Intentionally unbound:
- UC-CSU-6 (no operator action): structural/automatic — the handler is driven by an
  event with no operator command in any path. Asserting it would only restate the
  wiring the other scenarios already exercise, so it is left to the smoke tier.

UC-CSU-5's success path is exercised only up to its failure branch on purpose:
``execute_update``'s success path terminates in ``os._exit(42)``, which would
hard-kill the pytest runner. Only failure paths that ``return`` before that call
are driven here.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from teleclaude import __version__
from teleclaude.config import DeploymentConfig, ReleaseChannel
from teleclaude.deployment import executor, handler
from teleclaude.hooks.webhook_models import HookEvent

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/reconciliation/channel-gated-self-update"

# Channel inputs, asserted by identity against the convergence the handler triggers
# (round-trip: the configured channel is the channel that converges).
_ALPHA = "alpha"
_BETA = "beta"
_STABLE = "stable"

# Release tags injected via the event payload, asserted by identity against the
# convergence target the decision propagates (round-trip: published tag → target).
_PINNED_MINOR = "1.2"
_BETA_TAG = "2.3.0"
_IN_PINNED_TAG = "1.2.5"
_OUT_OF_PINNED_TAG = "1.3.0"


class _CapturedUpdate:
    """Capturing async fake for ``execute_update`` — the process boundary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(
        self,
        channel: str,
        version_info: dict,
        *,
        get_redis: object = None,
    ) -> None:
        self.calls.append((channel, version_info))


async def _run_decision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    channel: str,
    pinned_minor: str,
    event: HookEvent,
) -> list[tuple[str, dict]]:
    """Drive the real channel-policy decision; return captured execute_update calls."""
    captured = _CapturedUpdate()
    deployment = DeploymentConfig(channel=ReleaseChannel(channel), pinned_minor=pinned_minor)
    monkeypatch.setattr(handler._config, "deployment", deployment)
    monkeypatch.setattr(handler, "execute_update", captured)

    await handler.handle_deployment_event(event)
    await asyncio.sleep(0)  # let the scheduled execute_update task run
    return captured.calls


@pytest.mark.spec(_SPEC, "UC-CSU-1")
async def test_alpha_converges_on_mainline_push(monkeypatch: pytest.MonkeyPatch) -> None:
    event = HookEvent.now(source="github", event_type="push", properties={"ref": "refs/heads/main"})

    calls = await _run_decision(monkeypatch, channel=_ALPHA, pinned_minor="", event=event)

    [(call_channel, version_info)] = calls
    assert call_channel == _ALPHA
    assert version_info["channel"] == _ALPHA
    # Alpha stamps the currently-running version as the convergence origin.
    assert version_info["from_version"] == __version__


@pytest.mark.spec(_SPEC, "UC-CSU-2")
async def test_beta_converges_on_published_release(monkeypatch: pytest.MonkeyPatch) -> None:
    event = HookEvent.now(
        source="github",
        event_type="release",
        properties={"action": "published"},
        payload={"release": {"tag_name": f"v{_BETA_TAG}"}},
    )

    calls = await _run_decision(monkeypatch, channel=_BETA, pinned_minor="", event=event)

    [(call_channel, version_info)] = calls
    assert call_channel == _BETA
    assert version_info["version"] == _BETA_TAG


@pytest.mark.spec(_SPEC, "UC-CSU-2")
async def test_beta_ignores_unpublished_mainline_change(monkeypatch: pytest.MonkeyPatch) -> None:
    event = HookEvent.now(source="github", event_type="push", properties={"ref": "refs/heads/main"})

    calls = await _run_decision(monkeypatch, channel=_BETA, pinned_minor="", event=event)

    assert calls == []


@pytest.mark.spec(_SPEC, "UC-CSU-3")
async def test_stable_converges_within_pinned_minor(monkeypatch: pytest.MonkeyPatch) -> None:
    event = HookEvent.now(
        source="github",
        event_type="release",
        properties={"action": "published"},
        payload={"release": {"tag_name": f"v{_IN_PINNED_TAG}"}},
    )

    calls = await _run_decision(monkeypatch, channel=_STABLE, pinned_minor=_PINNED_MINOR, event=event)

    [(call_channel, version_info)] = calls
    assert call_channel == _STABLE
    assert version_info["version"] == _IN_PINNED_TAG


@pytest.mark.spec(_SPEC, "UC-CSU-3")
async def test_stable_ignores_release_outside_pinned_minor(monkeypatch: pytest.MonkeyPatch) -> None:
    event = HookEvent.now(
        source="github",
        event_type="release",
        properties={"action": "published"},
        payload={"release": {"tag_name": f"v{_OUT_OF_PINNED_TAG}"}},
    )

    calls = await _run_decision(monkeypatch, channel=_STABLE, pinned_minor=_PINNED_MINOR, event=event)

    assert calls == []


@pytest.mark.spec(_SPEC, "UC-CSU-4")
async def test_release_for_already_running_version_performs_no_second_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given the installation has already converged to its running version,
    # When a release for that same version becomes visible again,
    # Then it recognizes it is already at the desired version and performs no second update.
    event = HookEvent.now(
        source="github",
        event_type="release",
        properties={"action": "published"},
        payload={"release": {"tag_name": f"v{__version__}"}},
    )

    calls = await _run_decision(monkeypatch, channel=_BETA, pinned_minor="", event=event)

    assert calls == []


class _StatusRedis:
    """Fake Redis capturing each status payload written during convergence."""

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def set(self, _key: str, value: str) -> None:
        self.payloads.append(json.loads(value))


class _FailingGitProc:
    """Fake subprocess whose git step fails non-zero with stderr."""

    def __init__(self) -> None:
        self.returncode = 1

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", b"boom")


@pytest.mark.spec(_SPEC, "UC-CSU-5")
async def test_convergence_halts_with_recorded_reason_on_step_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_redis = _StatusRedis()

    async def get_redis() -> Redis:
        return status_redis  # pyright: ignore[reportReturnType]

    async def failing_exec(*_args: object, **_kwargs: object) -> _FailingGitProc:
        return _FailingGitProc()

    monkeypatch.setattr(executor.asyncio, "create_subprocess_exec", failing_exec)

    await executor.execute_update(
        _ALPHA,
        {"from_version": "1.0.0", "version": ""},
        get_redis=get_redis,
    )

    # Convergence began cleanly (no error on the opening status)...
    assert not status_redis.payloads[0].get("error")
    # ...then halted with a recorded reason on the failing step (the executor writes
    # an ``error`` field only on the failure status — recorded, never silent)...
    assert status_redis.payloads[-1].get("error")
    # ...and never advanced through the remaining convergence steps (migrate →
    # install → restart), each of which records its own status. Halting at the first
    # failing step means exactly the start marker and the failure marker were written.
    assert len(status_redis.payloads) == 2


__all__: list[str] = []
