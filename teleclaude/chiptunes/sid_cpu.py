"""6502 CPU driver with SID register interception using py65emu."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

try:
    from py65emu.cpu import CPU as _CPU
    from py65emu.mmu import MMU

    _py65emu_available = True  # pylint: disable=invalid-name
except ImportError:
    _py65emu_available = False  # pylint: disable=invalid-name
    _CPU = None  # type: ignore[unused-ignore]
    MMU = object  # type: ignore[unused-ignore]

if TYPE_CHECKING:
    from teleclaude.chiptunes.sid_parser import SIDHeader

logger = get_logger(__name__)

# SID register range on the C64 memory map
_SID_BASE = 0xD400
_SID_END = 0xD418  # inclusive — 25 registers $D400–$D418

_MAX_CYCLES_PER_FRAME = 100_000  # runaway protection

# Sentinel return address pushed before JSR stubs so we know when the routine returns
_SENTINEL_ADDR = 0xFFFF


class SIDInterceptMMU(MMU):  # type: ignore[misc]
    """64KB address space that captures writes to SID registers $D400–$D418."""

    def __init__(self, ram: bytearray) -> None:
        super().__init__()
        self._ram = ram
        self._sid_writes: list[tuple[int, int]] = []

    def read(self, addr: int) -> int:
        """Read a byte from the 64KB address space."""
        return self._ram[addr & 0xFFFF]

    def write(self, addr: int, value: int) -> None:
        """Write a byte; intercept SID register range $D400–$D418."""
        addr &= 0xFFFF
        if _SID_BASE <= addr <= _SID_END:
            self._sid_writes.append((addr - _SID_BASE, value & 0xFF))
        self._ram[addr] = value & 0xFF

    def flush_writes(self) -> list[tuple[int, int]]:
        """Drain and return captured SID register writes."""
        writes, self._sid_writes = self._sid_writes, []
        return writes


class SIDDriver:
    """Loads a SID tune into 64KB RAM and drives init/play cycles."""

    def __init__(self, header: SIDHeader) -> None:
        if not _py65emu_available:
            raise ImportError(
                "py65emu is required for SID playback. Install it with: pip install 'teleclaude[chiptunes]'"
            )
        self._header = header
        self._ram = bytearray(65536)
        self._mmu = SIDInterceptMMU(self._ram)

        # Load payload at load_address
        end = header.load_address + len(header.payload)
        if end > 0x10000:
            raise ValueError(f"SID payload exceeds 64KB address space: {end:#06x}")
        self._ram[header.load_address : end] = header.payload

        self._cpu = _CPU(self._mmu)

    def init_tune(self, subtune: int = 0) -> None:
        """Execute the SID init routine for a subtune (0-based)."""
        self._cpu.r.a = subtune
        self._cpu.r.x = 0
        self._cpu.r.y = 0
        self._run_to_return(self._header.init_address)
        # Discard any SID writes during init (they're part of setup, not audio)
        self._mmu.flush_writes()

    def play_frame(self) -> list[tuple[int, int]]:
        """Execute one SID play frame and return captured register writes."""
        self._run_to_return(self._header.play_address)
        return self._mmu.flush_writes()

    def _run_to_return(self, start_addr: int) -> None:
        """Execute from start_addr until the routine RTS back to sentinel."""
        # Push sentinel return address (PC will land at _SENTINEL_ADDR after RTS)
        self._push_word(_SENTINEL_ADDR - 1)  # RTS pops addr+1
        self._cpu.r.pc = start_addr & 0xFFFF

        self._cpu.cc = 0
        while self._cpu.cc < _MAX_CYCLES_PER_FRAME:
            if self._cpu.r.pc == _SENTINEL_ADDR:
                break
            try:
                self._cpu.step()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.debug("CPU exception during emulation: %s", exc)
                break

    def _push_word(self, word: int) -> None:
        """Push a 16-bit value onto the 6502 stack (big-endian, high byte first)."""
        self._cpu.stackPushWord(word)
