"""What started a maintenance run, and the marker that tells a command it was started on demand."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["DRAIN_HELD_ENV", "DRAIN_HELD_VALUE", "ON_DEMAND_TRIGGER_ENV", "MaintenanceTrigger"]

# The shell installers read this variable by name (bin/install.sh, bin/init/install_services.sh) and
# compare it with the value of ``MaintenanceTrigger.ON_DEMAND``; the name and the value live here once.
ON_DEMAND_TRIGGER_ENV = "TELECLAUDE_MAINTENANCE_TRIGGER"

# Every command a drain or an on-demand run starts carries this marker: the run already holds the
# checkout's maintenance serialization, so a command that would otherwise take it (the installer's
# release posture step, bin/install.sh) must not take it again from its own process. The name and the
# value live here once.
DRAIN_HELD_ENV = "TELECLAUDE_MAINTENANCE_DRAIN_HELD"
DRAIN_HELD_VALUE = "1"


class MaintenanceTrigger(StrEnum):
    """What started a maintenance run: a commit-boundary drain, a platform event, or a manual on-demand run."""

    COMMIT_BOUNDARY = "commit_boundary"
    EVENT = "event"
    ON_DEMAND = "on_demand"
