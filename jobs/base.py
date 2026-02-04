"""Base job class and schedule definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class Schedule(Enum):
    """Job schedule frequencies."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class JobResult:
    """Result of a job execution."""

    success: bool
    message: str
    items_processed: int = 0
    errors: list[str] | None = None


class Job(ABC):
    """Base class for scheduled jobs."""

    name: str
    schedule: Schedule
    preferred_hour: int = 6  # Default to 6 AM for daily/weekly/monthly
    preferred_weekday: int = 0  # Monday for weekly (0=Mon, 6=Sun)
    preferred_day: int = 1  # 1st for monthly

    @abstractmethod
    def run(self) -> JobResult:
        """Execute the job. Returns result with success/failure info."""
        ...

    def is_due(self, last_run: datetime | None, now: datetime | None = None) -> bool:
        """Check if job is due to run based on schedule and last run time."""
        if now is None:
            now = datetime.now(timezone.utc)

        # Never run before
        if last_run is None:
            return True

        # Ensure timezone-aware
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)

        elapsed = now - last_run

        match self.schedule:
            case Schedule.HOURLY:
                return elapsed >= timedelta(hours=1)

            case Schedule.DAILY:
                # Run once per day, prefer the specified hour
                if elapsed < timedelta(hours=20):  # Min 20h between runs
                    return False
                return now.hour >= self.preferred_hour

            case Schedule.WEEKLY:
                # Run once per week, prefer the specified weekday and hour
                if elapsed < timedelta(days=6):  # Min 6 days between runs
                    return False
                return (
                    now.weekday() == self.preferred_weekday
                    and now.hour >= self.preferred_hour
                )

            case Schedule.MONTHLY:
                # Run once per month, prefer the specified day and hour
                if elapsed < timedelta(days=25):  # Min 25 days between runs
                    return False
                return (
                    now.day == self.preferred_day
                    and now.hour >= self.preferred_hour
                )

        return False
