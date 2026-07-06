"""Core-owned error contract adapters raise and core catches at delivery boundaries."""

from __future__ import annotations


class AdapterError(Exception):
    """Base exception for adapter errors."""


class ChannelNotProvisionedError(AdapterError):
    """Raised when a session has no UI channel mapping yet.

    This is an expected, recoverable condition during reconciliation and
    on the first output tick of a session: the lane has nothing to deliver
    to because provisioning has not yet completed (or did not run for this
    session's origin). Adapters should catch it in ``recover_lane_error``,
    log at ``info`` level, and skip the lane without surfacing a lane error.
    """
