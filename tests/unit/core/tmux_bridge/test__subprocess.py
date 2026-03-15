"""Characterization tests for tmux bridge subprocess timeouts."""

from __future__ import annotations

import asyncio

import pytest

from teleclaude.core.tmux_bridge import _subprocess


class FakeWaitProcess:
    def __init__(self, *, pid: int = 101) -> None:
        self.pid = pid
        self.killed = False

    async def wait(self) -> None:
        if self.killed:
            return None
        await asyncio.sleep(0.2)
        return None

    def kill(self) -> None:
        self.killed = True


class FakeLookupErrorProcess(FakeWaitProcess):
    def kill(self) -> None:
        raise ProcessLookupError


class FakeImmediateWaitProcess(FakeWaitProcess):
    async def wait(self) -> None:
        return None


class FakeCommunicateProcess(FakeWaitProcess):
    def __init__(self, *, pid: int = 101, output: tuple[bytes, bytes] = (b"stdout", b"stderr")) -> None:
        super().__init__(pid=pid)
        self.output = output
        self.received_input: bytes | None = None

    async def communicate(self, input_data: bytes | None = None) -> tuple[bytes, bytes]:
        self.received_input = input_data
        if self.killed:
            return (b"", b"")
        await asyncio.sleep(0.2)
        return self.output


class FakeImmediateCommunicateProcess(FakeCommunicateProcess):
    async def communicate(self, input_data: bytes | None = None) -> tuple[bytes, bytes]:
        self.received_input = input_data
        return self.output


class TestSubprocessTimeoutError:
    @pytest.mark.unit
    def test_timeout_error_exposes_operation_timeout_and_pid(self) -> None:
        error = _subprocess.SubprocessTimeoutError("tmux wait", 1.5, 321)

        assert error.operation == "tmux wait"
        assert error.timeout == 1.5
        assert error.pid == 321


class TestWaitWithTimeout:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wait_with_timeout_returns_when_process_finishes_before_deadline(self) -> None:
        process = FakeImmediateWaitProcess()

        await _subprocess.wait_with_timeout(process, timeout=0.05, operation="tmux wait")

        assert process.killed is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wait_with_timeout_kills_the_process_and_raises_on_timeout(self) -> None:
        process = FakeWaitProcess(pid=654)

        with pytest.raises(_subprocess.SubprocessTimeoutError) as exc_info:
            await _subprocess.wait_with_timeout(process, timeout=0.01, operation="tmux wait")

        assert exc_info.value.operation == "tmux wait"
        assert exc_info.value.timeout == 0.01
        assert exc_info.value.pid == 654
        assert process.killed is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wait_with_timeout_still_raises_when_process_is_already_gone(self) -> None:
        process = FakeLookupErrorProcess(pid=777)

        with pytest.raises(_subprocess.SubprocessTimeoutError) as exc_info:
            await _subprocess.wait_with_timeout(process, timeout=0.01, operation="tmux wait")

        assert exc_info.value.pid == 777


class TestCommunicateWithTimeout:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_communicate_with_timeout_returns_stdout_and_stderr(self) -> None:
        process = FakeImmediateCommunicateProcess(output=(b"alpha", b"beta"))

        result = await _subprocess.communicate_with_timeout(
            process,
            input_data=b"payload",
            timeout=0.05,
            operation="tmux communicate",
        )

        assert result == (b"alpha", b"beta")
        assert process.received_input == b"payload"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_communicate_with_timeout_kills_the_process_and_raises_on_timeout(self) -> None:
        process = FakeCommunicateProcess(pid=808)

        with pytest.raises(_subprocess.SubprocessTimeoutError) as exc_info:
            await _subprocess.communicate_with_timeout(
                process,
                input_data=b"payload",
                timeout=0.01,
                operation="tmux communicate",
            )

        assert exc_info.value.operation == "tmux communicate"
        assert exc_info.value.timeout == 0.01
        assert exc_info.value.pid == 808
        assert process.received_input == b"payload"
        assert process.killed is True
