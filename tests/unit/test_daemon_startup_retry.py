"""Unit tests for daemon startup retry logic."""

import os
import uuid
from unittest.mock import patch

import pytest

from teleclaude.daemon import (
    STARTUP_MAX_RETRIES,
    STARTUP_RETRY_DELAYS,
    _is_retryable_startup_error,
)


class TestIsRetryableStartupError:
    """Test _is_retryable_startup_error() function."""

    def test_network_error_is_retryable(self):
        """NetworkError (from Telegram library) should be retryable."""

        class NetworkError(Exception):
            pass

        error = NetworkError("Connection failed")
        assert _is_retryable_startup_error(error) is True

    def test_connect_error_is_retryable(self):
        """ConnectError (from httpx) should be retryable."""

        class ConnectError(Exception):
            pass

        error = ConnectError("Failed to connect")
        assert _is_retryable_startup_error(error) is True

    def test_timeout_error_is_retryable(self):
        """TimeoutError should be retryable."""
        error = TimeoutError("Connection timed out")
        assert _is_retryable_startup_error(error) is True

    def test_os_error_is_retryable(self):
        """OSError (network socket errors) should be retryable."""
        error = OSError("Network is unreachable")
        assert _is_retryable_startup_error(error) is True

    def test_dns_resolution_failure_is_retryable(self):
        """DNS resolution failures should be retryable by message content."""
        error = Exception("getaddrinfo failed: name resolution failed")
        assert _is_retryable_startup_error(error) is True

    def test_connection_refused_is_retryable(self):
        """Connection refused errors should be retryable by message content."""
        error = Exception("Connection refused by server")
        assert _is_retryable_startup_error(error) is True

    def test_timed_out_message_is_retryable(self):
        """Errors with 'timed out' in message should be retryable."""
        error = Exception("Request timed out after 30s")
        assert _is_retryable_startup_error(error) is True

    def test_temporary_failure_is_retryable(self):
        """Temporary failures should be retryable by message content."""
        error = Exception("Temporary failure in name resolution")
        assert _is_retryable_startup_error(error) is True

    def test_value_error_is_not_retryable(self):
        """ValueError (config errors) should NOT be retryable."""
        error = ValueError("Invalid configuration")
        assert _is_retryable_startup_error(error) is False

    def test_key_error_is_not_retryable(self):
        """KeyError (missing config) should NOT be retryable."""
        error = KeyError("missing_key")
        assert _is_retryable_startup_error(error) is False

    def test_runtime_error_is_not_retryable(self):
        """RuntimeError (general errors) should NOT be retryable."""
        error = RuntimeError("Something went wrong")
        assert _is_retryable_startup_error(error) is False

    def test_generic_exception_is_not_retryable(self):
        """Generic Exception without network keywords should NOT be retryable."""
        error = Exception("Authentication failed: invalid token")
        assert _is_retryable_startup_error(error) is False

    def test_case_insensitive_message_matching(self):
        """Message matching should be case-insensitive."""
        error = Exception("NAME RESOLUTION FAILED")
        assert _is_retryable_startup_error(error) is True

        error2 = Exception("TIMED OUT waiting for response")
        assert _is_retryable_startup_error(error2) is True


class TestStartupRetryConstants:
    """Test startup retry configuration constants."""

    def test_max_retries_is_three(self):
        """Verify max retries is configured to 3."""
        assert STARTUP_MAX_RETRIES == 3

    def test_retry_delays_exponential_backoff(self):
        """Verify retry delays follow exponential backoff."""
        assert STARTUP_RETRY_DELAYS == [10, 20, 40]

    def test_retry_delays_length_matches_max_retries(self):
        """Verify enough delay values for all retry attempts."""
        assert len(STARTUP_RETRY_DELAYS) == STARTUP_MAX_RETRIES


