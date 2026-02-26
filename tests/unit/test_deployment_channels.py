"""Tests for deployment channel config, handler decision logic, executor paths, and fan-out."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.config.schema import DeploymentConfig, ProjectConfig
from teleclaude.hooks.webhook_models import HookEvent


def _create_task_closing_coro(coro: Any) -> MagicMock:
    """Side-effect for asyncio.create_task that closes the coroutine to prevent 'never awaited' warnings."""
    coro.close()
    return MagicMock()


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_deployment_config_defaults_to_alpha():
    cfg = DeploymentConfig()
    assert cfg.channel == "alpha"
    assert cfg.pinned_minor == ""


def test_deployment_config_beta_no_pinned_minor_required():
    cfg = DeploymentConfig(channel="beta")
    assert cfg.channel == "beta"


def test_deployment_config_stable_requires_pinned_minor():
    with pytest.raises(Exception, match="pinned_minor"):
        DeploymentConfig(channel="stable")


def test_deployment_config_stable_with_pinned_minor_ok():
    cfg = DeploymentConfig(channel="stable", pinned_minor="1.2")
    assert cfg.channel == "stable"
    assert cfg.pinned_minor == "1.2"


def test_project_config_includes_deployment_defaults():
    cfg = ProjectConfig()
    assert isinstance(cfg.deployment, DeploymentConfig)
    assert cfg.deployment.channel == "alpha"


# ---------------------------------------------------------------------------
# Handler helpers
# ---------------------------------------------------------------------------


def _github_push_event(ref: str = "refs/heads/main") -> HookEvent:
    return HookEvent.now(source="github", type="push", properties={"ref": ref})


def _github_release_event(action: str = "published", tag: str = "v1.2.3") -> HookEvent:
    return HookEvent.now(
        source="github",
        type="release",
        properties={"action": action},
        payload={"release": {"tag_name": tag}},
    )


def _deployment_fanout_event(channel: str = "alpha", version: str = "") -> HookEvent:
    return HookEvent.now(
        source="deployment",
        type="version_available",
        properties={"channel": channel, "version": version, "from_version": "0.0.0"},
    )


def _make_project_config_raw(channel: str, pinned_minor: str = "") -> Any:
    cfg = MagicMock()
    cfg.deployment.channel = channel
    cfg.deployment.pinned_minor = pinned_minor
    return cfg


# ---------------------------------------------------------------------------
# Handler decision logic — alpha
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_alpha_push_to_main_triggers_update():
    event = _github_push_event("refs/heads/main")
    cfg = _make_project_config_raw("alpha")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", None),
        patch("asyncio.create_task", side_effect=_create_task_closing_coro) as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert mock_task.called


@pytest.mark.asyncio
async def test_handler_alpha_push_to_feature_branch_skips():
    event = _github_push_event("refs/heads/feature/foo")
    cfg = _make_project_config_raw("alpha")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("asyncio.create_task") as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert not mock_task.called


# ---------------------------------------------------------------------------
# Handler decision logic — beta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_beta_release_published_triggers_update():
    event = _github_release_event("published", "v1.2.3")
    cfg = _make_project_config_raw("beta")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", None),
        patch("asyncio.create_task", side_effect=_create_task_closing_coro) as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert mock_task.called


@pytest.mark.asyncio
async def test_handler_beta_release_created_skips():
    event = _github_release_event("created", "v1.2.3")
    cfg = _make_project_config_raw("beta")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("asyncio.create_task") as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert not mock_task.called


# ---------------------------------------------------------------------------
# Handler decision logic — stable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_stable_release_within_pinned_minor_triggers_update():
    event = _github_release_event("published", "v1.2.5")
    cfg = _make_project_config_raw("stable", "1.2")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", None),
        patch("asyncio.create_task", side_effect=_create_task_closing_coro) as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert mock_task.called


@pytest.mark.asyncio
async def test_handler_stable_release_outside_pinned_minor_skips():
    event = _github_release_event("published", "v1.3.0")
    cfg = _make_project_config_raw("stable", "1.2")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("asyncio.create_task") as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert not mock_task.called


# ---------------------------------------------------------------------------
# Handler skips irrelevant events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_skips_unknown_source():
    event = HookEvent.now(source="unknown", type="push")
    cfg = _make_project_config_raw("alpha")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("asyncio.create_task") as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert not mock_task.called


@pytest.mark.asyncio
async def test_handler_alpha_push_skips_release_events():
    event = _github_release_event("published")
    cfg = _make_project_config_raw("alpha")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("asyncio.create_task") as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert not mock_task.called


# ---------------------------------------------------------------------------
# Fan-out: github source publishes, deployment source does not
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_github_source_publishes_fanout():
    event = _github_push_event("refs/heads/main")
    cfg = _make_project_config_raw("alpha")

    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock()

    async def _get_redis_fn() -> Any:
        return mock_redis

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", _get_redis_fn),
        patch("asyncio.create_task", side_effect=_create_task_closing_coro),
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        mock_redis.xadd.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_deployment_source_does_not_publish_fanout():
    event = _deployment_fanout_event("alpha", "")
    cfg = _make_project_config_raw("alpha")

    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock()

    async def _get_redis_fn() -> Any:
        return mock_redis

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", _get_redis_fn),
        patch("asyncio.create_task", side_effect=_create_task_closing_coro),
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        mock_redis.xadd.assert_not_awaited()


# ---------------------------------------------------------------------------
# Executor — alpha path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_alpha_runs_git_pull_and_install(tmp_path, monkeypatch):
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)

    # Fake pyproject.toml so _read_version_from_pyproject doesn't crash.
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    async def _fake_exec(*args: Any, **kwargs: Any) -> Any:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        return proc

    async def _fake_wait_for(coro: Any, timeout: float) -> Any:  # noqa: ASYNC109
        return await coro

    run_migrations_mock = MagicMock(return_value={"migrations_run": 0, "migrations_skipped": 0})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        patch("asyncio.wait_for", side_effect=_fake_wait_for),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("alpha", {"from_version": "1.0.0", "version": ""})
        mock_exit.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# Executor — beta/stable path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_beta_runs_fetch_and_checkout(tmp_path, monkeypatch):
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    calls: list[tuple[str, ...]] = []

    async def _fake_exec(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        return proc

    async def _fake_wait_for(coro: Any, timeout: float) -> Any:  # noqa: ASYNC109
        return await coro

    run_migrations_mock = MagicMock(return_value={"migrations_run": 0, "migrations_skipped": 0})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        patch("asyncio.wait_for", side_effect=_fake_wait_for),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("beta", {"from_version": "1.0.0", "version": "1.2.3"})
        mock_exit.assert_called_once_with(42)

    # Should have called git fetch --tags and git checkout v1.2.3
    git_commands = [c for c in calls if c[0] == "git"]
    assert any("fetch" in c for c in git_commands)
    assert any("checkout" in c for c in git_commands)


# ---------------------------------------------------------------------------
# Executor — migration failure halts update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_migration_failure_halts_update(tmp_path, monkeypatch):
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    async def _fake_exec(*args: Any, **kwargs: Any) -> Any:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        return proc

    run_migrations_mock = MagicMock(return_value={"error": "migration script exploded"})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("alpha", {"from_version": "1.0.0", "version": ""})
        mock_exit.assert_not_called()


# ---------------------------------------------------------------------------
# _is_within_pinned_minor helper
# ---------------------------------------------------------------------------


def test_is_within_pinned_minor_accepts_matching_patch():
    from teleclaude.deployment.handler import _is_within_pinned_minor

    assert _is_within_pinned_minor("1.2.5", "1.2") is True
    assert _is_within_pinned_minor("1.2.0", "1.2") is True


def test_is_within_pinned_minor_rejects_different_minor():
    from teleclaude.deployment.handler import _is_within_pinned_minor

    assert _is_within_pinned_minor("1.3.0", "1.2") is False
    assert _is_within_pinned_minor("2.2.0", "1.2") is False


def test_is_within_pinned_minor_rejects_empty_strings():
    from teleclaude.deployment.handler import _is_within_pinned_minor

    assert _is_within_pinned_minor("", "1.2") is False
    assert _is_within_pinned_minor("1.2.3", "") is False
