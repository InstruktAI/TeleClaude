# guard: no-companion
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
"""Test spec (xfail) for daemon internal watcher route - R2.1-R2.7, R6.1.

Covers authentication, project trust verification, server-side re-filtering,
stale preparation invalidation, single recomputation per batch, digest-gated
emission, and transport constraints. All tests are marked xfail.
"""
# pylint: disable=import-outside-toplevel,missing-function-docstring,too-few-public-methods

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# R2.1 — Authentication
# ---------------------------------------------------------------------------


class TestWatcherRouteAuthentication:
    """The route authenticates using a watcher-specific secret."""

    async def test_valid_secret_accepted(self) -> None:
        """Request with the correct watcher secret receives 200."""
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        request = _make_request(
            secret="valid-secret-abc",
            project_root="/home/user/project",
            changed_paths=["todos/my-slug/state.yaml"],
        )
        with _mock_secret_lookup("valid-secret-abc"), _mock_trusted_dir("/home/user/project"):
            response = await handle_watcher_notification(request)
        assert response.status_code == 200

    async def test_invalid_secret_rejected(self) -> None:
        """Request with wrong secret receives 403 or 401."""
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        request = _make_request(
            secret="wrong-secret",
            project_root="/home/user/project",
            changed_paths=["todos/my-slug/state.yaml"],
        )
        with _mock_secret_lookup("valid-secret-abc"):
            response = await handle_watcher_notification(request)
        assert response.status_code in (401, 403)

    async def test_missing_secret_rejected(self) -> None:
        """Request with no secret receives 403 or 401."""
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        request = _make_request(
            secret=None,
            project_root="/home/user/project",
            changed_paths=["todos/my-slug/state.yaml"],
        )
        with _mock_secret_lookup("valid-secret-abc"):
            response = await handle_watcher_notification(request)
        assert response.status_code in (401, 403)

    async def test_rejection_does_not_leak_valid_secret(self) -> None:
        """Error response body must not contain the valid secret value."""
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        request = _make_request(
            secret="wrong",
            project_root="/home/user/project",
            changed_paths=["todos/my-slug/state.yaml"],
        )
        valid = "super-secret-value-12345"
        with _mock_secret_lookup(valid):
            response = await handle_watcher_notification(request)
        body = _extract_body(response)
        assert valid not in body


# ---------------------------------------------------------------------------
# R2.2 — Project Trust Verification
# ---------------------------------------------------------------------------


class TestProjectTrustVerification:
    """The route verifies project_root belongs to a trusted directory."""

    async def test_trusted_project_accepted(self) -> None:
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        request = _make_request(
            secret="valid",
            project_root="/home/user/trusted-project",
            changed_paths=["todos/slug/state.yaml"],
        )
        with _mock_secret_lookup("valid"), _mock_trusted_dir("/home/user/trusted-project"):
            response = await handle_watcher_notification(request)
        assert response.status_code == 200

    async def test_untrusted_project_rejected(self) -> None:
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        request = _make_request(
            secret="valid",
            project_root="/tmp/untrusted",
            changed_paths=["todos/slug/state.yaml"],
        )
        with _mock_secret_lookup("valid"), _mock_no_trusted_dirs():
            response = await handle_watcher_notification(request)
        assert response.status_code in (403, 422)


# ---------------------------------------------------------------------------
# R2.3 — Server-Side Path Re-filtering
# ---------------------------------------------------------------------------


