"""System statistics type definitions."""

from typing_extensions import TypedDict


class MemoryStats(TypedDict):
    """Memory statistics structure."""

    total_gb: float
    available_gb: float
    percent_used: float


class DiskStats(TypedDict):
    """Disk statistics structure."""

    total_gb: float
    free_gb: float
    percent_used: float


class CpuStats(TypedDict):
    """CPU statistics structure."""

    percent_used: float


class SystemStats(TypedDict):
    """System statistics structure."""

    memory: MemoryStats
    disk: DiskStats
    cpu: CpuStats
