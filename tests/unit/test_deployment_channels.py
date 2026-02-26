"""Tests for deployment channel config, handler decision logic, executor paths, and fan-out."""

from __future__ import annotations

import asyncio
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
    # Regression: "1.20.0".startswith("1.2.") is True — must be rejected
    assert _is_within_pinned_minor("1.20.0", "1.2") is False


def test_is_within_pinned_minor_rejects_empty_strings():
    from teleclaude.deployment.handler import _is_within_pinned_minor

    assert _is_within_pinned_minor("", "1.2") is False
    assert _is_within_pinned_minor("1.2.3", "") is False


# ---------------------------------------------------------------------------
# Executor — error path tests (fix #6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_alpha_git_pull_failure_halts_update(tmp_path, monkeypatch):
    """git pull --ff-only failure should abort before migrations and install."""
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    async def _fail_exec(*args: Any, **kwargs: Any) -> Any:
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"not a fast-forward"))
        return proc

    run_migrations_mock = MagicMock(return_value={"migrations_run": 0})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fail_exec),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("alpha", {"from_version": "1.0.0", "version": ""})
        mock_exit.assert_not_called()
        run_migrations_mock.assert_not_called()


@pytest.mark.asyncio
async def test_executor_beta_git_fetch_failure_halts_update(tmp_path, monkeypatch):
    """git fetch --tags failure should abort before checkout, migrations, and install."""
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)

    async def _fail_exec(*args: Any, **kwargs: Any) -> Any:
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"fetch error"))
        return proc

    run_migrations_mock = MagicMock(return_value={"migrations_run": 0})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fail_exec),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("beta", {"from_version": "1.0.0", "version": "1.2.3"})
        mock_exit.assert_not_called()
        run_migrations_mock.assert_not_called()


@pytest.mark.asyncio
async def test_executor_beta_git_checkout_failure_halts_update(tmp_path, monkeypatch):
    """git checkout failure after successful fetch should abort before migrations."""
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)

    call_count = 0

    async def _fetch_ok_checkout_fail(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        proc = MagicMock()
        proc.returncode = 0 if call_count == 1 else 1  # fetch ok, checkout fails
        proc.communicate = AsyncMock(return_value=(b"", b"" if call_count == 1 else b"pathspec error"))
        return proc

    run_migrations_mock = MagicMock(return_value={"migrations_run": 0})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fetch_ok_checkout_fail),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("beta", {"from_version": "1.0.0", "version": "1.2.3"})
        mock_exit.assert_not_called()
        run_migrations_mock.assert_not_called()


@pytest.mark.asyncio
async def test_executor_make_install_failure_halts_update(tmp_path, monkeypatch):
    """make install non-zero exit code should abort before restart."""
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    call_count = 0

    async def _git_ok_make_fail(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        proc = MagicMock()
        proc.returncode = 0 if args[0] == "git" else 1
        proc.communicate = AsyncMock(return_value=(b"", b"" if args[0] == "git" else b"make: *** error"))
        return proc

    async def _fake_wait_for(coro: Any, timeout: float) -> Any:  # noqa: ASYNC109
        return await coro

    run_migrations_mock = MagicMock(return_value={"migrations_run": 0, "migrations_skipped": 0})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_git_ok_make_fail),
        patch("asyncio.wait_for", side_effect=_fake_wait_for),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("alpha", {"from_version": "1.0.0", "version": ""})
        mock_exit.assert_not_called()


