"""Characterization tests for teleclaude.types.system."""

from __future__ import annotations

from typing import get_type_hints

from teleclaude.types.system import CpuStats, DiskStats, MemoryStats, SystemStats


def test_leaf_typed_dicts_build_plain_dicts_with_required_keys() -> None:
    memory = MemoryStats(total_gb=32.0, available_gb=12.5, percent_used=60.9)
    disk = DiskStats(total_gb=512.0, free_gb=128.0, percent_used=75.0)
    cpu = CpuStats(percent_used=27.5)

    assert memory == {"total_gb": 32.0, "available_gb": 12.5, "percent_used": 60.9}
    assert disk == {"total_gb": 512.0, "free_gb": 128.0, "percent_used": 75.0}
    assert cpu == {"percent_used": 27.5}
    assert MemoryStats.__required_keys__ == frozenset({"total_gb", "available_gb", "percent_used"})
    assert DiskStats.__required_keys__ == frozenset({"total_gb", "free_gb", "percent_used"})
    assert CpuStats.__required_keys__ == frozenset({"percent_used"})


def test_system_stats_references_nested_typed_dicts() -> None:
    payload = SystemStats(
        memory=MemoryStats(total_gb=16.0, available_gb=4.0, percent_used=75.0),
        disk=DiskStats(total_gb=256.0, free_gb=64.0, percent_used=75.0),
        cpu=CpuStats(percent_used=19.5),
    )

    assert payload["memory"]["available_gb"] == 4.0
    assert payload["disk"]["free_gb"] == 64.0
    assert payload["cpu"]["percent_used"] == 19.5
    assert get_type_hints(SystemStats) == {"memory": MemoryStats, "disk": DiskStats, "cpu": CpuStats}