class TestServerSideRefiltering:
    """The daemon re-applies the path allowlist against reported changed_paths."""

    async def test_non_matching_paths_stripped_server_side(self) -> None:
        """Paths that don't match R1.5 allowlist are removed before processing."""
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        recompute_mock = AsyncMock()
        request = _make_request(
            secret="valid",
            project_root="/project",
            changed_paths=[
                "todos/slug/state.yaml",  # matches
                "src/main.py",  # does NOT match
                "todos/slug/data.json",  # does NOT match
            ],
        )
        with (
            _mock_secret_lookup("valid"),
            _mock_trusted_dir("/project"),
            _mock_recompute(recompute_mock),
        ):
            await handle_watcher_notification(request)

        # Only the valid path should reach recomputation
        recompute_mock.assert_called_once()
        call_paths = _extract_recompute_paths(recompute_mock)
        assert "todos/slug/state.yaml" in call_paths
        assert "src/main.py" not in call_paths
        assert "todos/slug/data.json" not in call_paths

    async def test_all_paths_filtered_out_produces_no_recomputation(self) -> None:
        """If re-filtering removes all paths, no recomputation occurs."""
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        recompute_mock = AsyncMock()
        request = _make_request(
            secret="valid",
            project_root="/project",
            changed_paths=["src/main.py", "README.md"],
        )
        with (
            _mock_secret_lookup("valid"),
            _mock_trusted_dir("/project"),
            _mock_recompute(recompute_mock),
        ):
            await handle_watcher_notification(request)

        recompute_mock.assert_not_called()


# ---------------------------------------------------------------------------
# R2.4 — Stale Preparation Invalidation
# ---------------------------------------------------------------------------


class TestStalePreparationInvalidation:
    """Paths affecting stale-preparation logic trigger invalidation."""

    async def test_state_yaml_change_triggers_invalidation(self) -> None:
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        invalidation_mock = AsyncMock()
        request = _make_request(
            secret="valid",
            project_root="/project",
            changed_paths=["todos/my-slug/state.yaml"],
        )
        with (
            _mock_secret_lookup("valid"),
            _mock_trusted_dir("/project"),
            _mock_invalidation(invalidation_mock),
        ):
            await handle_watcher_notification(request)

        invalidation_mock.assert_called()

    async def test_requirements_change_triggers_invalidation(self) -> None:
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        invalidation_mock = AsyncMock()
        request = _make_request(
            secret="valid",
            project_root="/project",
            changed_paths=["todos/my-slug/requirements.md"],
        )
        with (
            _mock_secret_lookup("valid"),
            _mock_trusted_dir("/project"),
            _mock_invalidation(invalidation_mock),
        ):
            await handle_watcher_notification(request)

        invalidation_mock.assert_called()


# ---------------------------------------------------------------------------
# R2.5 — Single Recomputation Per Notification
# ---------------------------------------------------------------------------


class TestSingleRecomputation:
    """The daemon recomputes the todo snapshot exactly once per batch."""

    async def test_multiple_paths_trigger_one_recomputation(self) -> None:
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        recompute_mock = AsyncMock()
        request = _make_request(
            secret="valid",
            project_root="/project",
            changed_paths=[
                "todos/slug-a/state.yaml",
                "todos/slug-b/requirements.md",
                "todos/roadmap.yaml",
            ],
        )
        with (
            _mock_secret_lookup("valid"),
            _mock_trusted_dir("/project"),
            _mock_recompute(recompute_mock),
        ):
            await handle_watcher_notification(request)

        assert recompute_mock.call_count == 1


# ---------------------------------------------------------------------------
# R2.6 — Digest-Gated Emission
# ---------------------------------------------------------------------------


class TestDigestGatedEmission:
    """Cache/WebSocket updates only when snapshot digest actually changes."""

    async def test_changed_digest_triggers_emission(self) -> None:
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        emission_mock = MagicMock()
        request = _make_request(
            secret="valid",
            project_root="/project",
            changed_paths=["todos/slug/state.yaml"],
        )
        with (
            _mock_secret_lookup("valid"),
            _mock_trusted_dir("/project"),
            _mock_snapshot_digest_changed(True),
            _mock_emission(emission_mock),
        ):
            await handle_watcher_notification(request)

        emission_mock.assert_called()

    async def test_unchanged_digest_suppresses_emission(self) -> None:
        from teleclaude.api.todo_watcher_routes import handle_watcher_notification

        emission_mock = MagicMock()
        request = _make_request(
            secret="valid",
            project_root="/project",
            changed_paths=["todos/slug/state.yaml"],
        )
        with (
            _mock_secret_lookup("valid"),
            _mock_trusted_dir("/project"),
            _mock_snapshot_digest_changed(False),
            _mock_emission(emission_mock),
        ):
            await handle_watcher_notification(request)

        emission_mock.assert_not_called()


