"""Job run lifecycle status shared by cron state and API surfaces."""

from enum import StrEnum


class JobRunStatus(StrEnum):
    """Finite state for a recurring job run."""

    NEVER = "never"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    STALLED = "stalled"
