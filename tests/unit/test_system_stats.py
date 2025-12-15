"""Unit tests for system_stats module."""

from unittest.mock import MagicMock, patch

from teleclaude.core.system_stats import (
    get_all_stats,
    get_cpu_percent,
    get_disk_stats,
    get_memory_stats,
)


def test_get_memory_stats():
    """Test get_memory_stats returns correct structure."""
    with patch("psutil.virtual_memory") as mock_vm:
        # Mock psutil.virtual_memory()
        mock_mem = MagicMock()
        mock_mem.total = 32 * (1024**3)  # 32 GB
        mock_mem.used = 16 * (1024**3)  # 16 GB
        mock_mem.percent = 50.0
        mock_vm.return_value = mock_mem

        result = get_memory_stats()

        assert "total_gb" in result
        assert "used_gb" in result
        assert "percent" in result
        assert result["total_gb"] == 32.0
        assert result["used_gb"] == 16.0
        assert result["percent"] == 50.0


def test_get_memory_stats_error_handling():
    """Test get_memory_stats returns fallback on error."""
    with patch("psutil.virtual_memory") as mock_vm:
        mock_vm.side_effect = Exception("psutil not available")

        result = get_memory_stats()

        assert result == {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}


def test_get_disk_stats():
    """Test get_disk_stats returns correct structure."""
    with patch("shutil.disk_usage") as mock_disk:
        # Mock disk usage
        mock_usage = MagicMock()
        mock_usage.total = 1000 * (1024**3)  # 1000 GB
        mock_usage.used = 500 * (1024**3)  # 500 GB
        mock_disk.return_value = mock_usage

        result = get_disk_stats()

        assert "total_gb" in result
        assert "used_gb" in result
        assert "percent" in result
        assert result["total_gb"] == 1000.0
        assert result["used_gb"] == 500.0
        assert result["percent"] == 50.0


def test_get_disk_stats_error_handling():
    """Test get_disk_stats returns fallback on error."""
    with patch("shutil.disk_usage") as mock_disk:
        mock_disk.side_effect = OSError("Path not found")

        result = get_disk_stats()

        assert result == {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}


def test_get_cpu_percent():
    """Test get_cpu_percent returns float."""
    with patch("psutil.cpu_percent") as mock_cpu:
        mock_cpu.return_value = 75.5

        result = get_cpu_percent()

        assert isinstance(result, float)
        assert result == 75.5
        mock_cpu.assert_called_once_with(interval=0.1)


def test_get_cpu_percent_error_handling():
    """Test get_cpu_percent returns 0.0 on error."""
    with patch("psutil.cpu_percent") as mock_cpu:
        mock_cpu.side_effect = Exception("psutil not available")

        result = get_cpu_percent()

        assert result == 0.0


def test_get_all_stats():
    """Test get_all_stats returns dict with all stats."""
    with (
        patch("psutil.virtual_memory") as mock_vm,
        patch("psutil.cpu_percent") as mock_cpu,
        patch("shutil.disk_usage") as mock_disk,
    ):
        # Mock memory
        mock_mem = MagicMock()
        mock_mem.total = 32 * (1024**3)
        mock_mem.used = 16 * (1024**3)
        mock_mem.percent = 50.0
        mock_vm.return_value = mock_mem

        # Mock disk
        mock_usage = MagicMock()
        mock_usage.total = 1000 * (1024**3)
        mock_usage.used = 500 * (1024**3)
        mock_disk.return_value = mock_usage

        # Mock CPU
        mock_cpu.return_value = 25.5

        result = get_all_stats()

        assert "memory" in result
        assert "disk" in result
        assert "cpu_percent" in result
        assert isinstance(result["memory"], dict)
        assert isinstance(result["disk"], dict)
        assert isinstance(result["cpu_percent"], float)


def test_get_all_stats_partial_failure():
    """Test get_all_stats handles partial failures gracefully."""
    with (
        patch("psutil.virtual_memory") as mock_vm,
        patch("psutil.cpu_percent") as mock_cpu,
        patch("shutil.disk_usage") as mock_disk,
    ):
        # Memory fails
        mock_vm.side_effect = Exception("Memory error")

        # Disk succeeds
        mock_usage = MagicMock()
        mock_usage.total = 1000 * (1024**3)
        mock_usage.used = 500 * (1024**3)
        mock_disk.return_value = mock_usage

        # CPU succeeds
        mock_cpu.return_value = 25.5

        result = get_all_stats()

        # Memory should have fallback values
        assert result["memory"] == {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}
        # Disk and CPU should work
        assert result["disk"]["total_gb"] == 1000.0
        assert result["cpu_percent"] == 25.5
