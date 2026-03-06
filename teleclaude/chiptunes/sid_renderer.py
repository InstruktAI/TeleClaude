"""SID chip emulation renderer using pyresidfp."""

from __future__ import annotations

import array
from datetime import timedelta

try:
    from pyresidfp import SoundInterfaceDevice, WritableRegister  # type: ignore[import-untyped]
    from pyresidfp._pyresidfp import ChipModel, SamplingMethod  # type: ignore[import-untyped]

    _pyresidfp_available = True  # pylint: disable=invalid-name

    # Map SID register offsets (0-24) to pyresidfp WritableRegister enum values
    _REGISTER_MAP: list[WritableRegister] = list(WritableRegister)  # pyright: ignore[reportInvalidTypeForm]
except ImportError:
    _pyresidfp_available = False  # pylint: disable=invalid-name
    SoundInterfaceDevice = None  # type: ignore[assignment]
    WritableRegister = None  # type: ignore[assignment]
    ChipModel = None  # type: ignore[assignment]
    SamplingMethod = None  # type: ignore[assignment]
    _REGISTER_MAP = []  # type: ignore[assignment]

# SID chip clock frequencies
_PAL_CLOCK = 985248  # Hz
_NTSC_CLOCK = 1022730  # Hz


class SIDRenderer:
    """Wraps pyresidfp.SoundInterfaceDevice to render SID register writes to PCM."""

    def __init__(
        self,
        sample_rate: int = 48000,
        chip_model: str = "MOS6581",
        pal: bool = True,
        volume: float = 1.0,
    ) -> None:
        if not _pyresidfp_available:
            raise ImportError(
                "pyresidfp is required for SID playback. Install it with: pip install 'teleclaude[chiptunes]'"
            )
        self._sample_rate = sample_rate
        self._clock_freq = _PAL_CLOCK if pal else _NTSC_CLOCK
        self._volume = max(0.0, min(1.0, volume))

        model_enum = ChipModel.MOS6581 if chip_model == "MOS6581" else ChipModel.MOS8580
        self._sid = SoundInterfaceDevice(
            model=model_enum,
            sampling_method=SamplingMethod.RESAMPLE,
            clock_frequency=float(self._clock_freq),
            sampling_frequency=float(sample_rate),
        )

    def render_frame(
        self,
        writes: list[tuple[int, int]],
        frame_duration_s: float,
    ) -> bytes:
        """Apply register writes, clock the SID, and return int16 PCM bytes.

        Args:
            writes: List of (register_offset, value) pairs from the CPU driver.
            frame_duration_s: Duration of this frame in seconds.

        Returns:
            Raw int16 little-endian PCM bytes.
        """
        # Apply register writes (map integer offsets to WritableRegister enum)
        for reg, val in writes:
            if 0 <= reg < len(_REGISTER_MAP):
                self._sid.write_register(_REGISTER_MAP[reg], val)

        # Clock the SID for frame_duration_s
        samples: list[int] = self._sid.clock(timedelta(seconds=frame_duration_s))

        if not samples:
            expected = int(self._sample_rate * frame_duration_s)
            return bytes(expected * 2)  # silence

        # Apply volume scaling and clamp to int16 range
        if self._volume != 1.0:
            scale = self._volume
            samples = [int(s * scale) for s in samples]

        # Clamp to [-32768, 32767]
        samples = [max(-32768, min(32767, s)) for s in samples]

        return array.array("h", samples).tobytes()

    def reset(self) -> None:
        """Reset the SID chip state."""
        self._sid.reset()

    @property
    def sample_rate(self) -> int:
        """Return the configured sample rate in Hz."""
        return self._sample_rate