@pytest.mark.asyncio
async def test_executor_make_install_timeout_halts_update(tmp_path, monkeypatch):
    """make install timeout should abort before restart."""
    import teleclaude.deployment.executor as executor_mod

    monkeypatch.setattr(executor_mod, "_REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    async def _git_ok(*args: Any, **kwargs: Any) -> Any:
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        return proc

    async def _timeout(*args: Any, **kwargs: Any) -> Any:  # noqa: ASYNC109
        raise asyncio.TimeoutError

    run_migrations_mock = MagicMock(return_value={"migrations_run": 0, "migrations_skipped": 0})

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_git_ok),
        patch("asyncio.wait_for", side_effect=_timeout),
        patch("teleclaude.deployment.executor.run_migrations", run_migrations_mock),
        patch("os._exit") as mock_exit,
    ):
        from teleclaude.deployment.executor import execute_update

        await execute_update("alpha", {"from_version": "1.0.0", "version": ""})
        mock_exit.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: HookEvent -> handler -> execute_update argument wire-up (fix #7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_github_event_invokes_execute_update_with_correct_args():
    """execute_update receives the channel and version_info built by the handler."""
    event = _github_push_event("refs/heads/main")
    cfg = _make_project_config_raw("alpha")

    # Capture args synchronously — the coroutine body is closed by _create_task_closing_coro
    # before it runs, so we record in the sync wrapper that returns the coroutine.
    captured: list[tuple[str, dict]] = []  # type: ignore[type-arg]

    async def _noop() -> None:
        pass

    def _sync_capture(channel: str, version_info: dict, **kwargs: Any) -> Any:
        captured.append((channel, dict(version_info)))
        return _noop()

    execute_mock = MagicMock(side_effect=_sync_capture)

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", None),
        patch("teleclaude.deployment.executor.execute_update", execute_mock),
        patch("asyncio.create_task", side_effect=_create_task_closing_coro),
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)

    assert len(captured) == 1, "execute_update should be called exactly once"
    channel, version_info = captured[0]
    assert channel == "alpha"
    assert version_info["channel"] == "alpha"
    assert "from_version" in version_info


@pytest.mark.asyncio
async def test_integration_beta_release_invokes_execute_update_with_version():
    """Beta release event passes the correct version tag to execute_update."""
    event = _github_release_event("published", "v1.2.3")
    cfg = _make_project_config_raw("beta")

    captured: list[tuple[str, dict]] = []  # type: ignore[type-arg]

    async def _noop() -> None:
        pass

    def _sync_capture(channel: str, version_info: dict, **kwargs: Any) -> Any:
        captured.append((channel, dict(version_info)))
        return _noop()

    execute_mock = MagicMock(side_effect=_sync_capture)

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", None),
        patch("teleclaude.deployment.executor.execute_update", execute_mock),
        patch("asyncio.create_task", side_effect=_create_task_closing_coro),
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)

    assert len(captured) == 1
    channel, version_info = captured[0]
    assert channel == "beta"
    assert version_info["version"] == "1.2.3"


# ---------------------------------------------------------------------------
# Fan-out decision logic for deployment source (fix #8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_deployment_source_alpha_triggers_execute_update():
    """Alpha fan-out event on an alpha node should trigger execute_update."""
    event = _deployment_fanout_event("alpha", "")
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
async def test_handler_deployment_source_channel_mismatch_skips():
    """Beta fan-out event received on an alpha node should not trigger an update."""
    event = _deployment_fanout_event("beta", "1.2.3")
    cfg = _make_project_config_raw("alpha")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", None),
        patch("asyncio.create_task") as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert not mock_task.called


@pytest.mark.asyncio
async def test_handler_deployment_source_beta_with_version_triggers_update():
    """Beta fan-out with a non-empty version triggers execute_update on a beta node."""
    event = _deployment_fanout_event("beta", "1.2.3")
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
async def test_handler_deployment_source_stable_within_pinned_minor_triggers_update():
    """Stable fan-out with version in pinned minor triggers execute_update on stable node."""
    event = _deployment_fanout_event("stable", "1.2.5")
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
async def test_handler_deployment_source_stable_outside_pinned_minor_skips():
    """Stable fan-out with version outside pinned minor does not trigger update."""
    event = _deployment_fanout_event("stable", "1.3.0")
    cfg = _make_project_config_raw("stable", "1.2")

    with (
        patch("teleclaude.config.loader.load_project_config", return_value=cfg),
        patch("teleclaude.deployment.handler.resolve_project_config_path", return_value=Path("/fake")),
        patch("teleclaude.deployment.handler._get_redis", None),
        patch("asyncio.create_task") as mock_task,
    ):
        from teleclaude.deployment.handler import handle_deployment_event

        await handle_deployment_event(event)
        assert not mock_task.called
