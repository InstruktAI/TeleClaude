"""Characterization tests for teleclaude.chiptunes.sid_renderer."""

from __future__ import annotations

import struct
from datetime import timedelta

import pytest

import teleclaude.chiptunes.sid_renderer as sid_renderer


class _FakeChipModel:
    MOS6581 = "MOS6581"
    MOS8580 = "MOS8580"


class _FakeSamplingMethod:
    RESAMPLE = "RESAMPLE"


class _FakeSIDDevice:
    instances: list[_FakeSIDDevice] = []

    def __init__(
        self,
        model: object,
        sampling_method: object,
        clock_frequency: float,
        sampling_frequency: float,
    ) -> None:
        self.model = model
        self.sampling_method = sampling_method
        self.clock_frequency = clock_frequency
        self.sampling_frequency = sampling_frequency
        self.samples: list[int] = []
        self.writes: list[tuple[object, int]] = []
        self.clock_calls: list[timedelta] = []
        self.reset_calls = 0
        type(self).instances.append(self)

    def write_register(self, register: object, value: int) -> None:
        self.writes.append((register, value))

    def clock(self, duration: timedelta) -> list[int]:
        self.clock_calls.append(duration)
        return list(self.samples)

    def reset(self) -> None:
        self.reset_calls += 1


def _patch_resid(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSIDDevice.instances.clear()
    monkeypatch.setattr(sid_renderer, "_pyresidfp_available", True)
    monkeypatch.setattr(sid_renderer, "SoundInterfaceDevice", _FakeSIDDevice)
    monkeypatch.setattr(sid_renderer, "ChipModel", _FakeChipModel)
    monkeypatch.setattr(sid_renderer, "SamplingMethod", _FakeSamplingMethod)
    monkeypatch.setattr(sid_renderer, "_REGISTER_MAP", ["REG0", "REG1"])


@pytest.mark.unit
class TestSIDRenderer:
    def test_init_requires_pyresidfp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sid_renderer, "_pyresidfp_available", False)

        with pytest.raises(ImportError):
            sid_renderer.SIDRenderer()

    def test_init_uses_selected_clock_and_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_resid(monkeypatch)

        renderer = sid_renderer.SIDRenderer(sample_rate=44100, chip_model="MOS8580", pal=False, volume=1.0)
        device = _FakeSIDDevice.instances[-1]

        assert renderer.sample_rate == 44100
        assert device.model == _FakeChipModel.MOS8580
        assert device.sampling_method == _FakeSamplingMethod.RESAMPLE
        assert device.clock_frequency == float(sid_renderer._NTSC_CLOCK)
        assert device.sampling_frequency == 44100.0

    def test_render_frame_applies_valid_registers_and_scales_samples(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_resid(monkeypatch)
        renderer = sid_renderer.SIDRenderer(volume=0.5)
        device = _FakeSIDDevice.instances[-1]
        device.samples = [70000, -70000, 1000]

        pcm = renderer.render_frame([(0, 0x11), (3, 0x22)], 0.02)

        assert device.writes == [("REG0", 0x11)]
        assert device.clock_calls == [timedelta(seconds=0.02)]
        assert struct.unpack("<3h", pcm) == (32767, -32768, 500)

    def test_render_frame_returns_silence_when_clock_returns_no_samples(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_resid(monkeypatch)
        renderer = sid_renderer.SIDRenderer(sample_rate=100)

        pcm = renderer.render_frame([], 0.05)

        assert pcm == bytes(10)

    def test_reset_delegates_to_sid_device(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_resid(monkeypatch)
        renderer = sid_renderer.SIDRenderer()
        device = _FakeSIDDevice.instances[-1]

        renderer.reset()

        assert device.reset_calls == 1
