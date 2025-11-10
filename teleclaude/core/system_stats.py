"""System statistics collection for computer monitoring."""

import logging
import shutil

logger = logging.getLogger(__name__)


def get_memory_stats() -> dict[str, float]:
    """Get memory usage statistics.

    Returns:
        Dict with total_gb, used_gb, percent
    """
    try:
        import psutil

        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent": round(mem.percent, 2),
        }
    except Exception as e:
        logger.warning("Failed to get memory stats: %s", e)
        return {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}


def get_disk_stats(path: str = "/") -> dict[str, float]:
    """Get disk usage statistics.

    Args:
        path: Path to check (default: root filesystem)

    Returns:
        Dict with total_gb, used_gb, percent
    """
    try:
        stat = shutil.disk_usage(path)
        total_gb = stat.total / (1024**3)
        used_gb = stat.used / (1024**3)
        percent = (stat.used / stat.total) * 100

        return {
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "percent": round(percent, 2),
        }
    except Exception as e:
        logger.warning("Failed to get disk stats: %s", e)
        return {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}


def get_cpu_percent() -> float:
    """Get current CPU usage percentage.

    Returns:
        CPU usage percent (0-100)
    """
    try:
        import psutil

        cpu_value: float = psutil.cpu_percent(interval=0.1)
        return round(cpu_value, 2)
    except Exception as e:
        logger.warning("Failed to get CPU stats: %s", e)
        return 0.0


def get_all_stats() -> dict[str, object]:
    """Get all system statistics.

    Returns:
        Dict with memory, disk, cpu_percent
    """
    return {
        "memory": get_memory_stats(),
        "disk": get_disk_stats(),
        "cpu_percent": get_cpu_percent(),
    }
