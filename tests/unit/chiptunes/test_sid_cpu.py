"""Characterization tests for teleclaude.chiptunes.sid_cpu."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

import teleclaude.chiptunes.sid_cpu as sid_cpu
from teleclaude.chiptunes.sid_parser import SIDHeader


class _ScriptedCPU:
    script: list[Callable[[_ScriptedCPU], None]] = []

    def __init__(self, mmu: sid_cpu.SIDInterceptMMU) -> None:
        self._mmu = mmu
        self._script = list(type(self).script)
        self.r = SimpleNamespace(a=0, x=0, y=0, pc=0)
        self.cc = 0
        self.stack_words: list[int] = []

    def stackPushWord(self, word: int) -> None:
        self.stack_words.append(word)

    def step(self) -> None:
        self.cc += 1
        if not self._script:
            self.r.pc = sid_cpu._SENTINEL_ADDR
            return
        action = self._script.pop(0)
        action(self)


def _header(*, load_address: int = 0x1000, payload: bytes = b"\xea\xea") -> SIDHeader:
    return SIDHeader(
        magic=b"PSID",
        version=2,
        data_offset=124,
        load_address=load_address,
        init_address=0x2000,
        play_address=0x2003,
        songs=1,
        start_song=1,
        speed=0,
        name="Test",
        author="Author",
        released="1987",
        flags=0,
        payload=payload,
    )


@pytest.mark.unit
class TestSIDInterceptMMU:
    def test_records_sid_register_writes_and_flushes_them(self) -> None:
        mmu = sid_cpu.SIDInterceptMMU(bytearray(65536))

        mmu.write(0xD400, 0x12)
        mmu.write(0xD418, 0x34)
        mmu.write(0x0400, 0x56)

        assert mmu.read(0xD400) == 0x12
        assert mmu.flush_writes() == [(0, 0x12), (24, 0x34)]
        assert mmu.flush_writes() == []


@pytest.mark.unit
class TestSIDDriver:
    def test_init_requires_py65emu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sid_cpu, "_py65emu_available", False)

        with pytest.raises(ImportError):
            sid_cpu.SIDDriver(_header())

    def test_loads_payload_into_ram_and_rejects_overflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sid_cpu, "_py65emu_available", True)
        monkeypatch.setattr(sid_cpu, "_CPU", _ScriptedCPU)

        driver = sid_cpu.SIDDriver(_header(payload=b"\xaa\xbb\xcc"))
        assert driver._ram[0x1000:0x1003] == b"\xaa\xbb\xcc"

        with pytest.raises(ValueError):
            sid_cpu.SIDDriver(_header(load_address=0xFFFF, payload=b"\xaa\xbb"))

    def test_init_tune_sets_registers_and_discards_init_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sid_cpu, "_py65emu_available", True)
        monkeypatch.setattr(sid_cpu, "_CPU", _ScriptedCPU)
        _ScriptedCPU.script = [
            lambda cpu: cpu._mmu.write(0xD400, 0x7F),
            lambda cpu: setattr(cpu.r, "pc", sid_cpu._SENTINEL_ADDR),
        ]
        driver = sid_cpu.SIDDriver(_header())

        driver.init_tune(2)

        assert driver._cpu.r.a == 2
        assert driver._cpu.r.x == 0
        assert driver._cpu.r.y == 0
        assert driver._cpu.stack_words == [sid_cpu._SENTINEL_ADDR - 1]
        assert driver._mmu.flush_writes() == []

    def test_play_frame_returns_captured_sid_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sid_cpu, "_py65emu_available", True)
        monkeypatch.setattr(sid_cpu, "_CPU", _ScriptedCPU)
        _ScriptedCPU.script = [
            lambda cpu: cpu._mmu.write(0xD405, 0x55),
            lambda cpu: setattr(cpu.r, "pc", sid_cpu._SENTINEL_ADDR),
        ]
        driver = sid_cpu.SIDDriver(_header())

        assert driver.play_frame() == [(5, 0x55)]

    def test_run_to_return_stops_when_cpu_step_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sid_cpu, "_py65emu_available", True)
        monkeypatch.setattr(sid_cpu, "_CPU", _ScriptedCPU)

        def _boom(cpu: _ScriptedCPU) -> None:
            raise RuntimeError("bad opcode")

        _ScriptedCPU.script = [_boom]
        driver = sid_cpu.SIDDriver(_header())

        driver._run_to_return(0x2345)

        assert driver._cpu.r.pc == 0x2345
        assert driver._cpu.stack_words == [sid_cpu._SENTINEL_ADDR - 1]