class TestDaemonStartupRetryIntegration:
    """Integration tests for daemon startup retry with network failures."""

    @pytest.mark.asyncio
    async def test_voice_handler_not_initialized_on_network_failure(self, monkeypatch, tmp_path):
        """Verify voice handler is not initialized if network connection fails.

        This test ensures the fix for the bug where voice handler was initialized
        before network operations, causing retry failures.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        # Isolate API socket path so this test never touches production daemon socket.
        from teleclaude import api_server as api_server_module
        from teleclaude import constants as constants_module
        from teleclaude.daemon import TeleClaudeDaemon

        temp_api_socket = f"/tmp/teleclaude-unit-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
        monkeypatch.setattr(constants_module, "API_SOCKET_PATH", temp_api_socket)
        monkeypatch.setattr(api_server_module, "API_SOCKET_PATH", temp_api_socket)

        with (
            patch("teleclaude.daemon.db") as mock_db,
            patch("teleclaude.daemon.config") as mock_config,
            patch("teleclaude.daemon.init_voice_handler") as mock_init_voice,
            patch.object(TeleClaudeDaemon, "_acquire_lock"),
        ):
            # Setup mocks
            mock_db.initialize = AsyncMock()
            mock_db.set_client = MagicMock()
            mock_db.get_active_sessions = AsyncMock(return_value=[])
            mock_db.get_ux_state = AsyncMock()
            mock_config.mcp.enabled = False

            # Create daemon
            daemon = TeleClaudeDaemon(".env.test")

            # Mock client.start() to fail (network error)
            daemon.client.start = AsyncMock(side_effect=ConnectionError("Network unreachable"))

            # Attempt to start daemon (should fail)
            with pytest.raises(ConnectionError):
                await daemon.start()

            # Verify voice handler was NOT initialized (network failed first)
            mock_init_voice.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires port 8420 free — fails when daemon is running")
    async def test_voice_handler_initialized_after_network_success(self, monkeypatch, tmp_path):
        """Verify voice handler is initialized only after network connection succeeds."""
        from unittest.mock import AsyncMock, MagicMock, patch

        # Isolate API socket path so this test never touches production daemon socket.
        from teleclaude import api_server as api_server_module
        from teleclaude import constants as constants_module
        from teleclaude.daemon import TeleClaudeDaemon

        temp_api_socket = f"/tmp/teleclaude-unit-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
        monkeypatch.setattr(constants_module, "API_SOCKET_PATH", temp_api_socket)
        monkeypatch.setattr(api_server_module, "API_SOCKET_PATH", temp_api_socket)

        with (
            patch("teleclaude.daemon.db") as mock_db,
            patch("teleclaude.daemon.config") as mock_config,
            patch("teleclaude.daemon.init_voice_handler") as mock_init_voice,
            patch("teleclaude.daemon.polling_coordinator") as mock_polling,
            patch.object(TeleClaudeDaemon, "_acquire_lock"),
            patch("teleclaude.daemon.MaintenanceService.periodic_cleanup", new_callable=AsyncMock),
            patch("teleclaude.daemon.MaintenanceService.poller_watch_loop", new_callable=AsyncMock),
        ):
            # Setup mocks
            mock_db.initialize = AsyncMock()
            mock_db.set_client = MagicMock()
            mock_db.get_active_sessions = AsyncMock(return_value=[])
            mock_db.get_ux_state = AsyncMock()
            mock_config.mcp.enabled = False
            mock_polling.restore_active_pollers = AsyncMock()

            # Create daemon
            daemon = TeleClaudeDaemon(".env.test")

            # Mock successful network connection
            daemon.client.start = AsyncMock()

            # Start daemon (should succeed)
            await daemon.start()

            # Verify voice handler WAS initialized (after network succeeded)
            assert mock_init_voice.call_count == 1

    @pytest.mark.asyncio
    async def test_voice_handler_idempotent_on_retry(self):
        """Verify voice handler init is idempotent and safe to call on retry.

        Even though we reordered initialization, this test ensures the voice
        handler itself is defensive and won't crash if accidentally called twice.
        """
        from teleclaude.core import voice_message_handler

        with patch.dict("os.environ", {}, clear=True):
            # First initialization sets the env var
            voice_message_handler.init_voice_handler(api_key="test-key")
            assert os.environ.get("OPENAI_API_KEY") == "test-key"

            # Second initialization (simulating retry) - should not overwrite
            voice_message_handler.init_voice_handler(api_key="different-key")
            assert os.environ.get("OPENAI_API_KEY") == "test-key"  # Still original