# ---------------------------------------------------------------------------
# R2.7 — Transport (Unix socket)
# ---------------------------------------------------------------------------


class TestTransport:
    """Watcher notifications travel over local Unix socket, not TCP/public surface."""

    def test_tcp_requests_rejected_on_api_server_surface(self, tmp_path: Path) -> None:
        """The shared FastAPI app must reject watcher posts that arrive over TCP."""
        from teleclaude.api_server import APIServer

        with _mock_secret_lookup("valid"), _mock_trusted_dir("/project"):
            server = APIServer(
                client=MagicMock(adapters={}),
                cache=None,
                socket_path=str(tmp_path / "api.sock"),
            )
            client = TestClient(server.app)
            response = client.post(
                "/internal/watcher-notification",
                json={
                    "project_root": "/project",
                    "changed_paths": ["todos/slug/state.yaml"],
                },
                headers={"X-Watcher-Secret": "valid"},
            )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# R6.1 — Rollout Safety: new route functional independently
# ---------------------------------------------------------------------------


class TestRolloutSafety:
    """The new watcher route is functional before the old watcher is removed."""

    def test_route_is_importable_and_has_handler(self) -> None:
        """The route module can be imported and exposes a handler function."""
        from teleclaude.api import todo_watcher_routes

        assert hasattr(todo_watcher_routes, "router")


# ---------------------------------------------------------------------------
# Test helpers — mock scaffolding
# ---------------------------------------------------------------------------


def _make_request(
    secret: str | None,
    project_root: str,
    changed_paths: list[str],
    *,
    client: tuple[str, int] | None = None,
) -> MagicMock:
    """Build a mock request object for watcher notification tests."""
    request = MagicMock()
    request.headers = {}
    request.scope = {"client": client}
    if secret is not None:
        request.headers["X-Watcher-Secret"] = secret
    request.json = AsyncMock(
        return_value={
            "project_root": project_root,
            "changed_paths": changed_paths,
        }
    )
    return request


def _mock_secret_lookup(valid_secret: str) -> object:
    """Context manager that mocks the secret validation to accept the given value."""
    return patch(
        "teleclaude.api.todo_watcher_routes._get_watcher_secret",
        return_value=valid_secret,
    )


def _mock_trusted_dir(project_root: str) -> object:
    """Context manager that mocks trusted-dir verification to accept the given root."""
    td = MagicMock()
    td.path = project_root
    return patch(
        "teleclaude.api.todo_watcher_routes._get_trusted_dirs",
        return_value=[td],
    )


def _mock_no_trusted_dirs() -> object:
    return patch(
        "teleclaude.api.todo_watcher_routes._get_trusted_dirs",
        return_value=[],
    )


def _mock_recompute(mock: AsyncMock) -> object:
    return patch(
        "teleclaude.api.todo_watcher_routes._recompute_todos",
        mock,
    )


def _mock_invalidation(mock: AsyncMock) -> object:
    return patch(
        "teleclaude.api.todo_watcher_routes._invalidate_stale_preparations",
        mock,
    )


def _mock_snapshot_digest_changed(changed: bool) -> object:
    return patch(
        "teleclaude.api.todo_watcher_routes._apply_snapshot_with_digest_check",
        return_value=changed,
    )


def _mock_emission(mock: MagicMock) -> object:
    return patch(
        "teleclaude.api.todo_watcher_routes._emit_change_event",
        mock,
    )


def _extract_body(response: MagicMock) -> str:
    """Extract response body as string for leakage checks."""
    if hasattr(response, "body"):
        return str(response.body)
    return str(response)


def _extract_recompute_paths(mock: AsyncMock) -> list[str]:
    """Extract the paths argument from a recompute mock call."""
    args, kwargs = mock.call_args
    # Accept both positional and keyword
    if "changed_paths" in kwargs:
        return list(kwargs["changed_paths"])
    # Second positional arg after project_root
    return list(args[1]) if len(args) > 1 else list(args[0])
