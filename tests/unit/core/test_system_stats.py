"""Characterization tests for teleclaude.core.system_stats."""

from __future__ import annotations

import pytest

from teleclaude.core.system_stats import get_all_stats, get_cpu_percent, get_disk_stats, get_memory_stats


class TestGetMemoryStats:
    @pytest.mark.unit
    def test_returns_required_keys(self):
        stats = get_memory_stats()
        assert "total_gb" in stats
        assert "used_gb" in stats
        assert "percent" in stats

    @pytest.mark.unit
    def test_values_are_floats(self):
        stats = get_memory_stats()
        assert isinstance(stats["total_gb"], float)
        assert isinstance(stats["used_gb"], float)
        assert isinstance(stats["percent"], float)
        assert stats["total_gb"] > 0.0

    @pytest.mark.unit
    def test_percent_in_valid_range(self):
        stats = get_memory_stats()
        assert 0.0 <= stats["percent"] <= 100.0


class TestGetDiskStats:
    @pytest.mark.unit
    def test_returns_required_keys(self):
        stats = get_disk_stats()
        assert "total_gb" in stats
        assert "used_gb" in stats
        assert "percent" in stats

    @pytest.mark.unit
    def test_default_path_is_root(self):
        stats = get_disk_stats()
        assert stats["total_gb"] >= 0.0

    @pytest.mark.unit
    def test_accepts_custom_path(self):
        import tempfile

        stats = get_disk_stats(tempfile.gettempdir())
        assert stats["total_gb"] >= 0.0

    @pytest.mark.unit
    def test_invalid_path_returns_zeros(self):
        stats = get_disk_stats("/nonexistent/path/xyz123")
        assert stats == {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}


class TestGetCpuPercent:
    @pytest.mark.unit
    def test_returns_float(self):
        cpu = get_cpu_percent()
        assert isinstance(cpu, float)

    @pytest.mark.unit
    def test_in_valid_range(self):
        cpu = get_cpu_percent()
        assert 0.0 <= cpu <= 100.0


class TestGetAllStats:
    @pytest.mark.unit
    def test_returns_expected_top_level_keys(self):
        stats = get_all_stats()
        assert "memory" in stats
        assert "disk" in stats
        assert "cpu_percent" in stats

    @pytest.mark.unit
    def test_memory_is_dict(self):
        stats = get_all_stats()
        assert isinstance(stats["memory"], dict)

    @pytest.mark.unit
    def test_cpu_percent_is_float(self):
        stats = get_all_stats()
        assert isinstance(stats["cpu_percent"], float)
